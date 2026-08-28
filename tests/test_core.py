from datetime import date
from pathlib import Path
from typer.testing import CliRunner
from property_hunt.cli import app
from property_hunt.config import load_config
from property_hunt.models import Listing
from property_hunt.normalize import BuildingCanonicalizer,normalize_name
from property_hunt.sources.dld import DLDAdapter
from property_hunt.sources.propertyfinder import PropertyFinderAdapter
from property_hunt.underwriting import monthly_mortgage,underwrite
from property_hunt.matching import group_duplicates,group_layouts
from property_hunt.comps import select_comparables
from property_hunt.storage import detect_events

def listing(i="1",price=1_200_000,area=760):return Listing(id=i,source="x",source_id=i,price_aed=price,area_sqft=area,bedrooms=1,bathrooms=2,building_name="Marina Pinnacle",community="Dubai Marina",canonical_building_id="marina-pinnacle")
def test_config_and_models():
 c=load_config();assert c.rental.str_management_fee==.17 and c.all_in_ceiling_aed==2_200_000
def test_parsers():
 assert len(PropertyFinderAdapter.parse(Path("tests/fixtures/propertyfinder.html").read_bytes()))==1
 assert len(DLDAdapter.parse(Path("tests/fixtures/dld.csv").read_bytes()))==2
def test_normalization_and_ambiguity():
 c=BuildingCanonicalizer();assert normalize_name("Tôwer—One!")=="tower one";assert c.match("Tiger Tower","Dubai Marina").canonical_id=="marina-pinnacle";assert c.match("Unknown").canonical_id is None
def test_layout_and_duplicates():
 a,b=listing("a"),listing("b",1_250_000,770);group_layouts([a,b]);group_duplicates([a,b]);assert a.layout_group_id==b.layout_group_id;assert a.duplicate_group_id==b.duplicate_group_id;assert any(x.field=="price_aed" for x in a.conflicts)
def test_comps_recency_priority():
 l=listing();tx=DLDAdapter.parse(Path("tests/fixtures/dld.csv").read_bytes());[setattr(x,"canonical_building_id","marina-pinnacle") for x in tx];ev,stats=select_comparables(l,tx,date(2026,8,28));assert stats["count"]==2 and ev[0].tier=="same_layout"
def test_underwriting_financing():
 c=load_config();u=underwrite(listing(),c,72_000);assert monthly_mortgage(100_000,.05,25)>500;assert u.metrics["all_in_cost"]>1_200_000;assert u.derivations[1].inputs["management_fee"]==.17
def test_state_transitions():
 assert detect_events([listing(price=1_000_000)],[listing(price=900_000)])[0].event_type=="changed"
def test_cli_fixture(tmp_path):
 r=CliRunner().invoke(app,["run","--fixture-dir","tests/fixtures","--output-dir",str(tmp_path),"--no-browser"]);assert r.exit_code==0,r.output;assert (tmp_path/"reports/latest.json").exists();assert (tmp_path/"data/state/listings.parquet").exists()
