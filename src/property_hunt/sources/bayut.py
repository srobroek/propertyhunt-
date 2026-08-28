from __future__ import annotations

from property_hunt.models import Listing, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported
from .portal_common import extract_links, parse_jsonld_listing


class BayutAdapter(SourceAdapter[Listing]):
    name = "bayut"

    @staticmethod
    def _page_url(start_url: str, page: int) -> str:
        if page <= 1:
            return start_url
        return start_url.rstrip("/") + f"/page-{page}/"

    async def fetch(self, **kwargs: object) -> FetchResult[Listing]:
        start_url = kwargs.get("url")
        allow_browser = bool(kwargs.get("allow_browser", False))
        max_pages = max(1, int(kwargs.get("max_pages", 5)))
        if not start_url:
            return unsupported(self.name, "No public Bayut search URL configured")

        records: dict[str, Listing] = {}
        diagnostics: list[SourceDiagnostic] = []
        for page_number in range(1, max_pages + 1):
            page_url = self._page_url(str(start_url), page_number)
            try:
                payload = await self.request(page_url)
                if self.challenge_detected(payload) and allow_browser:
                    payload = await self.browser_request(page_url)
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

                for listing in parse_jsonld_listing(payload, self.name, page_url):
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

        if not diagnostics:
            diagnostics.append(
                SourceDiagnostic(
                    source=self.name,
                    status="ok" if records else "partial",
                    message="public search/detail pages parsed",
                    records=len(records),
                    pages=max_pages,
                    partial=not bool(records),
                )
            )
        return FetchResult(
            records=list(records.values()),
            diagnostics=diagnostics,
            complete=bool(records) and not any(d.partial for d in diagnostics),
        )
