# Codex daily property-hunt runbook

The ready-to-paste scheduled-task instruction is in
[`docs/codex-scheduled-task-prompt.md`](codex-scheduled-task-prompt.md). It
requires Codex to generate live data, analyse it, validate the artifacts, and
report partial sources honestly. This runbook explains the operating details.

This is the procedure for a **local, attended Codex agent run**. The scheduled
GitHub workflow validates the deterministic fixture path; it does not perform
live scraping or commit market data. This prevents an unattended timer from
accessing a site after its policy or markup changes.

## 1. Prepare and inspect

1. Work on a clean branch and read `README.md`, `docs/source-status.md`, and
   `config/hunt.yaml`.
2. Review each enabled source's current terms, robots policy, authentication,
   and documented/open-data access. Do not bypass login, CAPTCHA, blocking, or
   technical controls.
3. Put only verified public URLs in a local configuration. Never commit tokens,
   cookies, raw responses, or personal information.
4. Install Python 3.12 and the pinned dependencies:

   ```bash
   python3.12 -m venv .venv
   . .venv/bin/activate
   python -m pip install -e '.[dev]'
   ```

   If an approved public page requires JavaScript rendering, additionally run
   `python -m pip install -e '.[dev,browser]'` and `playwright install chromium`.

## 2. Validate before live access

```bash
ruff check src tests
mypy src
pytest --cov=property_hunt --cov-report=term-missing
property-hunt run --fixture-dir tests/fixtures --output-dir /tmp/property-hunt-check --no-browser --verbose
python scripts/validate_artifacts.py /tmp/property-hunt-check
```

Stop if any check fails. A fixture failure is a code failure, not a permitted
source partial failure.

## 3. Collect and analyse

1. Start with direct HTTP and an explicit source subset:

   ```bash
   property-hunt run --config config/hunt.yaml --source propertyfinder --source dld --output-dir . --no-browser --verbose
   ```

2. Inspect diagnostics and counts in `reports/latest.json`. An `unsupported` or
   `partial` source must produce no invented rows.
3. Only when an approved public page needs rendering, repeat without
   `--no-browser`. Browser fallback remains rate-limited and does not evade
   access challenges.
4. Review included and excluded comparables, canonicalization ambiguity,
   rent-evidence labels, derivations, conflicts, and warnings. Scores are
   screening signals, not investment advice.

## 4. Validate and persist

```bash
python scripts/validate_artifacts.py .
git diff --check
git status --short
```

Confirm that only intended files under `data/state/` and `reports/` changed,
source failures are visible, and no secrets or raw pages are staged. Commit
reviewed outputs on the current branch; do not automatically merge them.

## 5. Scheduling model

Codex can be invoked daily by a local task runner using the dedicated prompt.
The repository's `0 3 * * *` workflow independently runs the tests and fixture
pipeline at 07:00 GST. The Codex task performs the permission-reviewed live
collection locally; the GitHub schedule does not masquerade fixture output as
current market data. Changing that split requires a deliberate code change and
a fresh source-access review.
