# Source reconnaissance and operating status

Status is deliberately conservative and must be rechecked when portal markup, access controls, or official data surfaces change.

| Source | Current method | Browser fallback | Default | Current limitation |
|---|---|---|---|---|
| Property Finder | Public Dubai sale search/detail pages plus published sitemap fallback | nodriver, then Playwright | Enabled | Search/detail access can be challenged; zero-row partial runs preserve the last valid listing snapshot |
| Bayut | Public Dubai apartment search/detail pages plus published sitemap fallback | nodriver, then Playwright | Enabled | Current GitHub-runner requests frequently hit access challenges |
| Dubizzle | Public Dubai apartment search pages, rendered cards and detail parsing | nodriver, then Playwright | Enabled | Current rendered search page may expose no parseable cards/detail links |
| Dubai Land Department - Transactions | Official DLD public real-estate-data page or configured official CSV/export | No CAPTCHA bypass | Enabled | Landing page is reachable, but current transaction rows require a date query and DLD CAPTCHA before CSV results are populated |
| Dubai Land Department - Rents | Official DLD public real-estate-data page or configured official CSV/export | No CAPTCHA bypass | Enabled | Current Ejari rows require a date query and DLD CAPTCHA before CSV results are populated |
| Dubai Land Department - Projects | Official DLD project/open-data surfaces or configured official CSV/export | No CAPTCHA bypass | Enabled | Public project datasets/status pages are query-driven; bulk rows are not treated as available unless an actual CSV/export is returned |
| DLD Unit/Building/Land/Broker/Developer/Valuation datasets | Documented official open-data schemas; adapters/registry ingestion planned | No CAPTCHA bypass | Not yet active as persisted datasets | The live DLD page shows query controls/CAPTCHA for these result sets as well; CSV buttons alone are not evidence of an unconditional bulk export |
| Data Dubai | Known successor/open-data catalogue | n/a | Disabled | Machine-access/auth model not yet verified; do not duplicate DLD datasets until resource-level access and schema differences are confirmed |
| Legacy Dubai Pulse | OAuth/API/CSV implementation retained for compatibility | n/a | Disabled | Treated as legacy/deprecated unless Data Dubai does not replace a needed dataset |
| DXBinteract aggregate reports | Public market-report HTML parser | nodriver | Enabled | Suitable for area/market transaction and rental context, not a substitute for exact DLD rows |
| DXBinteract authenticated exploration | GitHub Actions secrets + sanitized nodriver probe | nodriver | Probe only | GitHub-hosted runner may hit Cloudflare Turnstile before login; credentials are not logged or persisted |
| Emirates Auction | Public property inventory/detail parser | nodriver | Enabled | Public inventory structure may expose no detail links to the GitHub runner; zero rows are reported as partial |
| DLD/RERA Mollak service charges | Candidate-level web verification / future adapter | n/a | Not yet deterministic | Important for net-yield underwriting; add a deterministic adapter when a stable public resource is identified |
| DLD Project Status / Mashrooi | Candidate-level project progress verification / future adapter | n/a | Not yet deterministic | Use for completion %, inspections and schedule-risk diligence on shortlisted/off-plan units |

## Operating rules

- Direct HTTP is attempted first where appropriate.
- JavaScript-rendered public pages may use nodriver, with Playwright as fallback for ordinary rendering.
- CAPTCHA, Turnstile and access-challenge pages are detected and reported as partial/query-gated; the collector does not solve or bypass them.
- Failed or gated sources produce no invented rows.
- A run must disclose incomplete source coverage in `reports/latest.json` diagnostics.
- When a current listing source returns zero rows with partial diagnostics, the previous valid listing snapshot is preserved and removal events are suppressed.
- Search-page depth is a sampling boundary, not proof that every active portal listing was processed.
- DLD/RERA evidence has priority over secondary sources when actual official rows are available.
- DXBinteract can be used as secondary registered-sales/rental/context evidence during candidate diligence, including area/building comparisons where publicly retrievable.

## Persisted evidence schema

The canonical typed schemas are defined in `src/property_hunt/models.py`.

Current state files under `data/state/` include:

- `listings.parquet` - current effective sale-listing snapshot.
- `transactions.parquet` - normalized transaction evidence.
- `rents.parquet` - normalized registered/live rent evidence when collected.
- `projects.parquet` - normalized project/construction evidence when collected.
- `auctions.parquet` - Emirates Auction/distress evidence.
- `market_metrics.parquet` - aggregate market evidence such as DXBinteract reports.
- `registry.parquet` - building/unit/developer/other registry evidence when available.
- `observations.parquet` - historical listing observations.
- `first_seen.parquet` - immutable first-seen listing records.
- `events.parquet` - listing add/remove/change events.

`reports/latest.json` is the primary run manifest. It records current collection counts, snapshot-preservation flags, per-source diagnostics, exclusions, candidates and warnings.

## Current investment-analysis implication

The deterministic pipeline can persist listings, source diagnostics, market context and typed evidence, but **fresh transaction/rent coverage is not guaranteed on every run**. DLD current result sets are query/CAPTCHA-gated and the GitHub-hosted DXBinteract authenticated probe may be stopped by Cloudflare before login. Candidate-level transaction/rent verification therefore remains part of the scheduled ChatGPT/web-enrichment layer whenever the persisted `transactions.parquet` or `rents.parquet` does not contain fresh relevant rows.
