from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from property_hunt.comps import select_comparables
from property_hunt.config import HuntConfig, load_config
from property_hunt.matching import group_duplicates, group_layouts
from property_hunt.models import Listing, Observation, Transaction
from property_hunt.normalize import BuildingCanonicalizer
from property_hunt.reporting import generate_report
from property_hunt.scoring import score_listing
from property_hunt.sources.bayut import BayutAdapter
from property_hunt.sources.dld import DLDAdapter
from property_hunt.sources.dubizzle import DubizzleAdapter
from property_hunt.sources.propertyfinder import PropertyFinderAdapter
from property_hunt.storage import append_events, detect_events, read_models, write_models
from property_hunt.underwriting import underwrite


async def collect(
    cfg: HuntConfig,
    sources: list[str] | None = None,
    fixture_dir: str | Path | None = None,
    allow_browser: bool = False,
):
    configured = {
        name: settings
        for name, settings in cfg.sources.items()
        if settings.get("enabled", True)
    }
    wanted = sources or list(configured)
    listings: list[Listing] = []
    txns: list[Transaction] = []
    diags = []

    if fixture_dir:
        fd = Path(fixture_dir)
        listings = PropertyFinderAdapter.parse((fd / "propertyfinder.html").read_bytes())
        txns = DLDAdapter.parse((fd / "dld.csv").read_bytes())
        return listings, txns, diags

    adapters = {
        "propertyfinder": PropertyFinderAdapter,
        "bayut": BayutAdapter,
        "dubizzle": DubizzleAdapter,
        "dld": DLDAdapter,
    }

    for name in wanted:
        settings = cfg.sources.get(name)
        if settings is None:
            raise ValueError(f"unknown source: {name}")
        if not settings.get("enabled", True):
            continue
        cls = adapters.get(name)
        if cls is None:
            raise ValueError(
                f"enabled source {name!r} has no registered adapter; disable it or register one explicitly"
            )

        adapter = cls(cfg.http)
        try:
            result = await adapter.fetch(
                url=settings.get("url") or settings.get("start_url"),
                allow_browser=allow_browser,
                max_pages=int(settings.get("max_pages", 5)),
            )
        finally:
            await adapter.close()

        diags.extend(result.diagnostics)
        if name == "dld":
            txns.extend(result.records)
        else:
            listings.extend(result.records)

    return listings, txns, diags


def normalize_records(listings: list[Listing], txns: list[Transaction], cfg: HuntConfig):
    canonicalizer = BuildingCanonicalizer(
        threshold=cfg.canonicalization.fuzzy_threshold,
        ambiguity_margin=cfg.canonicalization.ambiguity_margin,
    )
    ambiguous = []
    for record in [*listings, *txns]:
        match = canonicalizer.match(record.building_name, record.community)
        record.canonical_building_id = match.canonical_id
        if isinstance(record, Listing):
            record.canonicalization_confidence = match.confidence
            record.canonicalization_reasons = match.reasons
        if match.ambiguous:
            ambiguous.append(record)
    group_layouts(listings, cfg.layouts.absolute_area_sqft, cfg.layouts.percentage_area)
    group_duplicates(listings)
    return ambiguous


def _merge_first_seen(previous: list[Listing], current: list[Listing]) -> list[Listing]:
    merged = {x.id: x for x in previous}
    for listing in current:
        merged.setdefault(listing.id, listing)
    return sorted(merged.values(), key=lambda x: x.id)


def _observations(listings: list[Listing]) -> list[Observation]:
    out: list[Observation] = []
    for listing in listings:
        provenance = listing.provenance
        if provenance is None:
            continue
        out.append(
            Observation(
                listing_id=listing.id,
                observed_at=listing.observed_at,
                price_aed=listing.price_aed,
                area_sqft=listing.area_sqft,
                status=listing.status,
                provenance=provenance,
            )
        )
    return out


def _historical_listing_valid(listing: Listing, cfg: HuntConfig) -> bool:
    """Reject known category/search-page records accidentally persisted as listings.

    Search-page observations are valid when deliberately parsed from rendered cards,
    but a generic JSON-LD object whose URL is exactly the configured source landing
    page is not a property listing.
    """
    settings = cfg.sources.get(listing.source) or {}
    start_url = settings.get("start_url") or settings.get("url")
    provenance = listing.provenance
    if not start_url or provenance is None:
        return True
    if provenance.method != "json-ld":
        return True
    return listing.url.rstrip("/") != str(start_url).rstrip("/")


def _listing_snapshot_partial(listings: list[Listing], diags: list[Any]) -> bool:
    if listings:
        return False
    listing_diags = [d for d in diags if d.source != "dld"]
    return bool(listing_diags) and any(d.partial for d in listing_diags)


def _transaction_snapshot_partial(txns: list[Transaction], diags: list[Any], cfg: HuntConfig) -> bool:
    if txns:
        return False
    dld_enabled = bool((cfg.sources.get("dld") or {}).get("enabled", False))
    if not dld_enabled:
        return True
    dld_diags = [d for d in diags if d.source == "dld"]
    return bool(dld_diags) and any(d.partial for d in dld_diags)


async def run_pipeline(
    config_path="config/hunt.yaml",
    sources=None,
    max_price=None,
    output_dir=".",
    fixture_dir=None,
    allow_browser=False,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    listings, txns, diags = await collect(cfg, sources, fixture_dir, allow_browser)
    ambiguous = normalize_records(listings, txns, cfg)

    base = Path(output_dir)
    state = base / "data/state"
    reports = base / "reports"

    raw_previous = read_models(state / "listings.parquet", Listing)
    raw_first_seen = read_models(state / "first_seen.parquet", Listing)
    previous_transactions = read_models(state / "transactions.parquet", Transaction)
    previous_observations = read_models(state / "observations.parquet", Observation)

    previous = [x for x in raw_previous if _historical_listing_valid(x, cfg)]
    previous_first_seen = [x for x in raw_first_seen if _historical_listing_valid(x, cfg)]
    invalid_historical_ids = {x.id for x in raw_previous if x not in previous}
    invalid_historical_ids.update(x.id for x in raw_first_seen if x not in previous_first_seen)
    previous_observations = [
        x for x in previous_observations if x.listing_id not in invalid_historical_ids
    ]

    preserve_listing_snapshot = _listing_snapshot_partial(listings, diags)
    preserve_transaction_snapshot = _transaction_snapshot_partial(txns, diags, cfg)

    effective_listings = previous if preserve_listing_snapshot else listings
    effective_txns = previous_transactions if preserve_transaction_snapshot else txns
    events = [] if preserve_listing_snapshot else detect_events(previous, listings)

    write_models(state / "listings.parquet", effective_listings, Listing)
    write_models(state / "transactions.parquet", effective_txns, Transaction)
    write_models(
        state / "observations.parquet",
        previous_observations + _observations(listings),
        Observation,
    )
    write_models(
        state / "first_seen.parquet",
        _merge_first_seen(previous_first_seen, listings),
        Listing,
    )
    append_events(state / "events.parquet", events)

    ceiling = min(cfg.all_in_ceiling_aed, max_price or cfg.all_in_ceiling_aed)
    candidates = []
    exclusions = {"bedrooms": 0, "all_in_ceiling": 0, "ambiguous_building": 0}
    for listing in listings:
        # Placeholder rent assumption remains explicitly labelled until registered/live
        # rental evidence is integrated into the source layer.
        uw = underwrite(listing, cfg, annual_rent=listing.price_aed * 0.06)
        all_in = uw.metrics["all_in_cost"] or 0
        if listing.bedrooms not in cfg.allowed_bedrooms:
            exclusions["bedrooms"] += 1
            continue
        if all_in > ceiling:
            exclusions["all_in_ceiling"] += 1
            continue
        if not listing.canonical_building_id:
            exclusions["ambiguous_building"] += 1
            continue

        evidence, stats = select_comparables(listing, effective_txns)
        score = score_listing(listing, stats["weighted_psf"], uw, cfg.scoring_weights)
        candidates.append(
            {
                "id": listing.id,
                "url": listing.url,
                "source": listing.source,
                "building": listing.building_name,
                "bedrooms": listing.bedrooms,
                "bathrooms": listing.bathrooms,
                "area_sqft": listing.area_sqft,
                "price_aed": listing.price_aed,
                "price_psf": listing.price_aed / listing.area_sqft,
                "score": score.total,
                "score_breakdown": score.model_dump(mode="json"),
                "underwriting": uw.model_dump(mode="json"),
                "comparables": [x.model_dump(mode="json") for x in evidence],
                "comp_statistics": stats,
            }
        )

    candidates.sort(key=lambda x: (-x["score"], x["id"]))
    warnings: list[str] = []
    if preserve_listing_snapshot:
        warnings.append(
            "Listing sources were partial with zero current records; preserved the last valid listing snapshot and suppressed removal events."
        )
    if preserve_transaction_snapshot:
        warnings.append(
            "No fresh transaction source was available; preserved the last valid transaction snapshot."
        )
    if invalid_historical_ids:
        warnings.append(
            f"Removed {len(invalid_historical_ids)} invalid historical category/search-page listing record(s)."
        )

    payload = {
        "run_id": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "collected_listings": len(listings),
            "state_listings": len(effective_listings),
            "transactions": len(txns),
            "state_transactions": len(effective_txns),
            "ambiguous": len(ambiguous),
            "candidates": len(candidates),
            "events": len(events),
        },
        "snapshot": {
            "listing_snapshot_preserved": preserve_listing_snapshot,
            "transaction_snapshot_preserved": preserve_transaction_snapshot,
        },
        "diagnostics": [d.model_dump(mode="json") for d in diags],
        "exclusions": exclusions,
        "candidates": candidates,
        "warnings": warnings,
    }
    generate_report(payload, reports, date.today())
    return payload
