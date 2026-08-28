from __future__ import annotations

import hashlib

from property_hunt.models import Conflict, Listing


def group_duplicates(records: list[Listing], area_tolerance_sqft: float = 25.0) -> list[Listing]:
    """Conservatively group probable duplicate adverts.

    The previous bucket-rounding approach created boundary artifacts: e.g. 760 sqft
    and 770 sqft landed in adjacent 25-sqft buckets despite being only 10 sqft apart.
    Use connected components instead, requiring same canonical building and bedroom
    count plus area within the configured tolerance.
    """

    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, left in enumerate(records):
        if left.canonical_building_id is None:
            continue
        for j in range(i + 1, len(records)):
            right = records[j]
            if right.canonical_building_id != left.canonical_building_id:
                continue
            if right.bedrooms != left.bedrooms:
                continue
            if abs(right.area_sqft - left.area_sqft) > area_tolerance_sqft:
                continue
            union(i, j)

    groups: dict[int, list[Listing]] = {}
    for i, record in enumerate(records):
        if record.canonical_building_id is None:
            continue
        groups.setdefault(find(i), []).append(record)

    for group in groups.values():
        if len(group) < 2:
            continue
        signature = (
            group[0].canonical_building_id,
            group[0].bedrooms,
            round(sum(x.area_sqft for x in group) / len(group)),
        )
        gid = "dup-" + hashlib.sha1(repr(signature).encode()).hexdigest()[:12]
        fields = {
            "price_aed": {x.price_aed for x in group},
            "area_sqft": {x.area_sqft for x in group},
            "bedrooms": {x.bedrooms for x in group},
            "bathrooms": {x.bathrooms for x in group},
        }
        for record in group:
            record.duplicate_group_id = gid
            record.duplicate_confidence = 0.85
            record.duplicate_reasons = [
                "same building",
                "same bedrooms",
                f"area within {area_tolerance_sqft:g} sqft tolerance",
            ]
            record.conflicts.extend(
                Conflict(
                    field=field,
                    values=sorted(values, key=lambda value: str(value)),
                    reason="duplicate sources disagree",
                )
                for field, values in fields.items()
                if len(values) > 1
            )
    return records
