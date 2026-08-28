from __future__ import annotations
from datetime import date
from statistics import median
from property_hunt.models import ComparableEvidence,Listing,Transaction
def select_comparables(listing:Listing,txns:list[Transaction],as_of:date|None=None,windows=(30,90,180,365)):
    as_of=as_of or date.today(); evidence=[]
    for t in txns:
        age=(as_of-t.transaction_date).days; same=t.canonical_building_id==listing.canonical_building_id
        layout=same and t.bedrooms==listing.bedrooms and abs(t.area_sqft-listing.area_sqft)<=max(75,.06*listing.area_sqft)
        included=same and 0<=age<=max(windows); tier="same_layout" if layout else "building" if same else "outside_building"
        reason="included same-layout" if layout and included else "included building-wide" if included else "excluded: building mismatch" if not same else "excluded: outside 365-day window"
        evidence.append(ComparableEvidence(transaction_id=t.id,included=included,reason=reason,tier=tier,age_days=age,recency_weight=max(0,1-age/max(windows)),price_per_sqft=t.price_per_sqft))
    evidence.sort(key=lambda x:(not x.included,0 if x.tier=="same_layout" else 1,x.age_days,x.transaction_id))
    chosen=[e for e in evidence if e.included]; values=[e.price_per_sqft for e in chosen]; weights=[e.recency_weight for e in chosen]
    stats={"count":len(chosen),"median_psf":median(values) if values else None,"weighted_psf":sum(v*w for v,w in zip(values,weights,strict=True))/sum(weights) if sum(weights)>0 else None}
    return evidence,stats
