from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
class Cfg(BaseModel):
    model_config=ConfigDict(extra="forbid")
class HTTPConfig(Cfg):
    timeout_seconds: float=20; retries: int=3; backoff_seconds: float=.5; rate_limit_per_second: float=1
    user_agent: str = "property-hunt/0.2 (+local research; contact repository owner)"
    browser_timeout_seconds: float = 30
class CanonicalizationConfig(Cfg): fuzzy_threshold: int=92; ambiguity_margin: int=4
class LayoutConfig(Cfg): absolute_area_sqft: float=75; percentage_area: float=.06
class AcquisitionConfig(Cfg): transfer_fee_pct: float=.04; agent_fee_pct: float=.02; mortgage_registration_pct: float=.0025; trustee_fee_aed: float=4200; valuation_fee_aed: float=3000
class FinancingConfig(Cfg): down_payment_pct: float=.25; annual_interest_rate: float=.045; term_years: int=25; loan_fee_pct: float=.01
class RentalConfig(Cfg): vacancy_pct: float=.08; maintenance_pct: float=.05; service_charge_aed_sqft: float=15; str_management_fee: float
class HuntConfig(Cfg):
    sources: dict[str,dict[str,Any]]; http: HTTPConfig; canonicalization: CanonicalizationConfig; layouts: LayoutConfig
    comp_windows_days: list[int]; acquisition: AcquisitionConfig; financing: FinancingConfig; rental: RentalConfig
    scoring_weights: dict[str,float]; thresholds: dict[str,float]; all_in_ceiling_aed: float; allowed_bedrooms: list[int]=[1,2]
    @model_validator(mode="after")
    def exact_fee(self):
        if self.rental.str_management_fee != .17: raise ValueError("STR management fee must be exactly 17%")
        if self.comp_windows_days != [30,90,180,365]: raise ValueError("comp windows must be 30/90/180/365")
        if abs(sum(self.scoring_weights.values())-1)>1e-6: raise ValueError("scoring weights must total 1")
        if self.all_in_ceiling_aed != 2_200_000: raise ValueError("all-in ceiling must be AED 2.2m")
        if self.http.rate_limit_per_second <= 0: raise ValueError("rate limit must be positive")
        return self
def load_config(path: str|Path="config/hunt.yaml")->HuntConfig:
    with Path(path).open(encoding="utf-8") as f: raw=yaml.safe_load(f)
    return HuntConfig.model_validate(raw)
