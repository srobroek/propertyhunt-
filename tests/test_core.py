from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from property_hunt.cli import app
from property_hunt.comps import select_comparables
from property_hunt.config import load_config
from property_hunt.matching import group_duplicates, group_layouts
from property_hunt.models import Listing, Observation, Provenance
from property_hunt.normalize import BuildingCanonicalizer, normalize_name
from property_hunt.pipeline import _merge_first_seen, _observations
from property_hunt.sources.dld import DLDAdapter
from property_hunt.sources.propertyfinder import PropertyFinderAdapter
from property_hunt.storage import detect_events, read_models
from property_hunt.underwriting import monthly_mortgage, underwrite


def listing(i="1", price=1_200_000, area=760):
    return Listing(
        id=i,
        source="x",
        source_id=i,
        price_aed=price,
        area_sqft=area,
        bedrooms=1,
        bathrooms=2,
        building_name="Marina Pinnacle",
        community="Dubai Marina",
        canonical_building_id="marina-pinnacle",
        provenance=Provenance(source="x", source_id=i, method="fixture"),
    )


def test_config_and_models():
    c = load_config()
    assert c.rental.str_management_fee == .17
    assert c.all_in_ceiling_aed == 2_200_000


def test_parsers():
    assert len(PropertyFinderAdapter.parse(Path("tests/fixtures/propertyfinder.html").read_bytes())) == 1
    assert len(DLDAdapter.parse(Path("tests/fixtures/dld.csv").read_bytes())) == 2


def test_propertyfinder_embedded_application_state():
    payload = b'''<html><script type="application/json">{
      "props": {"listings": [{
        "id": "13695167",
        "property_type": "Apartment",
        "price": {"value": 1200000, "currency": "AED"},
        "title": "Vacant | Mid Floor | Marina View",
        "location": {"full_name": "Marina Pinnacle, Dubai Marina, Dubai"},
        "bedrooms": "1",
        "bathrooms": "2",
        "size": {"value": 760, "unit": "sqft"},
        "share_url": "https://www.propertyfinder.ae/en/plp/buy/apartment-for-sale-dubai-dubai-marina-marina-pinnacle-13695167.html"
      }]}
    }</script></html>'''
    records = PropertyFinderAdapter.parse(payload, "https://www.propertyfinder.ae/en/buy/dubai/properties-for-sale.html")
    assert len(records) == 1
    record = records[0]
    assert record.source_id == "13695167"
    assert record.price_aed == 1_200_000
    assert record.area_sqft == 760
    assert record.bedrooms == 1
    assert record.building_name == "Marina Pinnacle"
    assert record.community == "Dubai Marina"
    assert record.provenance.method == "embedded-application-state"


def test_normalization_and_ambiguity():
    c = BuildingCanonicalizer()
    assert normalize_name("Tôwer—One!") == "tower one"
    assert c.match("Tiger Tower", "Dubai Marina").canonical_id == "marina-pinnacle"
    assert c.match("Unknown").canonical_id is None


def test_layout_and_duplicates():
    a, b = listing("a"), listing("b", 1_250_000, 770)
    group_layouts([a, b])
    group_duplicates([a, b])
    assert a.layout_group_id == b.layout_group_id
    assert a.duplicate_group_id == b.duplicate_group_id
    assert any(x.field == "price_aed" for x in a.conflicts)


def test_comps_recency_priority():
    l = listing()
    tx = DLDAdapter.parse(Path("tests/fixtures/dld.csv").read_bytes())
    [setattr(x, "canonical_building_id", "marina-pinnacle") for x in tx]
    ev, stats = select_comparables(l, tx, date(2026, 8, 28))
    assert stats["count"] == 2
    assert ev[0].tier == "same_layout"


def test_underwriting_financing():
    c = load_config()
    u = underwrite(listing(), c, 72_000)
    assert monthly_mortgage(100_000, .05, 25) > 500
    assert u.metrics["all_in_cost"] > 1_200_000
    assert u.derivations[1].inputs["management_fee"] == .17


def test_state_transitions():
    assert detect_events([listing(price=1_000_000)], [listing(price=900_000)])[0].event_type == "changed"


def test_first_seen_is_immutable_and_retains_removed_listings():
    old = listing("old", 1_000_000)
    changed = listing("old", 900_000)
    new = listing("new", 800_000)
    merged = _merge_first_seen([old], [changed, new])
    by_id = {x.id: x for x in merged}
    assert set(by_id) == {"old", "new"}
    assert by_id["old"].price_aed == 1_000_000
    assert by_id["new"].price_aed == 800_000
    assert _merge_first_seen([old], [])[0].id == "old"


def test_observations_are_created_from_provenance():
    obs = _observations([listing("a")])
    assert len(obs) == 1
    assert obs[0].listing_id == "a"
    assert obs[0].price_aed == 1_200_000


def test_cli_fixture_persists_observation_history(tmp_path):
    runner = CliRunner()
    args = [
        "run",
        "--fixture-dir",
        "tests/fixtures",
        "--output-dir",
        str(tmp_path),
        "--no-browser",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert (tmp_path / "reports/latest.json").exists()
    assert (tmp_path / "data/state/listings.parquet").exists()
    observations = read_models(tmp_path / "data/state/observations.parquet", Observation)
    assert len(observations) == 2
