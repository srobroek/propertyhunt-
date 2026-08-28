# Prompt for the daily Codex scheduled task

Copy the text between the horizontal rules into the scheduled Codex task. Set
its working directory to the repository root and schedule it for **07:00 GST
(03:00 UTC)**. The task is intentionally responsible for both collection and
analysis; the GitHub Actions schedule remains a deterministic fixture check.

---

Work in the property-hunt repository and execute today's UAE residential
property collection and analysis end to end.

1. Read `AGENTS.md` files (if any), `README.md`,
   `docs/codex-daily-runbook.md`, `docs/source-status.md`, and
   `config/hunt.yaml`. Check `git status` before changing anything. Preserve
   unrelated user changes.
2. Use Python 3.12. Create or reuse `.venv`, install the pinned project with
   `python -m pip install -e '.[dev,browser]'`, and install Playwright Chromium
   if it is not already present. Never invent a GitHub token or print secrets.
3. Before live access, run:

   ```bash
   ruff check src tests scripts
   mypy src
   pytest --cov=property_hunt --cov-report=term-missing
   property-hunt run --config config/hunt.yaml --fixture-dir tests/fixtures \
     --output-dir /tmp/property-hunt-check --no-browser --verbose
   python scripts/validate_artifacts.py /tmp/property-hunt-check
   ```

   Stop and report the exact failing command if deterministic validation
   fails. Do not replace a failed test with an assertion-free smoke test.
4. Reconfirm that each live URL is public, permitted by the current source
   terms and robots policy, and represented accurately in
   `docs/source-status.md`. Do not bypass authentication, CAPTCHA, paywalls,
   rate limits, bot challenges, or other access controls. Do not use stealth or
   fingerprint-evasion plugins. If a source is no longer permissible or its
   schema changed, retain a structured partial/unsupported diagnostic and
   continue with the other sources; never fabricate records.
5. Generate today's live data and analysis with direct HTTP first:

   ```bash
   property-hunt run --config config/hunt.yaml --output-dir . --no-browser --verbose
   ```

   If an approved public page genuinely requires JavaScript, rerun only the
   affected configured source without `--no-browser`, using the built-in
   rate-limited Playwright fallback. A configured URL is required for a live
   source. Do not silently treat fixture data as live data.
6. Run `python scripts/validate_artifacts.py .`. Inspect
   `reports/latest.json` and `reports/latest.md`: verify timestamps and counts,
   source outcomes, exclusions, ambiguous buildings, duplicate conflicts,
   comparable inclusion/exclusion reasons, underwriting assumptions, and score
   derivations. Explicitly call out an empty or partial live result; it is not a
   successful market-data refresh merely because the process exited zero.
7. Confirm that the only generated changes are intended derived artifacts in
   `data/state/` and `reports/`. Never commit raw responses, browser profiles,
   cookies, credentials, or debug HTML. Run `git diff --check` and rerun tests
   affected by any code or parser repair.
8. If and only if validation succeeded and live artifacts contain honestly
   labelled source outcomes, commit the intended code/documentation/data/report
   changes with a dated message. Push the current branch only when an existing
   authenticated remote is configured. Do not create credentials, rewrite
   history, force-push, or push directly to a protected branch. If repository
   instructions require a pull request, create it with the available repository
   tool after committing.
9. Finish with a Markdown summary containing: collection time; per-source
   record count and complete/partial/unsupported status; candidate and event
   counts; top candidates with warnings (not investment advice); changed file
   paths; commit and PR/push result; and every executed check prefixed with
   `✅`, `⚠️`, or `❌`. Distinguish environment limitations from code failures.

---

## Required local setup

Before enabling the schedule, an operator must place permission-reviewed live
URLs in a **local** configuration or update the checked-in configuration after
review. The repository deliberately ships with null live URLs, so an unchanged
checkout can validate fixtures but cannot produce a genuine live market
refresh. Authentication, when legitimately required by an official data
provider, must be injected by the task runner's secret store rather than YAML.

