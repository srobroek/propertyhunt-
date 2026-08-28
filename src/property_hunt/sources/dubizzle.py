from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from property_hunt.models import Listing, Provenance, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported
from .portal_common import extract_links, parse_jsonld_listing


DETAIL_PATTERN = r"/property-for-sale/residential/apartment/\d{4}/\d{1,2}/\d{1,2}/[^?#]+"
CARD_PATTERN = re.compile(
    r"AED\s*([0-9][0-9,]*)\s+Apartment\s+"
    r"(?:(Studio)|(\d+)\s*(?:Bed|beds?))\s+"
    r"(\d+)\s*(?:Bath|baths?)\s+"
    r"([0-9][0-9,]*)\s*sqft\s+(.+?)"
    r"(?=(?:\d+\s*/\s*\d+\s+(?:Verified\s+)?(?:Off-Plan\s+)?(?:Initial Sale\s+|Resale\s+)?AED)|$)",
    re.I | re.S,
)


def _plain_text(payload: bytes) -> str:
    raw = payload.decode("utf-8", errors="ignore")
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return " ".join(text.replace("\xa0", " ").split())


class DubizzleAdapter(SourceAdapter[Listing]):
    name = "dubizzle"

    @staticmethod
    def _page_url(start_url: str, page: int) -> str:
        if page <= 1:
            return start_url
        parts = urlsplit(start_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["page"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    @staticmethod
    def parse_search_cards(payload: bytes, page_url: str) -> list[Listing]:
        text = _plain_text(payload)
        out: list[Listing] = []
        for index, match in enumerate(CARD_PATTERN.finditer(text)):
            price = float(match.group(1).replace(",", ""))
            bedrooms = 0 if match.group(2) else int(match.group(3) or 0)
            bathrooms = float(match.group(4))
            area = float(match.group(5).replace(",", ""))
            tail = " ".join(match.group(6).split())
            tail = re.split(r"\s+(?:Email\s+)?Call(?:\s+WhatsApp)?\b", tail, maxsplit=1, flags=re.I)[0]
            tail = re.sub(r"\s+(?:PREMIUM|Verified)\s*$", "", tail, flags=re.I).strip()

            location = ""
            location_match = re.search(
                r"([A-Za-z0-9][A-Za-z0-9 .&'()/-]*(?:,\s*[A-Za-z0-9][A-Za-z0-9 .&'()/-]*){1,4},\s*Dubai)\s*$",
                tail,
                flags=re.I,
            )
            if location_match:
                location = location_match.group(1)
                title = tail[: location_match.start()].strip(" |- ,")
            else:
                title = tail[:180].strip(" |- ,")

            parts = [p.strip() for p in location.split(",") if p.strip()]
            building = parts[0] if parts else (title or "Unknown")
            community = ", ".join(parts[1:-1]) if len(parts) >= 3 else (parts[1] if len(parts) == 2 else None)
            fingerprint = f"{page_url}|{index}|{price}|{area}|{bedrooms}|{building}|{title}"
            sid = hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
            out.append(
                Listing(
                    id=f"dubizzle:{sid}",
                    source="dubizzle",
                    source_id=sid,
                    title=title,
                    url=page_url,
                    price_aed=price,
                    area_sqft=area,
                    bedrooms=bedrooms,
                    bathrooms=bathrooms,
                    building_name=building,
                    community=community,
                    provenance=Provenance(
                        source="dubizzle",
                        source_id=sid,
                        url=page_url,
                        method="rendered-search-card",
                    ),
                )
            )
        return out

    @staticmethod
    def parse_detail_html(payload: bytes, url: str) -> list[Listing]:
        raw = payload.decode("utf-8", errors="ignore")
        h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", raw, flags=re.I | re.S)
        title = ""
        if h1:
            title = html.unescape(re.sub(r"<[^>]+>", " ", h1.group(1)))
            title = " ".join(title.split())
        text = _plain_text(payload)
        if not text:
            return []

        price_match = re.search(r"\bAED\s*([0-9][0-9,]*)\b", text, flags=re.I)
        area_match = re.search(r"\b([0-9][0-9,]*)\s*(?:sq\.?\s*ft|sqft|ft²)\b", text, flags=re.I)
        beds_match = re.search(r"\b([0-9]+)\s*(?:bed|beds|bedroom|bedrooms)\b", text, flags=re.I)
        baths_match = re.search(r"\b([0-9]+)\s*(?:bath|baths|bathroom|bathrooms)\b", text, flags=re.I)
        studio = bool(re.search(r"\bStudio\b", text, flags=re.I))
        if price_match is None or area_match is None:
            return []

        price = float(price_match.group(1).replace(",", ""))
        area = float(area_match.group(1).replace(",", ""))
        bedrooms = 0 if studio and beds_match is None else int(beds_match.group(1)) if beds_match else 0
        bathrooms = float(baths_match.group(1)) if baths_match else None
        location = ""
        if title:
            title_pos = text.find(title)
            if title_pos > area_match.end():
                location = " ".join(text[area_match.end():title_pos].split()).strip(" ,-|")
        parts = [part.strip() for part in location.split(",") if part.strip()]
        building = parts[0] if parts else (title or "Unknown")
        community = ", ".join(parts[1:-1]) if len(parts) >= 3 else (parts[1] if len(parts) == 2 else None)
        id_match = re.search(r"-(\d+)/(?:\?.*)?$", url)
        sid = id_match.group(1) if id_match else hashlib.sha256(url.encode()).hexdigest()[:16]
        return [
            Listing(
                id=f"dubizzle:{sid}", source="dubizzle", source_id=sid, title=title, url=url,
                price_aed=price, area_sqft=area, bedrooms=bedrooms, bathrooms=bathrooms,
                building_name=building, community=community,
                provenance=Provenance(source="dubizzle", source_id=sid, url=url, method="server-rendered-html"),
            )
        ]

    async def fetch(self, **kwargs: object) -> FetchResult[Listing]:
        start_url = kwargs.get("url")
        allow_browser = bool(kwargs.get("allow_browser", False))
        max_pages = max(1, int(kwargs.get("max_pages", 5)))
        if not start_url:
            return unsupported(self.name, "No public Dubizzle search URL configured")

        records: dict[str, Listing] = {}
        diagnostics: list[SourceDiagnostic] = []
        detail_links_seen = detail_pages_parsed = browser_index_pages = search_cards_parsed = 0
        rendered_aed_markers = rendered_sqft_markers = 0

        for page_number in range(1, max_pages + 1):
            page_url = self._page_url(str(start_url), page_number)
            try:
                payload = await self.request(page_url)
                if self.challenge_detected(payload) and allow_browser:
                    payload = await self.browser_request(page_url)
                    browser_index_pages += 1
                if self.challenge_detected(payload):
                    diagnostics.append(SourceDiagnostic(source=self.name, status="partial", message="access challenge detected", pages=page_number - 1, records=len(records), partial=True))
                    break

                index_records = parse_jsonld_listing(payload, self.name, page_url)
                detail_links = extract_links(payload, page_url, (DETAIL_PATTERN,))
                search_cards = self.parse_search_cards(payload, page_url)
                if not index_records and not detail_links and not search_cards and allow_browser:
                    rendered = await self.browser_request(page_url)
                    browser_index_pages += 1
                    rendered_text = _plain_text(rendered)
                    rendered_aed_markers += len(re.findall(r"\bAED\b", rendered_text, re.I))
                    rendered_sqft_markers += len(re.findall(r"\bsqft\b", rendered_text, re.I))
                    if not self.challenge_detected(rendered):
                        payload = rendered
                        index_records = parse_jsonld_listing(payload, self.name, page_url)
                        detail_links = extract_links(payload, page_url, (DETAIL_PATTERN,))
                        search_cards = self.parse_search_cards(payload, page_url)

                for listing in [*index_records, *search_cards]:
                    records[listing.id] = listing
                search_cards_parsed += len(search_cards)
                detail_links_seen += len(detail_links)

                for detail_url in detail_links:
                    try:
                        detail = await self.request(detail_url)
                        parsed = parse_jsonld_listing(detail, self.name, detail_url) or self.parse_detail_html(detail, detail_url)
                        if not parsed and allow_browser:
                            detail = await self.browser_request(detail_url)
                            parsed = parse_jsonld_listing(detail, self.name, detail_url) or self.parse_detail_html(detail, detail_url)
                        if parsed:
                            detail_pages_parsed += 1
                        for listing in parsed:
                            records[listing.id] = listing
                    except Exception:
                        continue
            except Exception as exc:
                diagnostics.append(SourceDiagnostic(source=self.name, status="partial", message=str(exc), pages=page_number - 1, records=len(records), partial=True, details={"detail_links_seen": detail_links_seen, "detail_pages_parsed": detail_pages_parsed, "browser_index_pages": browser_index_pages, "search_cards_parsed": search_cards_parsed, "rendered_aed_markers": rendered_aed_markers, "rendered_sqft_markers": rendered_sqft_markers}))
                break

        if not diagnostics:
            diagnostics.append(SourceDiagnostic(source=self.name, status="ok" if records else "partial", message="public search/detail pages parsed", records=len(records), pages=max_pages, partial=not bool(records), details={"detail_links_seen": detail_links_seen, "detail_pages_parsed": detail_pages_parsed, "browser_index_pages": browser_index_pages, "search_cards_parsed": search_cards_parsed, "rendered_aed_markers": rendered_aed_markers, "rendered_sqft_markers": rendered_sqft_markers}))
        return FetchResult(records=list(records.values()), diagnostics=diagnostics, complete=bool(records) and not any(d.partial for d in diagnostics))
