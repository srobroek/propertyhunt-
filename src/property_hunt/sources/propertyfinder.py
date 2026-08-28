from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from property_hunt.models import Listing, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported
from .portal_common import extract_links, extract_sitemap_locs, parse_jsonld_listing


SITEMAP_INDEX = "https://www.propertyfinder.ae/sitemaps/index-sitemap.xml"


class PropertyFinderAdapter(SourceAdapter[Listing]):
    name = "propertyfinder"

    @staticmethod
    def parse(payload: bytes, url: str = "fixture://propertyfinder") -> list[Listing]:
        return parse_jsonld_listing(payload, "propertyfinder", url)

    @staticmethod
    def _page_url(start_url: str, page: int) -> str:
        if page <= 1:
            return start_url
        parts = urlsplit(start_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["page"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    async def _sitemap_fallback(self, allow_browser: bool, target_records: int = 50) -> tuple[list[Listing], dict]:
        records: dict[str, Listing] = {}
        details = {"sitemap_files": 0, "sitemap_urls": 0, "detail_attempts": 0, "detail_challenges": 0}
        try:
            index = await self.request(SITEMAP_INDEX)
            child_maps = [u for u in extract_sitemap_locs(index) if "/buy-" in u][:2]
            for child in child_maps:
                urls = extract_sitemap_locs(await self.request(child))
                listing_urls = [u for u in urls if "/plp/buy/" in u and "apartment" in u.lower()]
                details["sitemap_files"] += 1
                details["sitemap_urls"] += len(listing_urls)
                for detail_url in listing_urls[:100]:
                    if len(records) >= target_records or details["detail_challenges"] >= 3:
                        break
                    details["detail_attempts"] += 1
                    try:
                        payload = await self.request(detail_url)
                        if self.challenge_detected(payload):
                            details["detail_challenges"] += 1
                            continue
                        parsed = self.parse(payload, detail_url)
                        if not parsed and allow_browser:
                            payload = await self.browser_request(detail_url)
                            if self.challenge_detected(payload):
                                details["detail_challenges"] += 1
                                continue
                            parsed = self.parse(payload, detail_url)
                        for listing in parsed:
                            records[listing.id] = listing
                    except Exception:
                        continue
                if len(records) >= target_records or details["detail_challenges"] >= 3:
                    break
        except Exception as exc:
            details["sitemap_error"] = str(exc)
        return list(records.values()), details

    async def fetch(self, **kwargs: object) -> FetchResult[Listing]:
        start_url = kwargs.get("url")
        allow_browser = bool(kwargs.get("allow_browser", False))
        max_pages = max(1, int(kwargs.get("max_pages", 5)))
        if not start_url:
            return unsupported(self.name, "No public Property Finder search URL configured")

        records: dict[str, Listing] = {}
        diagnostics: list[SourceDiagnostic] = []
        challenged = False
        for page_number in range(1, max_pages + 1):
            page_url = self._page_url(str(start_url), page_number)
            try:
                payload = await self.request(page_url)
                parsed_index = self.parse(payload, page_url)
                if (not parsed_index or self.challenge_detected(payload)) and allow_browser:
                    payload = await self.browser_request(page_url)
                    parsed_index = self.parse(payload, page_url)
                if self.challenge_detected(payload):
                    challenged = True
                    break
                for listing in parsed_index:
                    records[listing.id] = listing
                for detail_url in extract_links(payload, page_url, (r"/en/plp/(?:buy|rent)/[^?#]+",)):
                    try:
                        detail = await self.request(detail_url)
                        parsed = self.parse(detail, detail_url)
                        for listing in parsed:
                            records[listing.id] = listing
                    except Exception:
                        continue
            except Exception as exc:
                diagnostics.append(SourceDiagnostic(source=self.name, status="partial", message=str(exc), pages=page_number - 1, records=len(records), partial=True))
                break

        sitemap_details = {}
        if not records and challenged:
            sitemap_records, sitemap_details = await self._sitemap_fallback(allow_browser)
            records.update((x.id, x) for x in sitemap_records)

        if not diagnostics:
            status = "ok" if records else "partial"
            message = "public search/detail pages parsed" if records and not challenged else "search challenged; published sitemap fallback used"
            diagnostics.append(SourceDiagnostic(source=self.name, status=status, message=message, records=len(records), pages=max_pages if not challenged else 0, partial=not bool(records), details=sitemap_details))
        return FetchResult(records=list(records.values()), diagnostics=diagnostics, complete=bool(records) and not any(d.partial for d in diagnostics))
