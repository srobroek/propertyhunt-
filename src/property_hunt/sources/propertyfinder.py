from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from property_hunt.models import Listing, Provenance, SourceDiagnostic
from .base import FetchResult, SourceAdapter, unsupported
from .portal_common import extract_links, extract_sitemap_locs, parse_jsonld_listing


SITEMAP_INDEX = "https://www.propertyfinder.ae/sitemaps/index-sitemap.xml"


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    match = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def _embedded_json_blocks(payload: bytes) -> Iterable[Any]:
    text = payload.decode("utf-8", errors="ignore")
    for block in re.findall(r"<script\b[^>]*>(.*?)</script>", text, re.I | re.S):
        candidate = block.strip()
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            yield json.loads(candidate)
        except json.JSONDecodeError:
            continue


def parse_embedded_listings(payload: bytes, page_url: str) -> list[Listing]:
    """Parse Property Finder listing objects embedded in application state.

    Current PF search pages serialize listing objects with stable semantic fields
    such as id/share_url/price/location/size. This path is intentionally independent
    of CSS selectors and complements JSON-LD detail parsing.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    for data in _embedded_json_blocks(payload):
        for item in _walk(data):
            share_url = item.get("share_url") or item.get("shareUrl") or item.get("url")
            if not isinstance(share_url, str):
                continue
            if "propertyfinder.ae" not in share_url or "/plp/buy/" not in share_url:
                continue

            property_type = str(item.get("property_type") or item.get("propertyType") or "").lower()
            if property_type and "apartment" not in property_type:
                continue

            sid_raw = item.get("id") or item.get("listing_id") or item.get("listingId")
            if sid_raw is None:
                match = re.search(r"-(\d+)\.html(?:\?|$)", share_url)
                sid_raw = match.group(1) if match else None
            if sid_raw is None:
                continue
            sid = str(sid_raw)
            key = f"propertyfinder:{sid}"
            if key in seen:
                continue

            price = _number(item.get("price"))
            size = _number(item.get("size") or item.get("area"))
            bedrooms_raw = item.get("bedrooms")
            bathrooms_raw = item.get("bathrooms")
            bedrooms = 0 if str(bedrooms_raw).lower() == "studio" else _number(bedrooms_raw)
            bathrooms = _number(bathrooms_raw)
            if price is None or size is None or bedrooms is None:
                continue

            location = item.get("location") or {}
            if isinstance(location, dict):
                full_name = str(
                    location.get("full_name")
                    or location.get("fullName")
                    or location.get("name")
                    or ""
                )
            else:
                full_name = str(location)
            parts = [part.strip() for part in full_name.split(",") if part.strip()]
            building = parts[0] if parts else str(item.get("title") or "Unknown")
            community_parts = [p for p in parts[1:] if p.lower() != "dubai"]
            community = ", ".join(community_parts) or None

            seen.add(key)
            out.append(
                Listing(
                    id=key,
                    source="propertyfinder",
                    source_id=sid,
                    title=str(item.get("title") or ""),
                    url=share_url,
                    price_aed=price,
                    area_sqft=size,
                    bedrooms=int(bedrooms),
                    bathrooms=bathrooms,
                    building_name=building,
                    community=community,
                    property_type="apartment",
                    provenance=Provenance(
                        source="propertyfinder",
                        source_id=sid,
                        url=share_url,
                        method="embedded-application-state",
                    ),
                )
            )
    return out


class PropertyFinderAdapter(SourceAdapter[Listing]):
    name = "propertyfinder"

    @staticmethod
    def parse(payload: bytes, url: str = "fixture://propertyfinder") -> list[Listing]:
        records = parse_jsonld_listing(payload, "propertyfinder", url)
        by_id = {record.id: record for record in records}
        for record in parse_embedded_listings(payload, url):
            by_id[record.id] = record
        return list(by_id.values())

    @staticmethod
    def _page_url(start_url: str, page: int) -> str:
        if page <= 1:
            return start_url
        parts = urlsplit(start_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["page"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    async def _sitemap_fallback(
        self, allow_browser: bool, target_records: int = 50
    ) -> tuple[list[Listing], dict]:
        records: dict[str, Listing] = {}
        details = {
            "sitemap_files": 0,
            "sitemap_urls": 0,
            "detail_attempts": 0,
            "detail_challenges": 0,
        }
        try:
            index = await self.request(SITEMAP_INDEX)
            child_maps = extract_sitemap_locs(index)
            # Be permissive about PF sitemap naming: names have changed over time.
            likely_buy_maps = [u for u in child_maps if "buy" in u.lower()] or child_maps
            for child in likely_buy_maps[:8]:
                urls = extract_sitemap_locs(await self.request(child))
                listing_urls = [u for u in urls if "/plp/buy/" in u]
                details["sitemap_files"] += 1
                details["sitemap_urls"] += len(listing_urls)
                for detail_url in listing_urls[:150]:
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
                            if listing.property_type.lower() != "apartment" and "apartment" not in listing.title.lower():
                                continue
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
                for detail_url in extract_links(
                    payload, page_url, (r"/en/plp/(?:buy|rent)/[^?#]+",)
                ):
                    try:
                        detail = await self.request(detail_url)
                        parsed = self.parse(detail, detail_url)
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

        sitemap_details = {}
        if not records and challenged:
            sitemap_records, sitemap_details = await self._sitemap_fallback(allow_browser)
            records.update((x.id, x) for x in sitemap_records)

        if not diagnostics:
            status = "ok" if records else "partial"
            message = (
                "public search/detail pages parsed"
                if records and not challenged
                else "search challenged; published sitemap fallback used"
            )
            diagnostics.append(
                SourceDiagnostic(
                    source=self.name,
                    status=status,
                    message=message,
                    records=len(records),
                    pages=max_pages if not challenged else 0,
                    partial=not bool(records),
                    details=sitemap_details,
                )
            )
        return FetchResult(
            records=list(records.values()),
            diagnostics=diagnostics,
            complete=bool(records) and not any(d.partial for d in diagnostics),
        )
