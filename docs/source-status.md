# Source reconnaissance and operating status

Status is deliberately conservative and must be rechecked when portal markup or access behavior changes.

| Source | Current method | Browser fallback | Default | Limitation |
|---|---|---|---|---|
| Property Finder | Public Dubai sale search pages + detail-page JSON-LD; pagination | Playwright | Enabled | Markup can change; coverage depends on configured page depth |
| Bayut | Public Dubai apartment search pages; discover detail links; parse detail JSON-LD | Playwright | Enabled | Markup/detail schema can change; coverage depends on configured page depth |
| Dubizzle | Public Dubai apartment search pages; discover detail links; parse detail JSON-LD | Playwright | Enabled | Markup/detail schema can change; coverage depends on configured page depth |
| Dubai Land Department | Deterministic CSV parser for approved exports | No | Disabled | Current-year public open-data form exposes an interactive CAPTCHA; no automated CAPTCHA solving is implemented |
| DXBInteract | No stable bulk adapter currently encoded | No | Disabled | Useful as secondary transaction evidence during candidate diligence |
| Emirates Auction | Adapter scaffold only | No | Disabled | Needs source-specific reconnaissance and parser before enabling |

## Operating rules

- Direct HTTP is attempted first.
- JavaScript-rendered public pages may use Playwright.
- CAPTCHA/access-challenge pages are reported as partial rather than bypassed.
- Failed sources produce no invented rows.
- A run must disclose incomplete source coverage in diagnostics.
- Search-page depth is a sampling boundary, not proof that every active portal listing was processed.

## Important current limitation

The repository is operational as a listing-collection/history pipeline, but **transaction coverage is not yet fully autonomous** because the primary DLD current-year export path requires an interactive CAPTCHA. As a result, valuation scores should not be treated as transaction-verified unless a transaction dataset has been supplied or candidate-level transaction research has been performed separately.
