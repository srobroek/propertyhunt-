from __future__ import annotations
import asyncio,json
from datetime import date,datetime,timezone
from pathlib import Path
from typing import Any
from property_hunt.comps import select_comparables
from property_hunt.config import HuntConfig,load_config
from property_hunt.matching import group_duplicates,group_layouts
from property_hunt.models import Listing,Provenance,Transaction
from property_hunt.normalize import BuildingCanonicalizer
from property_hunt.reporting import generate_report
from property_hunt.scoring import score_listing
from property_hunt.sources.dld import DLDAdapter
from property_hunt.sources.propertyfinder import PropertyFinderAdapter
from property_hunt.storage import append_events,detect_events,read_models,write_models
from property_hunt.underwriting import underwrite
async def collect(cfg:HuntConfig,sources:list[str]|None=None,fixture_dir:str|Path|None=None,allow_browser:bool=False):
 wanted=sources or list(cfg.sources); listings=[];txns=[];diags=[]
 if fixture_dir:
  fd=Path(fixture_dir); listings=PropertyFinderAdapter.parse((fd/"propertyfinder.html").read_bytes());txns=DLDAdapter.parse((fd/"dld.csv").read_bytes());return listings,txns,diags
 adapters={"propertyfinder":PropertyFinderAdapter,"dld":DLDAdapter}
 for name in wanted:
  if name in adapters:
   a=adapters[name](cfg.http);result=await a.fetch(url=cfg.sources[name].get("url") or cfg.sources[name].get("start_url"),allow_browser=allow_browser);await a.close()
  else:
   module=__import__(f"property_hunt.sources.{name}",fromlist=["*"]);cls=next(v for k,v in vars(module).items() if k.endswith("Adapter"));a=cls(cfg.http);result=await a.fetch();await a.close()
  diags.extend(result.diagnostics)
  if name=="dld":txns.extend(result.records)
  else:listings.extend(result.records)
 return listings,txns,diags
def normalize_records(listings:list[Listing],txns:list[Transaction],cfg:HuntConfig):
 c=BuildingCanonicalizer(threshold=cfg.canonicalization.fuzzy_threshold,ambiguity_margin=cfg.canonicalization.ambiguity_margin)
 ambiguous=[]
 for r in [*listings,*txns]:
  m=c.match(r.building_name,r.community);r.canonical_building_id=m.canonical_id
  if isinstance(r,Listing):r.canonicalization_confidence=m.confidence;r.canonicalization_reasons=m.reasons
  if m.ambiguous:ambiguous.append(r)
 group_layouts(listings,cfg.layouts.absolute_area_sqft,cfg.layouts.percentage_area);group_duplicates(listings);return ambiguous
async def run_pipeline(config_path="config/hunt.yaml",sources=None,max_price=None,output_dir=".",fixture_dir=None,allow_browser=False)->dict[str,Any]:
 cfg=load_config(config_path); listings,txns,diags=await collect(cfg,sources,fixture_dir,allow_browser);ambiguous=normalize_records(listings,txns,cfg);base=Path(output_dir);state=base/"data/state";reports=base/"reports";previous=read_models(state/"listings.parquet",Listing);events=detect_events(previous,listings)
 write_models(state/"listings.parquet",listings,Listing);write_models(state/"transactions.parquet",txns,Transaction);write_models(state/"observations.parquet",[],None);write_models(state/"first_seen.parquet",listings,Listing);append_events(state/"events.parquet",events)
 ceiling=min(cfg.all_in_ceiling_aed,max_price or cfg.all_in_ceiling_aed);candidates=[];exclusions={"bedrooms":0,"all_in_ceiling":0,"ambiguous_building":0}
 for l in listings:
  uw=underwrite(l,cfg,annual_rent=l.price_aed*.06);all_in=uw.metrics["all_in_cost"] or 0
  if l.bedrooms not in cfg.allowed_bedrooms:exclusions["bedrooms"]+=1;continue
  if all_in>ceiling:exclusions["all_in_ceiling"]+=1;continue
  if not l.canonical_building_id:exclusions["ambiguous_building"]+=1;continue
  evidence,stats=select_comparables(l,txns);score=score_listing(l,stats["weighted_psf"],uw,cfg.scoring_weights)
  candidates.append({"id":l.id,"price_aed":l.price_aed,"score":score.total,"score_breakdown":score.model_dump(mode="json"),"underwriting":uw.model_dump(mode="json"),"comparables":[x.model_dump(mode="json") for x in evidence],"comp_statistics":stats})
 candidates.sort(key=lambda x:(-x["score"],x["id"]));payload={"run_id":datetime.now(timezone.utc).isoformat(),"counts":{"collected_listings":len(listings),"transactions":len(txns),"ambiguous":len(ambiguous),"candidates":len(candidates),"events":len(events)},"diagnostics":[d.model_dump(mode="json") for d in diags],"exclusions":exclusions,"candidates":candidates,"warnings":[]};generate_report(payload,reports,date.today());return payload
