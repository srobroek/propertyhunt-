from __future__ import annotations

import json
import os
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel

from property_hunt.models import Project, Provenance, RegistryEntity, RentalRecord, SourceDiagnostic, Transaction
from .base import FetchResult, SourceAdapter
from .dld import DLDAdapter, DLDProjectAdapter, DLDRentAdapter, _first, _row

T = TypeVar("T", bound=BaseModel)

TOKEN_URL = "https://api.dubaipulse.gov.ae/oauth/client_credential/accesstoken?grant_type=client_credentials"
TRANSACTIONS_API = "https://api.dubaipulse.gov.ae/open/dld/dld_transactions-open-api"
RENTS_API = "https://api.dubaipulse.gov.ae/open/dld/dld_rent_contracts-open-api"
PROJECTS_API = "https://api.dubaipulse.gov.ae/open/dld/dld_projects-open-api"
BUILDINGS_API = "https://api.dubaipulse.gov.ae/open/dld/dld_buildings-open-api"
UNITS_API = "https://api.dubaipulse.gov.ae/open/dld/dld_units-open-api"
DEVELOPERS_API = "https://api.dubaipulse.gov.ae/open/dld/dld_developers-open-api"
LAND_API = "https://api.dubaipulse.gov.ae/open/dld/dld_land_registry-open-api"


def _records_from_json(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload.decode("utf-8"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("results", "result", "data", "records", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for nested in ("results", "records", "items", "data"):
                child = value.get(nested)
                if isinstance(child, list):
                    return [x for x in child if isinstance(x, dict)]
    return []


def _json_to_csv_payload(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    import csv
    import io

    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=keys)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


class DubaiPulseBase(SourceAdapter[T], Generic[T]):
    endpoint = ""

    async def _token(self) -> str | None:
        key = os.getenv("DUBAI_PULSE_API_KEY")
        secret = os.getenv("DUBAI_PULSE_API_SECRET")
        if not key or not secret:
            return None
        response = await self.client.post(
            TOKEN_URL,
            data={"client_id": key, "client_secret": secret},
            timeout=self.policy.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("access_token") if isinstance(data, dict) else None

    async def _api_payload(self, endpoint: str, limit: int, offset: int = 0) -> bytes:
        token = await self._token()
        if not token:
            raise RuntimeError(
                "Dubai Pulse API credentials are not configured; set DUBAI_PULSE_API_KEY and DUBAI_PULSE_API_SECRET"
            )
        response = await self.client.get(
            endpoint,
            params={"limit": limit, "offset": offset},
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.policy.timeout_seconds,
        )
        response.raise_for_status()
        return response.content


class DubaiPulseTransactionsAdapter(DubaiPulseBase[Transaction]):
    name = "dubai_pulse_transactions"
    endpoint = TRANSACTIONS_API

    async def fetch(self, **kwargs: object) -> FetchResult[Transaction]:
        csv_url = kwargs.get("url")
        limit = int(kwargs.get("limit", 1000))
        try:
            if csv_url:
                records = DLDAdapter.parse(await self.request(str(csv_url)), str(csv_url))
                method = "Dubai Pulse CSV"
            else:
                rows = _records_from_json(await self._api_payload(self.endpoint, limit))
                records = DLDAdapter.parse(_json_to_csv_payload(rows), self.endpoint)
                method = "Dubai Pulse API"
            return FetchResult(
                records=records,
                diagnostics=[
                    SourceDiagnostic(
                        source=self.name,
                        status="ok" if records else "partial",
                        message=f"{method} transaction data parsed",
                        records=len(records),
                        attempts=1,
                        partial=not bool(records),
                        details={"endpoint": self.endpoint, "limit": limit},
                    )
                ],
                complete=bool(records),
            )
        except Exception as exc:
            return FetchResult(
                complete=False,
                diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)],
            )


class DubaiPulseRentsAdapter(DubaiPulseBase[RentalRecord]):
    name = "dubai_pulse_rents"
    endpoint = RENTS_API

    async def fetch(self, **kwargs: object) -> FetchResult[RentalRecord]:
        csv_url = kwargs.get("url")
        limit = int(kwargs.get("limit", 1000))
        try:
            if csv_url:
                records = DLDRentAdapter.parse(await self.request(str(csv_url)), str(csv_url))
                method = "Dubai Pulse CSV"
            else:
                rows = _records_from_json(await self._api_payload(self.endpoint, limit))
                records = DLDRentAdapter.parse(_json_to_csv_payload(rows), self.endpoint)
                method = "Dubai Pulse API"
            return FetchResult(
                records=records,
                diagnostics=[
                    SourceDiagnostic(
                        source=self.name,
                        status="ok" if records else "partial",
                        message=f"{method} Ejari data parsed",
                        records=len(records),
                        attempts=1,
                        partial=not bool(records),
                        details={"endpoint": self.endpoint, "limit": limit},
                    )
                ],
                complete=bool(records),
            )
        except Exception as exc:
            return FetchResult(
                complete=False,
                diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)],
            )


class DubaiPulseProjectsAdapter(DubaiPulseBase[Project]):
    name = "dubai_pulse_projects"
    endpoint = PROJECTS_API

    async def fetch(self, **kwargs: object) -> FetchResult[Project]:
        csv_url = kwargs.get("url")
        limit = int(kwargs.get("limit", 1000))
        try:
            if csv_url:
                records = DLDProjectAdapter.parse(await self.request(str(csv_url)), str(csv_url))
                method = "Dubai Pulse CSV"
            else:
                rows = _records_from_json(await self._api_payload(self.endpoint, limit))
                records = DLDProjectAdapter.parse(_json_to_csv_payload(rows), self.endpoint)
                method = "Dubai Pulse API"
            return FetchResult(
                records=records,
                diagnostics=[
                    SourceDiagnostic(
                        source=self.name,
                        status="ok" if records else "partial",
                        message=f"{method} project data parsed",
                        records=len(records),
                        attempts=1,
                        partial=not bool(records),
                        details={"endpoint": self.endpoint, "limit": limit},
                    )
                ],
                complete=bool(records),
            )
        except Exception as exc:
            return FetchResult(
                complete=False,
                diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)],
            )


class DubaiPulseRegistryAdapter(DubaiPulseBase[RegistryEntity]):
    name = "dubai_pulse_registry"
    ENDPOINTS = {
        "building": BUILDINGS_API,
        "unit": UNITS_API,
        "developer": DEVELOPERS_API,
        "land": LAND_API,
    }

    async def fetch(self, **kwargs: object) -> FetchResult[RegistryEntity]:
        entity_type = str(kwargs.get("entity_type") or "building")
        endpoint = str(kwargs.get("url") or self.ENDPOINTS.get(entity_type, ""))
        limit = int(kwargs.get("limit", 1000))
        if not endpoint:
            return FetchResult(
                complete=False,
                diagnostics=[
                    SourceDiagnostic(
                        source=self.name,
                        status="partial",
                        message=f"unknown registry entity type: {entity_type}",
                        partial=True,
                    )
                ],
            )
        try:
            rows = _records_from_json(await self._api_payload(endpoint, limit))
            records: list[RegistryEntity] = []
            for index, raw in enumerate(rows):
                row = _row(raw)
                sid = _first(
                    row,
                    "building_id",
                    "building_number",
                    "unit_id",
                    "unit_number",
                    "developer_id",
                    "developer_number",
                    "property_id",
                ) or str(index + 1)
                name = _first(
                    row,
                    "building_name_en",
                    "building_name",
                    "unit_number",
                    "developer_name_en",
                    "developer_name",
                    "land_number",
                )
                if not name:
                    continue
                records.append(
                    RegistryEntity(
                        id=f"dubai-pulse-{entity_type}:{sid}",
                        entity_type=entity_type,
                        name=name,
                        project_name=_first(row, "project_name_en", "project_name"),
                        community=_first(row, "area_name_en", "area_name"),
                        attributes=row,
                        provenance=Provenance(
                            source="dubai_pulse",
                            source_id=sid,
                            url=endpoint,
                            method="official-data-api",
                        ),
                    )
                )
            return FetchResult(
                records=records,
                diagnostics=[
                    SourceDiagnostic(
                        source=self.name,
                        status="ok" if records else "partial",
                        message=f"Dubai Pulse {entity_type} registry parsed",
                        records=len(records),
                        attempts=1,
                        partial=not bool(records),
                        details={"endpoint": endpoint, "limit": limit, "entity_type": entity_type},
                    )
                ],
                complete=bool(records),
            )
        except Exception as exc:
            return FetchResult(
                complete=False,
                diagnostics=[SourceDiagnostic(source=self.name, status="partial", message=str(exc), partial=True)],
            )
