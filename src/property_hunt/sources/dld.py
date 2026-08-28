from __future__ import annotations
import csv,io
from datetime import date
from property_hunt.models import Provenance,SourceDiagnostic,Transaction
from .base import FetchResult,SourceAdapter,unsupported
class DLDAdapter(SourceAdapter[Transaction]):
    name="dld"
    @staticmethod
    def parse(payload:bytes,url:str="fixture://dld")->list[Transaction]:
        rows=csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))); out=[]
        for r in rows:
            try:
                sid=r.get("transaction_id") or r.get("procedure_id") or str(len(out)+1)
                out.append(Transaction(id=f"dld:{sid}",building_name=r["building_name"],community=r.get("area_name"),transaction_date=date.fromisoformat(r["transaction_date"]),price_aed=float(r["price_aed"]),area_sqft=float(r["area_sqft"]),bedrooms=int(r["bedrooms"]) if r.get("bedrooms") else None,provenance=Provenance(source="dld",source_id=sid,method="open-data-csv")))
            except (KeyError,TypeError,ValueError):continue
        return out
    async def fetch(self,**kwargs:object)->FetchResult[Transaction]:
        url=kwargs.get("url")
        if not url:return unsupported(self.name,"Official CSV URL not configured; provide an approved Dubai open-data export")
        try:
            p=await self.request(str(url)); records=self.parse(p,str(url)); return FetchResult(records=records,diagnostics=[SourceDiagnostic(source=self.name,status="ok",message="official CSV parsed",records=len(records),pages=1,attempts=1)])
        except Exception as e:return FetchResult(complete=False,diagnostics=[SourceDiagnostic(source=self.name,status="partial",message=str(e),partial=True)])
