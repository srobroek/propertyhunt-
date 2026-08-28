from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
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

    async def _rod_request(self, url: str) -> bytes | None:
        """Use the bundled Rod helper when it is available.

        Rod drives a normal Chromium instance with the configured browser user
        agent, language, and viewport. It is used for JavaScript rendering and
        normal browser compatibility only; challenge pages are still surfaced
        to the adapter and are not solved or bypassed.
        """
        rod_bin = Path(os.getenv("PROPERTY_HUNT_ROD_BIN", "bin/rod-fetch"))
        if not rod_bin.is_file():
            return None

        proc = await asyncio.create_subprocess_exec(
            str(rod_bin),
            "--url",
            url,
            "--user-agent",
            self.policy.user_agent,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.policy.browser_timeout_seconds + 15
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return None

        if proc.returncode != 0 or not stdout:
            _ = stderr
            return None
        return stdout

    async def browser_request(self, url: str) -> bytes:
        """Fetch rendered public HTML, preferring Rod and falling back to Playwright.

        Neither backend solves CAPTCHAs, bypasses authentication, or defeats an
        explicit access-control challenge. Such responses are detected by the
        source adapter and reported as partial-source diagnostics.
        """
        rendered = await self._rod_request(url)
        if rendered is not None:
            return rendered

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "browser fallback requires Rod (`bin/rod-fetch`) or: "
                "pip install 'property-hunt[browser]' && playwright install chromium"
            ) from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.policy.user_agent,
                locale="en-US",
                timezone_id="Asia/Dubai",
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
                        "networkidle",
                        timeout=min(10_000, int(self.policy.browser_timeout_seconds * 1000)),
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
