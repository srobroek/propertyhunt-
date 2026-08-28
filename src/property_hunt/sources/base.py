from __future__ import annotations

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

import httpx
from pydantic import BaseModel, Field

from property_hunt.config import HTTPConfig
from property_hunt.models import SourceDiagnostic

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    records: list[T] = Field(default_factory=list)
    next_cursor: str | None = None


class FetchResult(BaseModel, Generic[T]):
    records: list[T] = Field(default_factory=list)
    diagnostics: list[SourceDiagnostic] = Field(default_factory=list)
    complete: bool = True


class SourceAdapter(ABC, Generic[T]):
    name = "base"

    def __init__(self, http: HTTPConfig, client: httpx.AsyncClient | None = None):
        self.policy = http
        self.client = client or httpx.AsyncClient(
            timeout=http.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": http.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
        )
        self.cache: dict[str, bytes] = {}
        self._last = 0.0

    async def request(self, url: str) -> bytes:
        if url in self.cache:
            return self.cache[url]
        await asyncio.sleep(
            max(0, 1 / self.policy.rate_limit_per_second - (time.monotonic() - self._last))
        )
        error: Exception | None = None
        for attempt in range(self.policy.retries + 1):
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                self._last = time.monotonic()
                self.cache[url] = response.content
                return response.content
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.NetworkError) as exc:
                error = exc
                if attempt < self.policy.retries:
                    await asyncio.sleep(self.policy.backoff_seconds * 2**attempt)
        raise RuntimeError(f"{self.name} request failed after bounded retries: {error}")

    @staticmethod
    def payload_hash(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def challenge_detected(payload: bytes) -> bool:
        text = payload.decode("utf-8", errors="ignore").lower()
        markers = (
            "verify you are human",
            "captcha",
            "cf-chl-",
            "cloudflare challenge",
            "access denied",
            "unusual traffic",
        )
        return any(marker in text for marker in markers)

    @abstractmethod
    async def fetch(self, **kwargs: object) -> FetchResult[T]: ...

    async def close(self) -> None:
        await self.client.aclose()

    async def browser_request(self, url: str) -> bytes:
        """Fetch rendered public HTML when explicitly enabled by the caller.

        Browser use does not solve CAPTCHAs, bypass authentication, or defeat an
        explicit access-control challenge. Such responses are detected and
        returned to the adapter for a partial-source diagnostic.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "browser fallback requires: pip install 'property-hunt[browser]' "
                "&& playwright install chromium"
            ) from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.policy.user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 1000},
            )
            page = await context.new_page()
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.policy.browser_timeout_seconds * 1000),
                )
                try:
                    await page.wait_for_load_state(
                        "networkidle", timeout=min(10_000, int(self.policy.browser_timeout_seconds * 1000))
                    )
                except Exception:
                    pass
                return (await page.content()).encode()
            finally:
                await context.close()
                await browser.close()


def unsupported(source: str, message: str) -> FetchResult:
    return FetchResult(
        complete=False,
        diagnostics=[
            SourceDiagnostic(
                source=source,
                status="unsupported",
                message=message,
                partial=True,
            )
        ],
    )
