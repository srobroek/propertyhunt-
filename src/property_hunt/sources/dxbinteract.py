from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from property_hunt.models import MarketMetric, Provenance, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported

DEFAULT_URL = "https://dxbinteract.com/market-reports/2026/Q2"


def _money(value: str, unit: str | None) -> float:
    number = float(value.replace(",", ""))
    if not unit:
        return number
    scale = {"thousand": 1e3, "million": 1e6, "billion": 1e9}.get(unit.lower(), 1.0)
    return number * scale


class DXBInteractAdapter(SourceAdapter[MarketMetric]):
    """Parse publicly published DXBinteract market-report headline metrics.

    This is secondary/aggregate evidence. It must not replace DLD transaction-level
    comparables where official records are available.
    """

    name = "dxbinteract"

    @staticmethod
    def parse(payload: bytes, url: str) -> list[MarketMetric]:
        text = re.sub(r"\s+", " ", payload.decode("utf-8", errors="ignore"))
        period_match = re.search(
            r"(?:Market Report|Analysis)\s*[–-]?\s*((?:Q[1-4]|January|February|March|April|May|June|July|August|September|October|November|December)[, ]+20\d{2})",
            text,
            re.I,
        )
        if not period_match:
            period_match = re.search(r"/(20\d{2})/(Q[1-4]|[A-Za-z]+)", url)
            period = (
                f"{period_match.group(2)} {period_match.group(1)}" if period_match else "unknown"
            )
        else:
            period = period_match.group(1)

        patterns = [
            re.compile(
                r"All sales\s*[|:]\s*([0-9,]+)\s*[|:]\s*AED\s*([0-9.,]+)\s*(billion|million|thousand)?\s*[|:]\s*AED\s*([0-9,]+)\s*/\s*sqft",
                re.I,
            ),
            re.compile(
                r"recorded\s+([0-9,]+)\s+transactions\s+worth\s+AED\s*([0-9.,]+)\s*(billion|million|thousand)?.{0,120}?AED\s*([0-9,]+)\s*(?:per square foot|/sqft)",
                re.I,
            ),
        ]
        match = next((p.search(text) for p in patterns if p.search(text)), None)
        if not match:
            return []
        count = int(match.group(1).replace(",", ""))
        value = _money(match.group(2), match.group(3))
        psf = float(match.group(4).replace(",", ""))
        sid = hashlib.sha256(f"{period}|all-sales|{url}".encode()).hexdigest()[:16]
        return [
            MarketMetric(
                id=f"dxbinteract:{sid}",
                source="dxbinteract",
                period=period,
                segment="all sales",
                transaction_count=count,
                transaction_value_aed=value,
                median_price_psf=psf,
                provenance=Provenance(
                    source="dxbinteract",
                    source_id=sid,
                    url=url,
                    fetched_at=datetime.now(timezone.utc),
                    method="public-market-report-html",
                ),
            )
        ]

    async def fetch(self, **kwargs: object) -> FetchResult[MarketMetric]:
        url = str(kwargs.get("url") or DEFAULT_URL)
        allow_browser = bool(kwargs.get("allow_browser", False))
        if not url:
            return unsupported(self.name, "No public DXBinteract market report URL configured")
        try:
            payload = await self.request(url)
            records = self.parse(payload, url)
            if not records and allow_browser:
                payload = await self.browser_request(url)
                records = self.parse(payload, url)
            return FetchResult(
                records=records,
                diagnostics=[
                    SourceDiagnostic(
                        source=self.name,
                        status="ok" if records else "partial",
                        message="public DXBinteract market report parsed",
                        records=len(records),
                        pages=1,
                        attempts=1,
                        partial=not bool(records),
                        details={"role": "secondary aggregate market evidence", "url": url},
                    )
                ],
                complete=bool(records),
            )
        except Exception as exc:
            return FetchResult(
                complete=False,
                diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)],
            )
