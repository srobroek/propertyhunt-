"""Typed domain models; all calculated evidence remains inspectable."""
from __future__ import annotations
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
class Confidence(StrEnum):
    HIGH="high"; MEDIUM="medium"; LOW="low"; UNKNOWN="unknown"
class Provenance(StrictModel):
    source: str; source_id: str|None=None; url: HttpUrl|None=None
    fetched_at: datetime=Field(default_factory=lambda: datetime.now(timezone.utc))
    method: str="unknown"; payload_hash: str|None=None
class Derivation(StrictModel):
    metric: str; formula: str; inputs: dict[str, Any]=Field(default_factory=dict); reasons: list[str]=Field(default_factory=list)
class Conflict(StrictModel):
    field: str; values: list[Any]; reason: str
class DataQualityWarning(StrictModel):
    code: str; message: str; severity: str="warning"
class Listing(StrictModel):
    id: str; source: str; source_id: str; title: str=""; url: str|None=None
    price_aed: float=Field(gt=0); area_sqft: float=Field(gt=0); bedrooms: int=Field(ge=0, le=20); bathrooms: float|None=Field(None, ge=0)
    building_name: str; community: str|None=None; property_type: str="apartment"; status: str="active"; furnished: bool|None=None
    observed_at: datetime=Field(default_factory=lambda: datetime.now(timezone.utc)); canonical_building_id: str|None=None
    canonicalization_confidence: float|None=Field(None, ge=0, le=1); canonicalization_reasons: list[str]=Field(default_factory=list)
    layout_group_id: str|None=None; layout_confidence: float|None=Field(None, ge=0, le=1); layout_signals: list[str]=Field(default_factory=list)
    duplicate_group_id: str|None=None; duplicate_confidence: float|None=Field(None, ge=0, le=1); duplicate_reasons: list[str]=Field(default_factory=list)
    conflicts: list[Conflict]=Field(default_factory=list); warnings: list[DataQualityWarning]=Field(default_factory=list); provenance: Provenance|None=None
class Observation(StrictModel):
    listing_id: str; observed_at: datetime; price_aed: float; area_sqft: float; status: str; provenance: Provenance
class Transaction(StrictModel):
    id: str; building_name: str; community: str|None=None; canonical_building_id: str|None=None; transaction_date: date
    price_aed: float=Field(gt=0); area_sqft: float=Field(gt=0); bedrooms: int|None=Field(None, ge=0); property_type: str="apartment"; provenance: Provenance
    @property
    def price_per_sqft(self)->float: return self.price_aed/self.area_sqft
class RentalRecord(StrictModel):
    id: str; building_name: str; annual_rent_aed: float=Field(gt=0); area_sqft: float|None=None; bedrooms: int|None=None; contract_date: date|None=None; registered: bool=False; provenance: Provenance
class Project(StrictModel):
    id: str; name: str; developer: str|None=None; completion_percent: float|None=Field(None, ge=0, le=100); completion_date: date|None=None; provenance: Provenance
class SourceDiagnostic(StrictModel):
    source: str; status: str; message: str; records: int=0; pages: int=0; attempts: int=0; partial: bool=False; details: dict[str,Any]=Field(default_factory=dict)
class ComparableEvidence(StrictModel):
    transaction_id: str; included: bool; reason: str; tier: str; age_days: int; recency_weight: float=Field(ge=0, le=1); price_per_sqft: float
class UnderwritingResult(StrictModel):
    listing_id: str; metrics: dict[str,float|None]; derivations: list[Derivation]; warnings: list[DataQualityWarning]=Field(default_factory=list); rent_evidence_label: str
class ListingEvent(StrictModel):
    event_id: str; listing_id: str; event_type: str; occurred_at: datetime; before: dict[str,Any]|None=None; after: dict[str,Any]|None=None; reasons: list[str]=Field(default_factory=list)
class ScoreComponent(StrictModel):
    name: str; raw: float; weight: float; contribution: float; reasons: list[str]=Field(default_factory=list)
class Score(StrictModel):
    listing_id: str; kind: str; total: float=Field(ge=0, le=100); components: list[ScoreComponent]; exclusion_reasons: list[str]=Field(default_factory=list)
class RunSummary(StrictModel):
    run_id: str; started_at: datetime; completed_at: datetime|None=None; counts: dict[str,int]=Field(default_factory=dict); diagnostics: list[SourceDiagnostic]=Field(default_factory=list); exclusions: dict[str,int]=Field(default_factory=dict); warnings: list[DataQualityWarning]=Field(default_factory=list); artifacts: list[str]=Field(default_factory=list)
