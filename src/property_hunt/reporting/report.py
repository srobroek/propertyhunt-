from __future__ import annotations
import json
from datetime import date
from pathlib import Path
from typing import Any
def generate_report(payload:dict[str,Any],output_dir:str|Path="reports",day:date|None=None)->list[Path]:
 day=day or date.today();out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
 candidates=payload.get("candidates",[]);diagnostics=payload.get("diagnostics",[])
 lines=[f"# Property Hunt — {day.isoformat()}","","## Run totals",""]+[f"- **{k}**: {v}" for k,v in payload.get("counts",{}).items()]
 lines += ["","## Source diagnostics",""]+[f"- **{d['source']}** — {d['status']}: {d['message']} ({d.get('records',0)} records)" for d in diagnostics]
 lines += ["","## Candidates","","| Rank | Listing | Price AED | Score | All-in AED |","|---:|---|---:|---:|---:|"]
 for i,c in enumerate(candidates,1):lines.append(f"| {i} | {c['id']} | {c['price_aed']:,.0f} | {c['score']:.1f} | {c['underwriting']['metrics']['all_in_cost']:,.0f} |")
 lines += ["","## Changes",f"- Events: {payload.get('counts',{}).get('events',0)}","","## Warnings"]+[f"- {w}" for w in payload.get("warnings",[]) or ["None"]]
 lines += ["","## Evidence and derivations","Full included/excluded comparable evidence, score components, underwriting formulas, and source outcomes are available in `latest.json`."]
 dated=out/f"{day.isoformat()}.md";latest=out/"latest.md";js=out/"latest.json";text="\n".join(lines)+"\n";dated.write_text(text);latest.write_text(text);js.write_text(json.dumps(payload,indent=2,default=str)+"\n");return [dated,latest,js]
