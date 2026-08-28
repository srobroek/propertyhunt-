from __future__ import annotations

from property_hunt.models import Listing, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported
from .portal_common import extract_links, extract_sitemap_locs, parse_jsonld_listing


SITEMAP_INDEX = "https://www.bayut.com/sitemap_index.xml"


class BayutAdapter(SourceAdapter[Listing]):
    name = "bayut"

    @staticmethod
    def _page_url(start_url: str, page: int) -> str:
        if page <= 1:
            return start_url
        return start_url.rstrip("/") + f"/page-{page}/"

    async def _detail_sitemap_fallback(
        self,
        allow_browser: bool,
        target_records: int = 30,
        max_detail_attempts: int = 120,
    ) -> tuple[list[Listing], dict]:
        records: dict[str, Listing] = {}
        details = {
            "sitemap_files": 0,
            "sitemap_urls": 0,
            "detail_attempts": 0,
            "detail_challenges": 0,
            "non_dubai_rejected": 0,
        }
        try:
            index = await self.request(SITEMAP_INDEX)
            maps = [
                url
                for url in extract_sitemap_locs(index)
                if "/dpv-sale-sitemap" in url
            ]
            for sitemap_url in maps:
                urls = extract_sitemap_locs(await self.request(sitemap_url))
                detail_urls = [url for url in urls if "/property/details-" in url]
                details["sitemap_files"] += 1
                details["sitemap_urls"] += len(detail_urls)
                for detail_url in detail_urls:
                    if len(records) >= target_records:
                        break
                    if details["detail_attempts"] >= max_detail_attempts:
                        break
                    if details["detail_challenges"] >= 3:
                        break
                    details["detail_attempts"] += 1
                    try:
                        payload = await self.request(detail_url)
                        if self.challenge_detected(payload):
                            if allow_browser:
                                payload = await self.browser_request(detail_url)
                            if self.challenge_detected(payload):
                                details["detail_challenges"] += 1
                                continue

                        # DPV sitemaps are UAE-wide. Keep this fallback Dubai-only.
                        # The check is deliberately conservative: only retain pages
                        # whose rendered/server payload explicitly mentions Dubai.
                        if b"dubai" not in payload.lower():
                            details["non_dubai_rejected"] += 1
                            continue

                        parsed = parse_jsonld_listing(payload, self.name, detail_url)
                        if not parsed and allow_browser:
                            payload = await self.browser_request(detail_url)
                            if self.challenge_detected(payload):
                                details["detail_challenges"] += 1
                                continue
                            parsed = parse_jsonld_listing(payload, self.name, detail_url)
                        for listing in parsed:
                            if listing.url == detail_url or "/property/details-" in listing.url:
                                records[listing.id] = listing
                    except Exception:
                        continue
                if (
                    len(records) >= target_records
                    or details["detail_attempts"] >= max_detail_attempts
                    or details["detail_challenges"] >= 3
                ):
                    break
        except Exception as exc:
            details["sitemap_error"] = str(exc)
        return list(records.values()), details

    async def fetch(self, **kwargs: object) -> FetchResult[Listing]:
        start_url = kwargs.get("url")
        allow_browser = bool(kwargs.get("allow_browser", False))
        max_pages = max(1, int(kwargs.get("max_pages", 5)))
        if not start_url:
            return unsupported(self.name, "No public Bayut search URL configured")

        records: dict[str, Listing] = {}
        diagnostics: list[SourceDiagnostic] = []
        challenged = False
        for page_number in range(1, max_pages + 1):
            page_url = self._page_url(str(start_url), page_number)
            try:
                payload = await self.request(page_url)
                if self.challenge_detected(payload) and allow_browser:
                    payload = await self.browser_request(page_url)
                if self.challenge_detected(payload):
                    challenged = True
                    break

                for listing in parse_jsonld_listing(payload, self.name, page_url):
                    if "/property/details-" in listing.url:
                        records[listing.id] = listing

                detail_links = extract_links(payload, page_url, (r"/property/details-[^/?#]+",))
                for detail_url in detail_links:
                    try:
                        detail = await self.request(detail_url)
                        parsed = parse_jsonld_listing(detail, self.name, detail_url)
                        if not parsed and allow_browser:
                            detail = await self.browser_request(detail_url)
                            parsed = parse_jsonld_listing(detail, self.name, detail_url)
                        for listing in parsed:
                            if listing.url == detail_url or "/property/details-" in listing.url:
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
                    )
                )
                break

        sitemap_details = {}
        if not records and challenged:
            fallback_records, sitemap_details = await self._detail_sitemap_fallback(allow_browser)
            records.update((listing.id, listing) for listing in fallback_records)

        if not diagnostics:
            if records:
                message = (
                    "published detail sitemap fallback parsed"
                    if challenged
                    else "public search/detail pages parsed"
                )
                diagnostics.append(
                    SourceDiagnostic(
                        source=self.name,
                        status="ok",
                        message=message,
                        records=len(records),
                        pages=0 if challenged else max_pages,
                        partial=False,
                        details=sitemap_details,
                    )
                )
            else:
                diagnostics.append(
                    SourceDiagnostic(
                        source=self.name,
                        status="partial",
                        message=(
                            "search challenged; published detail sitemap fallback yielded no records"
                            if challenged
                            else "public search/detail pages parsed"
                        ),
                        records=0,
                        pages=0 if challenged else max_pages,
                        partial=True,
                        details=sitemap_details,
                    )
                )
        return FetchResult(
            records=list(records.values()),
            diagnostics=diagnostics,
            complete=bool(records) and not any(d.partial for d in diagnostics),
        )
