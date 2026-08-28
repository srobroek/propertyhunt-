from __future__ import annotations
import hashlib
from property_hunt.models import Listing
def group_layouts(records:list[Listing],absolute_area_sqft:float=75,percentage_area:float=.06)->list[Listing]:
    groups:list[list[Listing]]=[]
    for r in sorted(records,key=lambda x:(x.canonical_building_id or "",x.bedrooms,x.area_sqft,x.id)):
        found=None
        for g in groups:
            anchor=g[0]; tol=max(absolute_area_sqft,anchor.area_sqft*percentage_area)
            if r.canonical_building_id and r.canonical_building_id==anchor.canonical_building_id and r.bedrooms==anchor.bedrooms and abs(r.area_sqft-anchor.area_sqft)<=tol:found=g;break
        if found is None:groups.append([r]);found=groups[-1]
        found.append(r) if r not in found else None
    for g in groups:
        key=f"{g[0].canonical_building_id}:{g[0].bedrooms}:{round(sum(x.area_sqft for x in g)/len(g))}"; gid="layout-"+hashlib.sha1(key.encode()).hexdigest()[:12]
        for r in g:r.layout_group_id=gid;r.layout_confidence=.95 if len(g)>1 else .7;r.layout_signals=["same canonical building","same bedrooms",f"area within {absolute_area_sqft} sqft or {percentage_area:.1%}"]
    return records
