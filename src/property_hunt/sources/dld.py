from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any

from property_hunt.models import Project, Provenance, RentalRecord, SourceDiagnostic, Transaction
from .base import FetchResult, SourceAdapter, unsupported

SQM_TO_SQFT = 10.7639104167


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _row(row: dict[str, Any]) -> dict[str, str]:
    return {_norm_key(str(k)): "" if v is None else str(v).strip() for k, v in row.items()}


def _first(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(_norm_key(key))
        if value not in (None, "", "null", "None"):
            return value
    return None


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", value)
    return float(match.group(0).replace(",", "")) if match else None


def _int(value: str | None) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip().split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _csv_rows(payload: bytes) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig", errors="replace")
    return [_row(row) for row in csv.DictReader(io.StringIO(text))]


def _looks_like_csv(payload: bytes) -> bool:
    head = payload[:4096].decode("utf-8-sig", errors="ignore").lstrip().lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return False
    first_line = head.splitlines()[0] if head.splitlines() else ""
    return "," in first_line


def _area_sqft(row: dict[str, str]) -> float | None:
    sqft = _float(_first(row, "area_sqft", "property_size_sqft", "transaction_size_sqft"))
    if sqft and sqft > 0:
        return sqft
    sqm = _float(
        _first(
            row,
            "property_size_sqm",
            "property_size_sq_m",
            "property_size_sq_m_t",
            "property_size_sq_m_",
            "property_size_sq_meters",
            "property_size",
            "procedure_area",
            "transaction_size_sq_m",
            "transaction_size_sqm",
        )
    )
    return sqm * SQM_TO_SQFT if sqm and sqm > 0 else None


def _bedrooms(row: dict[str, str]) -> int | None:
    raw = _first(row, "bedrooms", "rooms", "room_s", "rooms_en", "room_type_en")
    if not raw:
        return None
    if "studio" in raw.lower():
        return 0
    return _int(raw)


def _gated(source: str, message: str, url: str) -> FetchResult:
    return FetchResult(
        complete=False,
        diagnostics=[
            SourceDiagnostic(
                source=source,
                status="query-gated",
                message=message,
                records=0,
                pages=1,
                attempts=1,
                partial=True,
                details={"url": url, "reachable": True, "requires_query": True},
            )
        ],
    )


class DLDAdapter(SourceAdapter[Transaction]):
    name = "dld"

    @staticmethod
    def parse(payload: bytes, url: str = "fixture://dld") -> list[Transaction]:
        out: list[Transaction] = []
        for row in _csv_rows(payload):
            sid = _first(row, "transaction_id", "transaction_number", "procedure_id", "procedure_number")
            tx_date = _date(_first(row, "transaction_date", "instance_date", "procedure_date"))
            price = _float(_first(row, "price_aed", "amount", "actual_worth", "worth"))
            area = _area_sqft(row)
            building = _first(row, "building_name", "project_name_en", "project_name", "project", "master_project_en", "master_project")
            community = _first(row, "area_name", "area_name_en", "community")
            if not (tx_date and price and price > 0 and area and area > 0 and building):
                continue
            sid = sid or f"{tx_date.isoformat()}-{len(out) + 1}"
            property_type = (_first(row, "property_sub_type_en", "property_type", "property_type_en") or "apartment").lower()
            out.append(Transaction(id=f"dld:{sid}", building_name=building, community=community, transaction_date=tx_date, price_aed=price, area_sqft=area, bedrooms=_bedrooms(row), property_type=property_type, provenance=Provenance(source="dld", source_id=sid, url=url if url.startswith("http") else None, method="official-open-data-csv")))
        return out

    async def fetch(self, **kwargs: object) -> FetchResult[Transaction]:
        url = kwargs.get("url")
        if not url:
            return unsupported(self.name, "No official DLD source configured")
        try:
            payload = await self.request(str(url))
            if not _looks_like_csv(payload):
                return _gated(self.name, "official DLD transaction page reachable; current rows require the public date/CAPTCHA query or an export/API URL", str(url))
            records = self.parse(payload, str(url))
            return FetchResult(records=records, diagnostics=[SourceDiagnostic(source=self.name, status="ok" if records else "partial", message="official DLD transaction CSV parsed", records=len(records), pages=1, attempts=1, partial=not bool(records))], complete=bool(records))
        except Exception as exc:
            return FetchResult(complete=False, diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)])


class DLDRentAdapter(SourceAdapter[RentalRecord]):
    name = "dld_rents"

    @staticmethod
    def parse(payload: bytes, url: str = "fixture://dld-rents") -> list[RentalRecord]:
        out: list[RentalRecord] = []
        for row in _csv_rows(payload):
            annual = _float(_first(row, "annual_amount", "annual_rent_aed", "contract_amount"))
            area = _area_sqft(row)
            building = _first(row, "building_name", "project_name_en", "project_name", "project")
            contract_date = _date(_first(row, "registration_date", "contract_start_date", "start_date", "contract_date"))
            if not (annual and annual > 0 and building):
                continue
            sid = _first(row, "contract_id", "ejari_id", "registration_number") or f"rent-{len(out)+1}"
            out.append(RentalRecord(id=f"dld-rent:{sid}", building_name=building, community=_first(row, "area_name", "area_name_en", "community"), annual_rent_aed=annual, area_sqft=area, bedrooms=_bedrooms(row), contract_date=contract_date, property_type=(_first(row, "property_sub_type_en", "property_type", "property_type_en") or "apartment").lower(), registered=True, provenance=Provenance(source="dld", source_id=sid, url=url if url.startswith("http") else None, method="official-ejari-open-data")))
        return out

    async def fetch(self, **kwargs: object) -> FetchResult[RentalRecord]:
        url = kwargs.get("url")
        if not url:
            return unsupported(self.name, "No official DLD rent source configured")
        try:
            payload = await self.request(str(url))
            if not _looks_like_csv(payload):
                return _gated(self.name, "official DLD rent page reachable; current Ejari rows require the public date/CAPTCHA query or an export/API URL", str(url))
            records = self.parse(payload, str(url))
            return FetchResult(records=records, diagnostics=[SourceDiagnostic(source=self.name, status="ok" if records else "partial", message="registered DLD rent CSV parsed", records=len(records), pages=1, attempts=1, partial=not bool(records))], complete=bool(records))
        except Exception as exc:
            return FetchResult(complete=False, diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)])


class DLDProjectAdapter(SourceAdapter[Project]):
    name = "dld_projects"

    @staticmethod
    def parse(payload: bytes, url: str = "fixture://dld-projects") -> list[Project]:
        out: list[Project] = []
        for row in _csv_rows(payload):
            name = _first(row, "project_name", "project_name_en", "name")
            if not name:
                continue
            sid = _first(row, "project_number", "project_id", "property_id") or str(len(out) + 1)
            completion = _float(_first(row, "completed", "completed_percent", "completion_percent", "completed_%"))
            out.append(Project(id=f"dld-project:{sid}", name=name, developer=_first(row, "developer_name", "developer_name_en"), community=_first(row, "area", "area_name", "area_name_en"), status=_first(row, "project_status", "project_status_en", "status"), start_date=_date(_first(row, "start_date")), advertised_end_date=_date(_first(row, "end_date")), completion_percent=completion, inspection_date=_date(_first(row, "inspection_date")), completion_date=_date(_first(row, "completion_date")), total_units=_int(_first(row, "total_units", "units")), provenance=Provenance(source="dld", source_id=sid, url=url if url.startswith("http") else None, method="official-project-open-data")))
        return out

    async def fetch(self, **kwargs: object) -> FetchResult[Project]:
        url = kwargs.get("url")
        if not url:
            return unsupported(self.name, "No official DLD project source configured")
        try:
            payload = await self.request(str(url))
            if not _looks_like_csv(payload):
                return _gated(self.name, "official DLD project-status page reachable; project records require a project-name/number query or official export", str(url))
            records = self.parse(payload, str(url))
            return FetchResult(records=records, diagnostics=[SourceDiagnostic(source=self.name, status="ok" if records else "partial", message="DLD project CSV parsed", records=len(records), pages=1, attempts=1, partial=not bool(records))], complete=bool(records))
        except Exception as exc:
            return FetchResult(complete=False, diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)])
