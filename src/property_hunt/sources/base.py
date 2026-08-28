from __future__ import annotations
import asyncio, hashlib, json, time
from abc import ABC, abstractmethod
from typing import Generic, TypeVar
import httpx
from pydantic import BaseModel, Field
from property_hunt.config import HTTPConfig
from property_hunt.models import SourceDiagnostic
T=TypeVar("T")
class Page(BaseModel, Generic[T]):
    records:list[T]=Field(default_factory=list); next_cursor:str|None=None
class FetchResult(BaseModel, Generic[T]):
    records:list[T]=Field(default_factory=list); diagnostics:list[SourceDiagnostic]=Field(default_factory=list); complete:bool=True
class SourceAdapter(ABC, Generic[T]):
    name="base"
    def __init__(self,http:HTTPConfig,client:httpx.AsyncClient|None=None):
        self.policy=http; self.client=client or httpx.AsyncClient(timeout=http.timeout_seconds,follow_redirects=True,headers={"User-Agent": http.user_agent}); self.cache:dict[str,bytes]={}; self._last=0.0
    async def request(self,url:str)->bytes:
        if url in self.cache:return self.cache[url]
        await asyncio.sleep(max(0,1/self.policy.rate_limit_per_second-(time.monotonic()-self._last)))
        error:Exception|None=None
        for attempt in range(self.policy.retries+1):
            try:
                response=await self.client.get(url); response.raise_for_status(); self._last=time.monotonic(); self.cache[url]=response.content; return response.content
            except (httpx.TimeoutException,httpx.HTTPStatusError,httpx.NetworkError) as exc:
                error=exc
                if attempt<self.policy.retries: await asyncio.sleep(self.policy.backoff_seconds*2**attempt)
        raise RuntimeError(f"{self.name} request failed after bounded retries: {error}")
    @staticmethod
    def payload_hash(payload:bytes)->str:return hashlib.sha256(payload).hexdigest()
    @abstractmethod
    async def fetch(self,**kwargs:object)->FetchResult[T]:...
    async def close(self)->None: await self.client.aclose()

    async def browser_request(self, url: str) -> bytes:
        """Fetch rendered HTML when explicitly enabled by the caller.

        Browser use is deliberately opt-in.  It does not bypass authentication,
        CAPTCHAs, robots directives, or access controls.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("browser fallback requires: pip install 'property-hunt[browser]' && playwright install chromium") from exc
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=self.policy.user_agent)
            try:
                await page.goto(url, wait_until="networkidle", timeout=int(self.policy.browser_timeout_seconds * 1000))
                return (await page.content()).encode()
            finally:
                await browser.close()
def unsupported(source:str,message:str)->FetchResult:
    return FetchResult(complete=False,diagnostics=[SourceDiagnostic(source=source,status="unsupported",message=message,partial=True)])
