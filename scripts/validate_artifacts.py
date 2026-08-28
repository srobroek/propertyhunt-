"""Validate schemas and internal consistency of a pipeline output tree."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq


def validate(root: Path) -> None:
    report = json.loads((root / "reports/latest.json").read_text(encoding="utf-8"))
    required = {"run_id", "counts", "diagnostics", "exclusions", "candidates"}
    if missing := required - report.keys():
        raise ValueError(f"report missing keys: {sorted(missing)}")

    state = root / "data/state"
    for name in ("listings", "transactions", "observations", "first_seen", "events"):
        path = state / f"{name}.parquet"
        if not path.is_file():
            raise FileNotFoundError(path)
        pq.read_schema(path)

    if report["counts"]["candidates"] != len(report["candidates"]):
        raise ValueError("candidate count does not match candidate rows")


if __name__ == "__main__":
    validate(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    print("artifact validation passed")
