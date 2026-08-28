from __future__ import annotations
import re,unicodedata
from pathlib import Path
import yaml
from rapidfuzz.fuzz import ratio
from pydantic import BaseModel
class CanonicalMatch(BaseModel):
    canonical_id:str|None; confidence:float; reasons:list[str]; ambiguous:bool=False; candidates:list[str]=[]
def normalize_name(v:str)->str:
    v=unicodedata.normalize("NFKD",v).encode("ascii","ignore").decode().lower(); return " ".join(re.sub(r"[^a-z0-9]+"," ",v).split())
class BuildingCanonicalizer:
    def __init__(self,alias_path="data/metadata/building_aliases.yaml",threshold=92,ambiguity_margin=4):
        raw=yaml.safe_load(Path(alias_path).read_text()) or {}; self.aliases=raw.get("aliases",{}); self.threshold=threshold; self.margin=ambiguity_margin
    def match(self,name:str,community:str|None=None)->CanonicalMatch:
        key=normalize_name(name); comm=normalize_name(community or "")
        exact=self.aliases.get(key)
        if exact and (not exact.get("community") or normalize_name(exact["community"])==comm): return CanonicalMatch(canonical_id=exact["canonical"],confidence=1,reasons=["manual alias","community agrees"])
        scored=[]
        for alias,v in self.aliases.items():
            score=ratio(key,normalize_name(alias));
            if comm and normalize_name(v.get("community",""))==comm:score=min(100,score+3)
            scored.append((score,v["canonical"],alias))
        scored.sort(reverse=True)
        if not scored or scored[0][0]<self.threshold:return CanonicalMatch(canonical_id=None,confidence=0,reasons=["no conservative match"])
        if len(scored)>1 and scored[0][0]-scored[1][0]<self.margin and scored[0][1]!=scored[1][1]:return CanonicalMatch(canonical_id=None,confidence=scored[0][0]/100,reasons=["fuzzy candidates too close"],ambiguous=True,candidates=[scored[0][1],scored[1][1]])
        return CanonicalMatch(canonical_id=scored[0][1],confidence=scored[0][0]/100,reasons=[f"fuzzy name {scored[0][0]:.0f}","community context applied" if comm else "no community context"])
