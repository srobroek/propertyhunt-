from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable
from urllib.parse import urljoin

from property_hunt.models import Listing, Provenance


LISTING_TYPES = {
    "Product",
    "Apartment",
    "Residence",
    "RealEstateListing",
    "House",
    "Accommodation",
    "SingleFamilyResidence",
}


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_links(payload: bytes, base_url: str, patterns: tuple[str, ...]) -> list[str]:
    text = payload.decode("utf-8", errors="ignore")
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', text, re.I)
    links: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        url = urljoin(base_url, href.replace("&amp;", "&"))
        if not any(re.search(pattern, url, re.I) for pattern in patterns):
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def _is_listing_type(value: Any) -> bool:
    if isinstance(value, str):
        return value in LISTING_TYPES
    if isinstance(value, list):
        return any(isinstance(item, str) and item in LISTING_TYPES for item in value)
    return False


def parse_jsonld_listing(payload: bytes, source: str, url: str) -> list[Listing]:
    text = payload.decode("utf-8", errors="ignore")
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        text,
        re.I | re.S,
    )
    out: list[Listing] = []
    seen: set[str] = set()

    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue

        for item in _walk(data):
            if not _is_listing_type(item.get("@type")):
                continue

            offer = item.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            if not isinstance(offer, dict):
                offer = {}

            floor = item.get("floorSize") or {}
            if not isinstance(floor, dict):
                floor = {"value": floor}
            address = item.get("address") or {}
            if isinstance(address, str):
                address = {"streetAddress": address}
            if not isinstance(address, dict):
                address = {}

            additional = item.get("additionalProperty") or []
            if not isinstance(additional, list):
                additional = [additional]
            props = {
                str(p.get("name", "")).strip().lower(): p.get("value")
                for p in additional
                if isinstance(p, dict)
            }

            item_url = str(item.get("url") or url)
            sid_value = item.get("sku") or item.get("identifier")
            if isinstance(sid_value, dict):
                sid_value = sid_value.get("value")
            sid = str(sid_value or hashlib.sha256(item_url.encode()).hexdigest()[:16])
            key = f"{source}:{sid}"
            if key in seen:
                continue

            price = _number(offer.get("price") or item.get("price") or props.get("price"))
            area = _number(
                floor.get("value")
                or props.get("area")
                or props.get("size")
                or props.get("property size")
            )
            bedrooms = _number(
                props.get("bedrooms")
                or props.get("bedroom")
                or item.get("numberOfBedrooms")
            )
            bathrooms = _number(
                props.get("bathrooms")
                or props.get("bathroom")
                or item.get("numberOfBathroomsTotal")
            )
            if price is None or area is None:
                continue

            building = str(
                props.get("building")
                or props.get("building name")
                or address.get("streetAddress")
                or item.get("name")
                or "Unknown"
            )
            community = address.get("addressLocality") or address.get("addressRegion")
            seen.add(key)
            out.append(
                Listing(
                    id=key,
                    source=source,
                    source_id=sid,
                    title=str(item.get("name") or ""),
                    url=item_url,
                    price_aed=price,
                    area_sqft=area,
                    bedrooms=int(bedrooms or 0),
                    bathrooms=bathrooms,
                    building_name=building,
                    community=str(community) if community else None,
                    provenance=Provenance(
                        source=source,
                        source_id=sid,
                        url=item_url if item_url.startswith("http") else None,
                        method="json-ld",
                    ),
                )
            )
    return out
