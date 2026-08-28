from __future__ import annotations
import hashlib,json,re
from datetime import datetime,timezone
from typing import Any
from property_hunt.models import Listing,Provenance,SourceDiagnostic
from .base import FetchResult,SourceAdapter,unsupported
class PropertyFinderAdapter(SourceAdapter[Listing]):
    name="propertyfinder"
    @staticmethod
    def parse(payload:bytes,url:str="fixture://propertyfinder")->list[Listing]:
        text=payload.decode("utf-8")
        blocks=re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',text,re.I|re.S)
        out=[]
        for block in blocks:
            try:data=json.loads(block)
            except json.JSONDecodeError:continue
            nodes=data.get("@graph",[]) if isinstance(data,dict) and "@graph" in data else ([data] if isinstance(data,dict) else data)
            for x in nodes:
                if not isinstance(x,dict) or x.get("@type") not in {"Product","Apartment","Residence","RealEstateListing"}:continue
                offer=x.get("offers",{}); floor=x.get("floorSize",{}); address=x.get("address",{})
                extra=x.get("additionalProperty",[]); props={str(p.get("name","")).lower():p.get("value") for p in extra if isinstance(p,dict)}
                try:
                    fallback=hashlib.sha256(str(x.get("url",url)).encode()).hexdigest()[:16]
                    sid=str(x.get("sku") or x.get("identifier") or fallback)
                    out.append(Listing(id=f"propertyfinder:{sid}",source="propertyfinder",source_id=sid,title=x.get("name","") ,url=x.get("url",url),price_aed=float(offer.get("price")),area_sqft=float(floor.get("value") or props["area"]),bedrooms=int(props.get("bedrooms",0)),bathrooms=float(props["bathrooms"]) if props.get("bathrooms") is not None else None,building_name=str(props.get("building") or address.get("streetAddress") or x.get("name","Unknown")),community=address.get("addressLocality"),provenance=Provenance(source="propertyfinder",source_id=sid,url=x.get("url") if str(x.get("url","")).startswith("http") else None,method="json-ld")))
                except (KeyError,TypeError,ValueError):continue
        return out
    async def fetch(self,**kwargs:object)->FetchResult[Listing]:
        url=kwargs.get("url"); allow_browser=bool(kwargs.get("allow_browser",False))
        if not url:return unsupported(self.name,"No publicly verified start URL configured; no browser automation attempted")
        try:
            payload=await self.request(str(url)); records=self.parse(payload,str(url))
            method="public JSON-LD parsed"
            if not records and allow_browser:
                payload=await self.browser_request(str(url)); records=self.parse(payload,str(url)); method="browser-rendered JSON-LD parsed"
            status="ok" if records else "partial"
            return FetchResult(records=records,complete=bool(records),diagnostics=[SourceDiagnostic(source=self.name,status=status,message=method if records else "no supported JSON-LD listing records found",records=len(records),pages=1,attempts=1,partial=not records)])
        except Exception as e:return FetchResult(complete=False,diagnostics=[SourceDiagnostic(source=self.name,status="partial",message=str(e),partial=True)])
