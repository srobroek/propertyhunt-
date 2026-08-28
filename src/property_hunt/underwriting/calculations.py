from __future__ import annotations
from property_hunt.config import HuntConfig
from property_hunt.models import DataQualityWarning,Derivation,Listing,UnderwritingResult
def acquisition_costs(price:float,cfg:HuntConfig,mortgage:bool=True)->dict[str,float]:
 a=cfg.acquisition; f=cfg.financing; loan=price*(1-f.down_payment_pct) if mortgage else 0
 return {"transfer_fee":price*a.transfer_fee_pct,"agent_fee":price*a.agent_fee_pct,"trustee_fee":a.trustee_fee_aed,"valuation_fee":a.valuation_fee_aed if mortgage else 0,"mortgage_registration":loan*a.mortgage_registration_pct if mortgage else 0,"loan_fee":loan*f.loan_fee_pct if mortgage else 0}
def monthly_mortgage(principal:float,annual_rate:float,years:int)->float:
 n=years*12;r=annual_rate/12
 return principal/n if r==0 else principal*r*(1+r)**n/((1+r)**n-1)
def underwrite(listing:Listing,cfg:HuntConfig,annual_rent:float|None=None,str_gross:float|None=None,registered_rent:bool=False)->UnderwritingResult:
 costs=acquisition_costs(listing.price_aed,cfg); all_in=listing.price_aed+sum(costs.values()); loan=listing.price_aed*(1-cfg.financing.down_payment_pct); debt=monthly_mortgage(loan,cfg.financing.annual_interest_rate,cfg.financing.term_years)*12
 rent=annual_rent or 0; effective=rent*(1-cfg.rental.vacancy_pct); operating=effective*cfg.rental.maintenance_pct+listing.area_sqft*cfg.rental.service_charge_aed_sqft; noi=effective-operating; cash=listing.price_aed*cfg.financing.down_payment_pct+sum(costs.values()); flow=noi-debt
 str_net=(str_gross*(1-cfg.rental.str_management_fee-cfg.rental.vacancy_pct)-operating) if str_gross is not None else None
 metrics={**costs,"all_in_cost":all_in,"loan_principal":loan,"annual_debt_service":debt,"annual_noi":noi,"annual_cash_flow":flow,"break_even_rent":(operating+debt)/(1-cfg.rental.vacancy_pct),"cash_on_cash":flow/cash if cash else None,"str_net_before_debt":str_net}
 deriv=[Derivation(metric="annual_debt_service",formula="12 * amortizing monthly payment",inputs={"principal":loan,"rate":cfg.financing.annual_interest_rate,"years":cfg.financing.term_years}),Derivation(metric="str_net_before_debt",formula="gross * (1 - 17% management - vacancy) - operating",inputs={"management_fee":.17,"gross":str_gross})]
 warnings=[] if annual_rent else [DataQualityWarning(code="missing_rent",message="No rental evidence supplied")]
 return UnderwritingResult(listing_id=listing.id,metrics=metrics,derivations=deriv,warnings=warnings,rent_evidence_label="registered rental evidence" if registered_rent else "asking-rent estimate")
