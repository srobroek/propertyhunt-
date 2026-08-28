from __future__ import annotations

import asyncio
import hashlib
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel, Field

from property_hunt.config import HTTPConfig
from property_hunt.models import SourceDiagnostic

T = TypeVar("T")


@dataclass(frozen=True)
class BrowserProfile:
    name: str
    languages: tuple[str, ...]
    timezone: str
    window_width: int
    window_height: int
    browser_class: str = "desktop"


REALISTIC_PROFILE = BrowserProfile(
    BrowserFingerprint(

        name="Windows desktop",

        os="Windows 11",

        user_agent_family="Chrome/Chromium Windows",

        user_agent=(

            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "

            "AppleWebKit/537.36 (KHTML, like Gecko) "

            "Chrome/151.0.0.0 Safari/537.36"

        ),

        platform="Win32",

        languages=("en-US", "en"),

        timezone="America/New_York",

        screen_width=1920,

        screen_height=1080,

        color_depth=24,

        hardware_concurrency=8,

        device_memory_gb=16,

        max_touch_points=0,

        webdriver=False,

        gpu_class="desktop GPU",

        browser_class="desktop",
)


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
        self.browser_profile = REALISTIC_PROFILE
        self.client = client or httpx.AsyncClient(
            timeout=http.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": http.user_agent,
                "Accept-Language": ",".join(self.browser_profile.languages),
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
        )
        self.cache: dict[str, bytes] = {}
        self._last = 0.0
        self._nodriver_browser: Any | None = None

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
        if self._nodriver_browser is not None:
            try:
                self._nodriver_browser.stop()
                await asyncio.sleep(0.1)
            except Exception:
                pass
            self._nodriver_browser = None

    async def _nodriver_request(self, url: str) -> bytes | None:
        """Render a public page with nodriver and the runner's installed Chrome."""
        try:
            import nodriver as uc
        except ImportError:
            return None

        profile = self.browser_profile
        if self._nodriver_browser is None:
            chrome_bin = os.getenv("CHROME_BIN") or None
            browser_args = [
                f"--window-size={profile.window_width},{profile.window_height}",
                "--disable-dev-shm-usage",
            ]
            try:
                self._nodriver_browser = await uc.start(
                    headless=False,
                    browser_executable_path=chrome_bin,
                    browser_args=browser_args,
                    lang=profile.languages[0],
                    expert=False,
                )
            except Exception:
                self._nodriver_browser = None
                return None

        try:
            page = await self._nodriver_browser.get(url)
            try:
                await page.send(
                    uc.cdp.emulation.set_timezone_override(timezone_id=profile.timezone)
                )
            except Exception:
                pass
            await page.sleep(1.5)
            html = await page.get_content()
            return html.encode("utf-8") if html else None
        except Exception:
            return None

    async def browser_request(self, url: str) -> bytes:
        """Fetch rendered public HTML, preferring nodriver and falling back to Playwright."""
        rendered = await self._nodriver_request(url)
        if rendered is not None:
            return rendered

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("browser fallback requires property-hunt[browser]") from exc

        profile = self.browser_profile
        async with async_playwright() as playwright:
            launch_kwargs: dict[str, object] = {"headless": True}
            chrome_bin = os.getenv("CHROME_BIN")
            if chrome_bin:
                launch_kwargs["executable_path"] = chrome_bin
            browser = await playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                locale=profile.languages[0],
                timezone_id=profile.timezone,
                viewport={"width": profile.window_width, "height": profile.window_height},
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
