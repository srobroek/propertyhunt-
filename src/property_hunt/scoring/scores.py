from __future__ import annotations
from property_hunt.models import Listing,Score,ScoreComponent,UnderwritingResult
def _component(name,raw,weight,reasons):return ScoreComponent(name=name,raw=max(0,min(100,raw)),weight=weight,contribution=max(0,min(100,raw))*weight,reasons=reasons)
def score_listing(listing:Listing,market_psf:float|None,uw:UnderwritingResult,weights:dict[str,float]|None=None)->Score:
 w=weights or {"valuation":.45,"distress":.2,"investment":.35}; exclusions=[]
 if market_psf is None: exclusions.append("valuation excluded: no eligible comparables"); valuation=0
 else: valuation=max(0,min(100,(market_psf-listing.price_aed/listing.area_sqft)/market_psf*500+50))
 # Distress needs corroborating signals: low price alone contributes nothing.
 signals=[]
 if listing.status in {"auction","urgent"}:signals.append("explicit urgent/auction status")
 if any("relist" in x.message.lower() for x in listing.warnings):signals.append("relisting history")
 distress=min(100,len(signals)*45); coc=uw.metrics.get("cash_on_cash"); investment=max(0,min(100,50+(coc or 0)*500))
 comps=[_component("valuation",valuation,w["valuation"],["discount relative to selected comps"] if market_psf else ["missing comps"]),_component("distress",distress,w["distress"],signals or ["low price alone is not distress"]),_component("investment",investment,w["investment"],["cash-on-cash after debt service"])]
 return Score(listing_id=listing.id,kind="combined",total=sum(c.contribution for c in comps),components=comps,exclusion_reasons=exclusions)
