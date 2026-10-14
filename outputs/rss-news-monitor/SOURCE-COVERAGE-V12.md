# V12 source coverage and collector audit — 2026-09-28 KST

Scope: read-only live HTTP probes, parser repairs, deterministic source discovery, and source-body caching. No full production collection, historical queue reset, or Telegram send was performed by this audit. Existing DB/history/receipts/credentials are preserved. Pre-change owned files are in `work/v12-upgrade/baseline`.

## Confirmed gaps and repairs

| Route | Before | V12 change | Live evidence |
| --- | --- | --- | --- |
| US federal permitting negotiations | Named transmission projects but no broad Congress/White House legislative discovery | Three independent public Google News RSS searches: federal energy permitting news, official permitting reform/deal sources, and wind/solar Pentagon/DoD/Department of War approvals | 28 / 7 / 6 items. The defense-approval query found the exact missed Bloomberg title, `Trump Offering Solar Projects for Permitting Deal, Senator Says` |
| White House | No dedicated executive-action route | Official `/news/` page, verified dated article paths, industry/energy/NEPA/permitting and signed-bill title filter | 10 real article links before keyword filter; 1 matched item during test |
| Hitachi Energy | JavaScript news listing returned zero article links | Official public JSON URL extracted from the page's `data-props:url`; dedicated parser validates schema, same host, public status, article path, date, and duplicate URLs | 12 public press releases, including Sep 24 Enedis EUR350m agreements; original body usable, 4,689 characters |
| Siemens Energy | `/press-releases.html` returned 33 navigation links and falsely appeared covered | Verified `/press.html` plus `/press-releases/` article filter | 6 press-release URLs, no products/service navigation |
| CAISO | 58 links, many navigation/category links | `/about/news/` paths; exclude topic/archive/blog directories while retaining dated news updates outside news-releases | 27 article/news update URLs |
| T&D World | 44 links including category pages; unnecessary original/date attempts for those pages | Require article/news/blog/podcast/whitepaper numeric content URL | 36 actual content links; original exact-time resolver retained |

The federal discovery sources are explicitly `discovery=true`, `primary=false`. A search result is discovery evidence, not verified direct access to its publisher or an enacted law. Candidates still require original/official alternative validation, current-publication eligibility, industrial relevance, novelty guard, receipt, and ACK. Discovery of the old Bloomberg example does not authorize sending it as current news.

The official query deliberately uses `permitting reform`, `permitting deal`, and `energy permitting` phrases. A broader NEPA keyword probe produced the 100-result feed limit, including historical guidance/library pages; that noisy query was not installed. Existing DOE/FERC direct sources and the White House title route retain NEPA executive-action discovery. Google can return stale search records despite `when:7d`; the local date/freshness gates remain authoritative.

## Source availability retained, not overstated

- Utility Dive RSS: 10 dated items; individual original probe returned HTTP 403. RSS health does not mean full-text access succeeded.
- PJM Inside Lines: 10 dated items; ISO-NE Newswire: 10 dated items.
- MISO public media API: 47 dated items; NYISO official press page: 20 article links; SPP: 74 article links.
- ERCOT direct news remained HTTP 403. All seven individual ISO/RTO discovery feeds remain configured; discovery is not a claim of direct-source repair.
- GEV direct releases: 10 items. GEV, Siemens Energy, Hitachi, Eaton, and Schneider order-discovery queries each returned items (100/58/42/100/55 in the probe). Schneider official-release discovery returned 1 item.
- Eaton direct yearly news listing timed out; Schneider official page and Senate ENR/EPW direct pages returned HTTP 403. No unverified replacement direct endpoint was added for them. Official-targeted discovery and existing SEC routes remain separate fallbacks.
- No guarantee of instant publisher indexing, absence of paywalls, or zero missed articles is implied by these tests.

### Follow-up on the first V12 full run's 8 reported gaps

The first full run reported 139/147 successful routes. Additional read-only checks distinguish broken duplicate routes from missing coverage:

| Reported gap | Verified alternate route / remaining limitation |
| --- | --- |
| nVent issuer SEC RSS: no entries | SEC NVT Company Filings returns 53 items directly from SEC; issuer's empty RSS remains an explicit gap |
| Vertiv issuer SEC RSS: no entries | SEC VRT Company Filings returns 63 items directly from SEC; issuer's empty RSS remains an explicit gap |
| GridStatus Insights: no links | Page is now an application shell. Existing GridStatus Exports RSS returns 15 analytical articles; this is not proof that every dashboard insight is covered |
| Fluence media room: no links matching prior article path | Official media room now links to an IR news-events directory; IR direct access timed out / returned403. SEC FLNC Company Filings returns56. Added `Fluence Industry News Discovery`, live28 results including the battery supply agreement and COO change; primary=false, discovery=true |
| FERC direct news:403 | Existing official-targeted search returned7 but includes navigation/library pages. Added `FERC Industry News Discovery`, live5 substantive results including ISO-NE ROE/refunds, Oklo/PJM interconnection, and PJM price cap. Direct403 remains visible |
| ERCOT direct news:403 | Existing ISO RTO Keyword ERCOT returns11 results including765kV transmission project coverage |
| AEMO / NESO direct:403 | Non-core overseas direct gaps retained. No broad noisy search added to fill counts |

The two new fallbacks increase configured source definitions from146 to148 (the full-run count also includes OpenDART when configured); this audit did not invoke a full collection to manufacture an updated coverage ratio. A Fluence official-domain search was also tested and returned0, so it was not installed or described as restored access. Empty duplicated issuer feeds were not relabeled as successful and existing source definitions/history were not deleted.

## False-success, date precision, and token repairs

1. RSS must be RSS/Atom/RDF, with a proper RSS channel and valid article title/URL entries. HTML/login bodies and malformed/empty official feeds are coverage failures. Legitimate empty discovery and zero matches after configured filters remain explicit `discovery_no_results` / `filtered_no_matches`, not invented articles.
2. `source_freshness` covers every fetched source and includes `coverage_state`, raw count, and direct/discovery distinction. Latest recorded publication time remains separate from current fetch success.
3. Collector rows and snapshots carry `publication_precision` (`exact`, `date`, `unknown`). HTML title date and Hitachi timezone-less API dates are day-level; they must not masquerade as exact midnight publication. Existing history defaults to `unknown` until positively observed. Original metadata lacking a timezone preserves its raw value and reports only its stated date.
4. Google News title/summary normalization removes the exact RSS `<source>` publisher suffix and pure linked-headline/publisher description. Publisher-brand/domain label rotation can no longer manufacture repeated article revisions. Actual additional summary facts are retained.
5. Source-body cache prefers semantic `article` / `main`, drops duplicate responsive paragraphs and unrelated sidebars, and extracts valid Article/NewsArticle JSON-LD publication/body metadata. Generic WebPage modification dates are not original publication evidence. Cache version 2 re-fetches old extraction once.
6. Collector commits schema work before network requests, uses a 30-second SQLite timeout, and completes T&D parallel date requests before writing the results. This allows delivery ACKs during long source requests. Fast polling prefers `runtime-v12.json` and falls back to V11 for compatibility.

## Validation

- `test_collector` + `test_v11_source_cache`: 86 tests passed after final collector/cache changes.
- `test_company_scope`: 20 tests passed.
- Live probes used the same configured HTTP/parsing paths but never called production `collect` or publish.
- Regression coverage includes Google publisher rename invariance, actual summary-fact retention, malformed/empty/filtered feeds, navigation rejection, Hitachi public-only records, date precision, JSON-LD date precedence, semantic-body extraction, and cache/network safety.
