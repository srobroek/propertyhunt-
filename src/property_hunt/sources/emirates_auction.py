from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from urllib.parse import urljoin

from property_hunt.models import AuctionRecord, Provenance, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported

DEFAULT_URL = "https://www.emiratesauction.com/auction-calendar"
DETAIL_PATTERN = re.compile(r"https?://(?:www\.)?emiratesauction\.com/auctions/properties/\d+/\d+/[^\"'<>\s]+", re.I)


def _text(payload: bytes) -> str:
    raw = payload.decode("utf-8", errors="ignore")
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " ").split())


def _float(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", value)
    return float(match.group(0).replace(",", "")) if match else None


def _parse_date(text: str) -> datetime | None:
    match = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{1,2}:\d{2})\s*(AM|PM)\b", text)
    if not match:
        return None
    year = datetime.now().year
    try:
        return datetime.strptime(f"{match.group(1)} {match.group(2)} {year} {match.group(3)} {match.group(4)}", "%b %d %Y %I:%M %p")
    except ValueError:
        return None


class EmiratesAuctionAdapter(SourceAdapter[AuctionRecord]):
    name = "emirates_auction"

    @staticmethod
    def extract_detail_links(payload: bytes, base_url: str) -> list[str]:
        raw = payload.decode("utf-8", errors="ignore")
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I)
        links: list[str] = []
        seen: set[str] = set()
        for href in hrefs:
            url = urljoin(base_url, href)
            if "/auctions/properties/" not in url:
                continue
            if url not in seen:
                seen.add(url)
                links.append(url)
        for match in DETAIL_PATTERN.finditer(raw):
            url = match.group(0)
            if url not in seen:
                seen.add(url)
                links.append(url)
        return links

    @staticmethod
    def parse_detail(payload: bytes, url: str) -> list[AuctionRecord]:
        text = _text(payload)
        if not text:
            return []
        title_match = re.search(r"(?:Image:\s*)?([^|]{3,120}?\s+-\s+(?:Apartment|Villa|Residential Building|Building|Land))\b", text, re.I)
        if not title_match:
            h = re.search(r"^(?:Image\s+)?(.{3,100}?)(?:\s+undefined\s+#|\s+\d[\d,.]*\s*ft²)", text)
            title = h.group(1).strip() if h else "Emirates Auction Property"
        else:
            title = title_match.group(1).strip()

        area = _float((re.search(r"Total Area\s*:?[ ]*([0-9,.]+)\s*sq\.?\s*ft", text, re.I) or re.search(r"Area\s+([0-9,.]+)\s*ft²", text, re.I)).group(1) if (re.search(r"Total Area\s*:?[ ]*([0-9,.]+)\s*sq\.?\s*ft", text, re.I) or re.search(r"Area\s+([0-9,.]+)\s*ft²", text, re.I)) else None)
        beds_match = re.search(r"\b(\d+)\s*BR\b", text, re.I) or re.search(r"\b(\d+)\s+Bedrooms?\b", text, re.I)
        bedrooms = int(beds_match.group(1)) if beds_match else None
        location_match = re.search(r"Location\s+([A-Za-z0-9 .'-]+?)\s+Emirate\s+(Dubai|Sharjah|Ajman|Abu Dhabi|Ras Al Khaimah|Fujairah|Umm Al Quwain)", text, re.I)
        location = location_match.group(1).strip() if location_match else None
        emirate = location_match.group(2) if location_match else None
        if emirate and emirate.lower() != "dubai":
            return []
        property_type_match = re.search(r"Land use\s+([A-Za-z ]+?)\s+Location", text, re.I)
        property_type = property_type_match.group(1).strip() if property_type_match else None

        cheque = re.search(r"manager.?s cheque of at least\s+AED\s*([0-9,]+)", text, re.I)
        reserve = _float(cheque.group(1)) * 5 if cheque and _float(cheque.group(1)) is not None else None
        current_bid_match = re.search(r"(?:Current Bid|Bid)\s*AED\s*([0-9,]+)", text, re.I)
        current_bid = _float(current_bid_match.group(1)) if current_bid_match else None

        auction_dt = _parse_date(text)
        rented = re.search(r"Rented(?:\s+till\s+[^,]+)?\s*,?\s*Rent Value\s*([0-9,.]+)\s*AED", text, re.I)
        vacant = bool(re.search(r"\bVacant\b", text, re.I))
        viewing = bool(re.search(r"Viewing Available", text, re.I))
        status_parts = ["vacant" if vacant else "rented" if re.search(r"\bRented\b", text, re.I) else "unknown occupancy"]
        if viewing:
            status_parts.append("viewing available")
        rent_value = _float(rented.group(1)) if rented else None
        if rent_value:
            status_parts.append(f"rent_aed_{int(rent_value)}")

        sid_match = re.search(r"/properties/(\d+)/", url)
        sid = sid_match.group(1) if sid_match else hashlib.sha256(url.encode()).hexdigest()[:16]
        return [
            AuctionRecord(
                id=f"emirates-auction:{sid}",
                title=title,
                url=url,
                location=location,
                property_type=property_type,
                auction_date=auction_dt.date() if auction_dt else None,
                current_bid_aed=current_bid,
                reserve_aed=reserve,
                area_sqft=area,
                bedrooms=bedrooms,
                status="; ".join(status_parts),
                provenance=Provenance(
                    source="emirates_auction",
                    source_id=sid,
                    url=url,
                    method="public-auction-detail-html",
                ),
            )
        ]

    async def fetch(self, **kwargs: object) -> FetchResult[AuctionRecord]:
        start_url = str(kwargs.get("url") or DEFAULT_URL)
        allow_browser = bool(kwargs.get("allow_browser", False))
        max_pages = max(1, int(kwargs.get("max_pages", 1)))
        if not start_url:
            return unsupported(self.name, "No Emirates Auction URL configured")
        try:
            payload = await self.request(start_url)
            links = self.extract_detail_links(payload, start_url)
            if not links and allow_browser:
                payload = await self.browser_request(start_url)
                links = self.extract_detail_links(payload, start_url)
            records: dict[str, AuctionRecord] = {}
            attempts = 0
            for detail_url in links[: max_pages * 50]:
                attempts += 1
                try:
                    detail = await self.request(detail_url)
                    parsed = self.parse_detail(detail, detail_url)
                    if not parsed and allow_browser:
                        parsed = self.parse_detail(await self.browser_request(detail_url), detail_url)
                    for record in parsed:
                        records[record.id] = record
                except Exception:
                    continue
            return FetchResult(
                records=list(records.values()),
                diagnostics=[
                    SourceDiagnostic(
                        source=self.name,
                        status="ok" if records else "partial",
                        message="public Emirates Auction property inventory parsed",
                        records=len(records),
                        pages=1,
                        attempts=attempts,
                        partial=not bool(records),
                        details={"detail_links": len(links), "dubai_only": True},
                    )
                ],
                complete=bool(records),
            )
        except Exception as exc:
            return FetchResult(
                complete=False,
                diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)],
            )
