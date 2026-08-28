from __future__ import annotations
import json,uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import TypeVar
import pyarrow as pa,pyarrow.parquet as pq
from pydantic import BaseModel
from property_hunt.models import Listing,ListingEvent
T=TypeVar("T",bound=BaseModel)
def write_models(path:str|Path,records:list[BaseModel],model:type[BaseModel]|None=None)->None:
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True); rows=[r.model_dump(mode="json") for r in records]
 if not rows and model: rows=[]
 table=pa.Table.from_pylist(rows) if rows else pa.table({"_empty":pa.array([],type=pa.string())});pq.write_table(table,p)
def read_models(path:str|Path,model:type[T])->list[T]:
 p=Path(path)
 if not p.exists():return []
 rows=pq.read_table(p).to_pylist();return [] if rows and "_empty" in rows[0] else [model.model_validate(r) for r in rows]
def detect_events(previous:list[Listing],current:list[Listing],at:datetime|None=None)->list[ListingEvent]:
 at=at or datetime.now(timezone.utc); old={x.id:x for x in previous};new={x.id:x for x in current};events=[]
 def add(i,t,b=None,a=None,reasons=[]):events.append(ListingEvent(event_id=str(uuid.uuid4()),listing_id=i,event_type=t,occurred_at=at,before=b,after=a,reasons=reasons))
 for i in new.keys()-old.keys():add(i,"added",a=new[i].model_dump(mode="json"))
 for i in old.keys()-new.keys():add(i,"removed",b=old[i].model_dump(mode="json"))
 for i in old.keys()&new.keys():
  changed=[f for f in ("price_aed","area_sqft","status","duplicate_group_id") if getattr(old[i],f)!=getattr(new[i],f)]
  if changed:add(i,"changed",old[i].model_dump(mode="json"),new[i].model_dump(mode="json"),changed)
 return events
def append_events(path:str|Path,events:list[ListingEvent])->None:
 old=read_models(path,ListingEvent);write_models(path,old+events,ListingEvent)
