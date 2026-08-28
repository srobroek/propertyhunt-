# Property Hunt

A Python 3.12, provenance-first UAE residential research pipeline. It preserves broad source records, avoids fabricated data when access is unavailable, and exposes comparable, underwriting, and scoring derivations.

The attended Codex procedure is documented in
[`docs/codex-daily-runbook.md`](docs/codex-daily-runbook.md), including source
review, fixture validation, optional browser rendering, analysis, and safe
persistence. A complete copy/paste prompt for a local daily Codex schedule is
available in
[`docs/codex-scheduled-task-prompt.md`](docs/codex-scheduled-task-prompt.md).

## Install

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

Network collection requires DNS/HTTPS access to only the domains explicitly configured in `config/hunt.yaml`; the checked-in configuration has no live URLs. Review each domain's current terms, robots policy, and licence first. Secrets belong in environment variables, never YAML. Optional browser rendering is installed with `pip install -e '.[browser]'` and `playwright install chromium`; `--no-browser` guarantees it is not requested.

> **Live-data precondition:** the shipped null URLs make fixture validation
> runnable but cannot generate a live market refresh. The scheduled Codex task
> must use permission-reviewed configured URLs and must report partial or empty
> extraction rather than presenting fixtures as current data.

## Commands

`property-hunt fetch|normalize|compare|score|report|run` accept `--config`, repeatable `--source`, `--max-price`, `--output-dir`, `--no-browser`, and `--verbose`. A deterministic demonstration is:

```bash
property-hunt run --fixture-dir tests/fixtures --output-dir /tmp/property-hunt --no-browser
```

## Artifacts and persistence

Current listings, transactions, observations, first-seen snapshots, and append-only events are Parquet files in `data/state/`. Reports are emitted as `reports/YYYY-MM-DD.md`, `latest.md`, and machine-readable `latest.json`. Commit these small derived outputs to retain Git-backed prior state. Raw responses are ignored.

## Limitations and troubleshooting

Unsupported sources produce partial diagnostics while the run continues. An unrecoverable configuration, filesystem, or schema failure exits nonzero. Empty live runs usually mean no approved URL is configured; inspect `latest.json` and `docs/source-status.md`. Parquet errors generally indicate a mismatched `pyarrow` install. This is research automation, not valuation, financial, legal, or investment advice; asking rents and registered rental evidence are labelled separately.
