from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from property_hunt.models import Listing, Provenance, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported
from .portal_common import extract_links, parse_jsonld_listing


DETAIL_PATTERN = r"/property-for-sale/residential/apartment/\d{4}/\d{1,2}/\d{1,2}/[^?#]+"


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
    def parse_detail_html(payload: bytes, url: str) -> list[Listing]:
        raw = payload.decode("utf-8", errors="ignore")
        raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
        raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)

        h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", raw, flags=re.I | re.S)
        title = ""
        if h1:
            title = html.unescape(re.sub(r"<[^>]+>", " ", h1.group(1)))
            title = " ".join(title.split())

        text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        text = " ".join(text.replace("\xa0", " ").split())
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
                location = text[area_match.end():title_pos]
                location = re.sub(
                    r"^(?:Image:\s*)?(?:location_outlined|location|pin|map)\s*",
                    "",
                    location,
                    flags=re.I,
                )
                location = " ".join(location.split()).strip(" ,-|")
        if not location:
            loc_match = (
                re.search(
                    r"(?:Location|Map View)\s+(.+?)(?:\s+#?\s*" + re.escape(title) + r"|\s+Type\s)",
                    text,
                    flags=re.I,
                )
                if title
                else None
            )
            if loc_match:
                location = " ".join(loc_match.group(1).split()).strip(" ,-|")

        parts = [part.strip() for part in location.split(",") if part.strip()]
        building = parts[0] if parts else (title or "Unknown")
        community = ", ".join(parts[1:-1]) if len(parts) >= 3 else (parts[1] if len(parts) == 2 else None)

        id_match = re.search(r"-(\d+)/(?:\?.*)?$", url)
        sid = id_match.group(1) if id_match else hashlib.sha256(url.encode()).hexdigest()[:16]
        return [
            Listing(
                id=f"dubizzle:{sid}",
                source="dubizzle",
                source_id=sid,
                title=title,
                url=url,
                price_aed=price,
                area_sqft=area,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                building_name=building,
                community=community,
                provenance=Provenance(
                    source="dubizzle",
                    source_id=sid,
                    url=url,
                    method="server-rendered-html",
                ),
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
        detail_links_seen = 0
        detail_pages_parsed = 0
        browser_index_pages = 0

        for page_number in range(1, max_pages + 1):
            page_url = self._page_url(str(start_url), page_number)
            try:
                payload = await self.request(page_url)
                if self.challenge_detected(payload) and allow_browser:
                    payload = await self.browser_request(page_url)
                    browser_index_pages += 1
                if self.challenge_detected(payload):
                    diagnostics.append(
                        SourceDiagnostic(
                            source=self.name,
                            status="partial",
                            message="access challenge detected",
                            pages=page_number - 1,
                            records=len(records),
                            partial=True,
                        )
                    )
                    break

                index_records = parse_jsonld_listing(payload, self.name, page_url)
                detail_links = extract_links(payload, page_url, (DETAIL_PATTERN,))

                # Dubizzle serves a usable shell over HTTP but hydrates the listing
                # cards client-side. Render that ordinary public page when HTTP has
                # neither records nor detail links.
                if not index_records and not detail_links and allow_browser:
                    rendered = await self.browser_request(page_url)
                    browser_index_pages += 1
                    if not self.challenge_detected(rendered):
                        payload = rendered
                        index_records = parse_jsonld_listing(payload, self.name, page_url)
                        detail_links = extract_links(payload, page_url, (DETAIL_PATTERN,))

                for listing in index_records:
                    records[listing.id] = listing

                detail_links_seen += len(detail_links)
                for detail_url in detail_links:
                    try:
                        detail = await self.request(detail_url)
                        parsed = parse_jsonld_listing(detail, self.name, detail_url)
                        if not parsed:
                            parsed = self.parse_detail_html(detail, detail_url)
                        if not parsed and allow_browser:
                            detail = await self.browser_request(detail_url)
                            parsed = parse_jsonld_listing(detail, self.name, detail_url)
                            if not parsed:
                                parsed = self.parse_detail_html(detail, detail_url)
                        if parsed:
                            detail_pages_parsed += 1
                        for listing in parsed:
                            records[listing.id] = listing
                    except Exception:
                        continue
            except Exception as exc:
                diagnostics.append(
                    SourceDiagnostic(
                        source=self.name,
                        status="partial",
                        message=str(exc),
                        pages=page_number - 1,
                        records=len(records),
                        partial=True,
                        details={
                            "detail_links_seen": detail_links_seen,
                            "detail_pages_parsed": detail_pages_parsed,
                            "browser_index_pages": browser_index_pages,
                        },
                    )
                )
                break

        if not diagnostics:
            diagnostics.append(
                SourceDiagnostic(
                    source=self.name,
                    status="ok" if records else "partial",
                    message="public search/detail pages parsed",
                    records=len(records),
                    pages=max_pages,
                    partial=not bool(records),
                    details={
                        "detail_links_seen": detail_links_seen,
                        "detail_pages_parsed": detail_pages_parsed,
                        "browser_index_pages": browser_index_pages,
                    },
                )
            )
        return FetchResult(
            records=list(records.values()),
            diagnostics=diagnostics,
            complete=bool(records) and not any(d.partial for d in diagnostics),
        )
