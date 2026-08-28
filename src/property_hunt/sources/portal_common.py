from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable
from urllib.parse import urljoin

from property_hunt.models import Listing, Provenance


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
            item_type = item.get("@type")
            if item_type not in {
                "Product",
                "Apartment",
                "Residence",
                "RealEstateListing",
                "House",
                "Accommodation",
                "SingleFamilyResidence",
            }:
                continue

            offer = item.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            floor = item.get("floorSize") or {}
            address = item.get("address") or {}
            if isinstance(address, str):
                address = {"streetAddress": address}
            additional = item.get("additionalProperty") or []
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
