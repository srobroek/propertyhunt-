# Property Hunt automation

`daily.yml` is the production scheduler for deterministic property data collection.

- Schedule: 03:00 UTC / 07:00 UAE daily
- Runner: `ubuntu-latest`
- Python: 3.12
- Browser fallback: Playwright Chromium
- Validation: ruff, pytest, fixture pipeline, artifact validation
- Persistence: generated `data/` and `reports/` are committed back to `main`
- Manual testing: workflow can also be run with `workflow_dispatch`

The downstream ChatGPT `Property Hunt Analysis` scheduled task runs after collection and reviews the persisted GitHub output.
