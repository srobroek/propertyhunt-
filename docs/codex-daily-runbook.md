# Codex daily property-hunt runbook

The intended production runner is a **Codex Automation / cloud task**, not a scheduled GitHub Actions workflow. GitHub is used for source code and persisted state; daily compute should not consume GitHub Actions minutes.

The ready-to-paste automation instruction is in [`docs/codex-scheduled-task-prompt.md`](codex-scheduled-task-prompt.md).

## 1. Environment

The ephemeral runner needs:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,browser]'
playwright install --with-deps chromium
```

Outbound access is required for the enabled sources in `config/hunt.yaml`.

No database is required. Prior state is restored by cloning/pulling the Git repository; updated Parquet state and reports are committed back after a successful run.

## 2. Preflight

Run before live collection:

```bash
ruff check src tests scripts
mypy src/property_hunt
pytest --cov=property_hunt --cov-report=term-missing
property-hunt run --fixture-dir tests/fixtures --output-dir /tmp/property-hunt-check --no-browser --verbose
python scripts/validate_artifacts.py /tmp/property-hunt-check
```

A test/fixture failure is a code failure. Do not continue to live collection in that case.

## 3. Live collection

Run:

```bash
property-hunt run --config config/hunt.yaml --output-dir . --verbose
```

Collection behavior is:

1. direct HTTP first;
2. browser rendering through Playwright when direct HTTP produces no usable listing data or an ordinary JavaScript-rendered page;
3. if an explicit access challenge/CAPTCHA remains, mark that source partial and continue;
4. never invent rows for failed sources.

Enabled live listing sources are configured in `config/hunt.yaml`. Current-year official DLD exports remain disabled until a non-interactive approved data path is available because the public export currently uses an interactive CAPTCHA.

## 4. Validate outputs

After collection:

```bash
python scripts/validate_artifacts.py .
git diff --check
git status --short
```

Inspect `reports/latest.json` for:

- source diagnostics;
- unexpectedly low record counts;
- canonicalization ambiguity;
- candidate exclusions;
- comparable evidence;
- underwriting assumptions;
- price/listing events.

A partial source is acceptable only if it is visible in diagnostics and the report does not imply complete coverage.

## 5. Persist state

If the run is valid:

```bash
git add data reports
git commit -m "property hunt: $(date -u +%F)"
git push origin HEAD:main
```

Do not commit secrets, cookies, raw browser profiles, debug HTML, or CAPTCHA/challenge material.

## 6. Daily analysis

After deterministic collection, analyse `reports/latest.json` and the normalized Parquet data. Prioritize:

- same-layout and same-building transaction discounts;
- new/reduced/relisted/vacant units;
- realistic long-term and furnished rental economics;
- service-charge drag;
- financing-adjusted cash flow;
- transaction/rental liquidity;
- off-plan construction/handover risk;
- unresolved data conflicts.

Return the investable conclusion first and explicitly disclose source coverage failures.

## 7. GitHub Actions

`.github/workflows/daily.yml` is intentionally **manual only**. It exists for an occasional validation run and is not the production scheduler.
