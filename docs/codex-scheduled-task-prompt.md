# Prompt for the daily Codex Automation

Use the text below for a **Codex Automation**, with this repository as its working repository. Schedule for **07:00 Gulf Standard Time (03:00 UTC)** unless a different collection time is desired.

GitHub Actions is not the scheduler. The automation itself performs collection, analysis, validation, and Git-backed persistence.

---

Work in the `srobroek/propertyhunt-` repository and execute today's UAE residential property collection and investment analysis end to end.

1. Read `AGENTS.md` files if present, `README.md`, `docs/codex-daily-runbook.md`, `docs/source-status.md`, and `config/hunt.yaml`. Check `git status` before changing anything and preserve unrelated changes.

2. Use Python 3.12. Create or reuse `.venv`, then install:

   ```bash
   python -m pip install -e '.[dev,browser]'
   playwright install --with-deps chromium
   ```

3. Run deterministic validation before live access:

   ```bash
   ruff check src tests scripts
   mypy src/property_hunt
   pytest --cov=property_hunt --cov-report=term-missing
   property-hunt run --config config/hunt.yaml --fixture-dir tests/fixtures --output-dir /tmp/property-hunt-check --no-browser --verbose
   python scripts/validate_artifacts.py /tmp/property-hunt-check
   ```

   If any deterministic validation fails, stop the live run and report the exact failure.

4. Run the live collector:

   ```bash
   property-hunt run --config config/hunt.yaml --output-dir . --verbose
   ```

   Collection policy:
   - use direct HTTP first;
   - use Playwright for public pages that require JavaScript rendering;
   - use normal browser configuration and retries to reduce false bot detections;
   - do not automate CAPTCHA solving or bypass authentication/access controls;
   - when a source remains challenged, mark it partial and continue;
   - never fabricate records.

5. Inspect `reports/latest.json`. Treat source completeness as part of the result, not merely a diagnostic. If Property Finder, Bayut, or Dubizzle returns an implausibly low count relative to recent runs, investigate parser/source regressions before accepting the refresh.

6. The official current-year DLD export may remain disabled because its public form uses interactive CAPTCHA. For the strongest candidates, use public transaction evidence available through DLD-derived sources, Property Finder transaction pages, DXBinteract, and other credible sources to verify same-layout/same-building sale evidence. Clearly distinguish this agent-level research from records produced by the deterministic DLD adapter.

7. Analyse the candidate set as an investment underwriting exercise. Prioritize:
   - asking price and AED/sqft;
   - recent same-layout and same-building transactions;
   - discount/premium to credible comparables;
   - listing age, reductions, relistings, vacancy and duplicate-agent competition;
   - realistic long-term unfurnished and furnished rents;
   - STR only where genuinely supportable;
   - service charges, maintenance, vacancy and management costs;
   - net operating yield;
   - 3.99% / 25-year financing economics;
   - transaction and rental liquidity;
   - layout quality;
   - competing supply;
   - off-plan construction progress and realistic income-start date;
   - resale optionality.

8. For serious candidates calculate downside/base/upside scenarios and classify each as strong buy, attractive at a lower price, fair value, weak opportunity, or reject. State the maximum compelling purchase price, primary buy reason, primary reason not to buy, and largest unresolved diligence item.

9. Validate generated artifacts:

   ```bash
   python scripts/validate_artifacts.py .
   git diff --check
   git status --short
   ```

10. Persist successful state to GitHub. Stage only intended files under `data/`, `reports/`, and any necessary parser/code/documentation repairs. Do not commit secrets, cookies, raw browser profiles, CAPTCHA material, or debug HTML.

   ```bash
   git add data reports
   git add <any intentionally repaired code/docs>
   git commit -m "property hunt: $(date -u +%F)"
   git pull --rebase origin main
   git push origin HEAD:main
   ```

   Never force-push. If `main` cannot be updated safely, push a branch and report the conflict instead.

11. Return a compact daily report containing:
   - collection timestamp;
   - per-source status and record counts;
   - new/removed/reduced/relisted listing counts;
   - top ranked candidates;
   - transaction evidence for finalists;
   - LT unfurnished / LT furnished / STR underwriting where applicable;
   - financing-adjusted cash flow;
   - downside/base/upside return scenarios;
   - source/data-quality warnings;
   - commit SHA containing today's persisted state.

Put the investable conclusion first. Do not treat portal asking prices as market value.

---
