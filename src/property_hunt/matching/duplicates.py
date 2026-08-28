from __future__ import annotations
import hashlib
from property_hunt.models import Conflict,Listing
def group_duplicates(records:list[Listing])->list[Listing]:
    buckets:dict[tuple,list[Listing]]={}
    for r in records:buckets.setdefault((r.canonical_building_id,r.bedrooms,round(r.area_sqft/25)),[]).append(r)
    for key,group in buckets.items():
        if key[0] is None or len(group)<2:continue
        gid="dup-"+hashlib.sha1(repr(key).encode()).hexdigest()[:12]
        fields={"price_aed":{x.price_aed for x in group},"area_sqft":{x.area_sqft for x in group},"bedrooms":{x.bedrooms for x in group},"bathrooms":{x.bathrooms for x in group}}
        for r in group:
            r.duplicate_group_id=gid;r.duplicate_confidence=.85;r.duplicate_reasons=["same building","same bedrooms","area in same 25 sqft band"]
            r.conflicts.extend(Conflict(field=f,values=sorted(v,key=lambda x:str(x)),reason="duplicate sources disagree") for f,v in fields.items() if len(v)>1)
    return records
