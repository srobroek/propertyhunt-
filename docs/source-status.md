# Source reconnaissance and operating status

Status is deliberately conservative and must be rechecked before production use. The pipeline does not bypass authentication, bot controls, robots directives, or terms.

| Source | Evidence/access method | Authentication / robots / terms | Reliability | Browser | Limitation |
|---|---|---|---|---|---|
| Property Finder | Public listing pages may expose schema.org JSON-LD; parser is fixture-tested | No login used; operator must review current robots and terms before enabling a URL | Partial: markup can change | Optional Playwright rendering; never bypass challenges | No discovery endpoint is assumed; returns unsupported without configured URL |
| Bayut | No stable permission-verified endpoint encoded | Terms/robots must be reviewed; no circumvention | Unsupported | Not used | Explicit diagnostic, zero fabricated records |
| dubizzle | No stable permission-verified endpoint encoded | Terms/robots and account requirements must be reviewed | Unsupported | Not used | Explicit diagnostic, zero fabricated records |
| Dubai Land Department | Adapter accepts an operator-supplied approved official open-data CSV export | Use only under the portal/export licence; no credentials stored | Functional deterministic CSV parser | No | URL intentionally unset because portal links and schemas can change |
| DXBInteract | No permission-verified public bulk endpoint encoded | Third-party terms apply | Unsupported | Not used | Explicit diagnostic, zero fabricated records |
| Emirates Auction | No stable permission-verified endpoint encoded | Auction terms and robots apply | Unsupported | Not used | Explicit diagnostic, zero fabricated records |

“Functional” describes parser behavior, not a grant of data rights. Operators remain responsible for permission, rate limits, and current terms.
