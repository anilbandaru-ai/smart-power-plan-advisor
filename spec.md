# Smart Power Plan Advisor — Implemented Specification

Status: current implementation baseline, API version `0.1.0`.
Reviewed: 2026-09-11.

This specification records the functionality present in the repository. Requirement IDs describe existing behavior, not proposed features. Future changes can reference these IDs and update their acceptance criteria alongside implementation and tests. All source paths below are relative to the application directory, [`smart-power-plan-advisor/`](smart-power-plan-advisor/).

## 1. Purpose and scope

The application is a local Texas electricity-plan comparison demo. A user enters a demo ZIP and supplies 12 monthly electricity-usage values. The application computes each eligible plan's monthly charges, ranks plans by annual cost, and saves a retrievable comparison.

All calculator catalog plans, rates, and delivery charges are synthetic. Comparison results are estimates in USD, not available electricity offers. Calculator pricing and explanations use deterministic Python logic with no API key. The separate document Q&A feature in section 10 uses OpenAI, Pinecone and LangGraph to explain indexed PDFs with citations.

## 2. User workflow

| ID | Implemented requirement |
| --- | --- |
| UI-01 | Serve the application at `/`, with a required ZIP input, a required usage textarea, and a Compare plans button. Explain that plans are fictional and taxes and switching fees are excluded. |
| UI-02 | Enable comparison for a five-digit ZIP when no comparison is pending. No delivery-area lookup or selection exists. |
| UI-03 | Prepopulate usage with `800, 750, 700, 850, 1100, 1400, 1600, 1500, 1200, 950, 750, 850`, labeled January through December. |
| UI-04 | Accept exactly 12 comma-separated usage values. Trim each token; require digits with an optional decimal portion of one to four digits, and a numeric value at most `99999999.9999`. Zero is allowed. Reject empty tokens, negative numbers, exponent notation, and incomplete decimals in the browser. |
| UI-05 | On invalid browser input, clear results and display `Enter 12 non-negative usage numbers with no more than four decimal places.` Do not send a comparison request. |
| UI-06 | Submit ZIP and monthly usage, disable the comparison button while pending and ignore responses made stale by input edits. |
| UI-07 | Render assumptions followed by ranked plan cards showing rank, name, annual cost, explanation, and source. Label the first plan `Lowest estimated cost among these demo plans`. |
| UI-08 | Provide an expandable monthly breakdown for each plan with month, kWh, energy, base fee, delivery, credit, and total columns. Display money using US-dollar currency formatting. Explain that credits are subtracted. |
| UI-09 | After creation, display `Comparison saved locally.`, replace the browser URL with `/?comparison=<id>`, and provide a link to that saved comparison. |
| UI-10 | Retrieve saved comparisons and restore ZIP and usage, without a coverage lookup. Legacy results without ZIP remain viewable and need ZIP for a new comparison. |
| UI-11 | Show a string API `detail` as an error message when available; otherwise show `Request failed (<status>). Check your inputs and try again.` Network errors are displayed using the thrown error's message. An empty area list displays `No demo delivery areas are available.` |
| UI-12 | Provide labeled form controls, usage help linked through `aria-describedby`, a polite live status region, table captions and column headers, visible keyboard focus styling, and horizontally scrollable tables. Link to API documentation and service health in the footer. |

The frontend uses plain HTML, CSS, and JavaScript. It has no frontend build step or npm dependencies. Dynamic result text is inserted with `textContent`.

## 3. Input and data contracts

### 3.1 Comparison request

```json
{
  "zip_code": "75201",
  "monthly_kwh": [800, 750, 700, 850, 1100, 1400, 1600, 1500, 1200, 950, 750, 850]
}
```

| ID | Implemented requirement |
| --- | --- |
| DATA-01 | Require a five-ASCII-digit ZIP string; comparison requests have no tdu field. Filter demo plans using the in-memory ZIP-to-plan-ID mapping. |
| DATA-02 | Require exactly 12 nonnegative decimal usage values, with Pydantic constraints `max_digits=12` and `decimal_places=4`. Numeric JSON values and decimal strings are supported. Non-finite values such as `NaN` are invalid. |
| DATA-03 | Reject additional top-level comparison-request fields. Backend validation is authoritative and is separate from the browser's token-format check. |

### 3.2 Plan model and catalog

`Plan` contains `id`, `name`, `energy_rate`, `base_fee`, `delivery_rate`, `delivery_fee`, `credit_threshold`, `credit_amount`, `term_months`, and `source`.

- Rates, fees, credit amounts, and non-null thresholds use the same nonnegative decimal constraints as usage.
- `credit_threshold` defaults to `null`, `credit_amount` to zero, and `term_months` to 12.
- Every shipped plan has a 12-month term. The model defaults to 12 but does not enforce a 12-only term; calculations always use the 12 supplied months.
- `JsonPlanSource` reads and validates `data/plans.json` each time `list_plans()` is called. No caching or remote retrieval is implemented.

The current catalog is:

| Plan ID | Name | Energy $/kWh | Base $/month | Delivery $/kWh | Delivery $/month | Credit |
| --- | --- | --- | --- | --- | --- | --- |
| `demo-oncor-simple` | Demo Simple | 0.105 | 0 | 0.05 | 5 | None |
| `demo-oncor-credit` | Demo Usage Credit | 0.13 | 5 | 0.05 | 5 | $40 at usage ≥ 1000 kWh |
| `demo-centerpoint-simple` | Demo Simple | 0.10 | 0 | 0.055 | 5 | None |
| `demo-centerpoint-credit` | Demo Usage Credit | 0.125 | 5 | 0.055 | 5 | $40 at usage ≥ 1000 kWh |

All four plans have source `Synthetic fixture: data/plans.json`.

### 3.3 Comparison result

| Field | Implemented content |
| --- | --- |
| `id` | Newly generated UUID4 string. |
| `created_at` | UTC timestamp serialized with Python `isoformat()`. |
| `data_mode` | `"demo"`. |
| `zip_code` | Requested ZIP string; null when reading legacy snapshots. |
| `assumptions` | Statements covering synthetic offers, USD and constant 12-month rates, excluded taxes/enrollment/early-termination fees, demo ZIP plan coverage without verified eligibility, and monthly line-item rounding. |
| `recommendations` | All matching plans, ordered by annual cost and then plan ID. |

Each recommendation contains `plan_id`, `name`, `term_months`, `annual_cost`, `monthly_costs`, `explanation`, and `source`. Each monthly entry contains `month` (1–12), `kwh`, `energy`, `base_fee`, `delivery`, `credit`, and `total`.

Decimal fields in comparison responses, including usage and money, are JSON strings. Monetary calculations produce cent-rounded values. The original usage is retained in each plan's monthly breakdown rather than in a separate top-level request field.

## 4. Pricing and ranking

Let `round_cents(x)` mean Python Decimal quantization to `0.01` using `ROUND_HALF_UP`. For each supplied month with usage `u`:

```text
energy   = round_cents(u × energy_rate)
delivery = round_cents(u × delivery_rate + delivery_fee)
base_fee = round_cents(plan.base_fee)
credit   = round_cents(credit_amount), if threshold is non-null and u ≥ threshold
           0.00, otherwise
total    = round_cents(energy + delivery + base_fee − credit)
annual_cost = sum(the 12 monthly totals)
```

| ID | Implemented requirement |
| --- | --- |
| PRICE-01 | Filter catalog by the requested ZIP's mapped plan IDs. Reject unmapped ZIPs or ZIPs with no available catalog matches. |
| PRICE-02 | Calculate each month independently using Decimal arithmetic. Do not substitute average usage for the monthly profile. |
| PRICE-03 | Apply the credit at an inclusive threshold. Round the energy amount, combined delivery amount, base fee, and credit separately before calculating the monthly total. |
| PRICE-04 | Sum monthly totals to get annual cost. Sort ascending by `(annual_cost, plan_id)` and return every eligible plan. |
| PRICE-05 | Generate template explanations stating the estimated 12-month cost, separate monthly calculation, included energy/base/delivery charges, and number of months with a positive credit. |

There is no minimum-total clamp, tax calculation, time-of-use calculation, variable-rate adjustment, or generalized provider billing-rule engine.

## 5. HTTP API

| ID | Method and route | Success behavior | Implemented error behavior |
| --- | --- | --- | --- |
| API-01 | `GET /api/health` | 200: `{"status":"ok","data_mode":"demo","storage":"sqlite"}` after checking storage and reading the catalog. | 503 with `detail: "Storage or plan source is unavailable"` if either check raises an exception. |
| API-02 | `GET /api/plans` | 200: data_mode and the validated plans list; no tdus or plan TDU fields. | No custom catalog-failure response. |
| API-03 | `POST /api/comparisons` | 201: calculate, save, and return a `ComparisonResult`. | 422 for invalid requests; comparison-service `ValueError` messages become string `detail` responses, including an unsupported area. |
| API-04 | `GET /api/comparisons/{comparison_id}` | 200: return the stored comparison without recalculation. | 422 for an invalid UUID; 404 with `detail: "Comparison not found"` for a valid UUID with no saved result. |
| API-05 | `GET /` and `/static/*` | Serve `frontend/index.html` and files from `frontend/`, respectively. | Standard framework file-serving behavior. |
| API-07 | Removed: `/api/service-areas` | No active endpoint. | 404. |
| API-06 | `GET /docs` | Expose FastAPI's interactive API documentation. | Standard framework behavior. |

FastAPI validation errors use the framework's structured `detail` format. Storage failures during save/retrieval and other uncaught errors have no custom application error mapping. The API does not return a successful creation response before storage succeeds.

## 6. Persistence and runtime

| ID | Implemented requirement |
| --- | --- |
| STORE-01 | Use SQLite at application-relative `.data/advisor.sqlite3` by default. Allow `ADVISOR_DB_PATH` to override the path; an explicit `create_app(db_path=...)` argument takes precedence. |
| STORE-02 | On application startup, create parent directories and initialize `comparisons (id TEXT PRIMARY KEY, payload TEXT NOT NULL)` if absent. Read the catalog during startup so invalid catalog data prevents normal startup. |
| STORE-03 | Insert the complete serialized comparison as a snapshot, keyed by its generated ID. Read and validate the saved JSON when retrieving it. Provide no update, deletion, or listing endpoint. |
| STORE-04 | Preserve saved comparisons across application restarts using the same database file. Retrieval does not recalculate against current rates, and the browser displays saved results even when current ZIP coverage cannot be resolved. |
| OPS-01 | For requests that return through the middleware, log HTTP method, URL path, response status, and elapsed milliseconds using the `uvicorn.error` logger. Log exceptions encountered by the readiness check. |
| OPS-02 | Use FastAPI and Uvicorn as runtime dependencies, with HTTPX added for API tests. Run locally on loopback as documented in the README. |

The health check verifies that the comparisons table can be queried and that the catalog can be read/validated. It does not perform a write probe or reject an empty catalog. No authentication or ownership checks exist; anyone with server access and a comparison ID can retrieve that comparison.

## 7. Architecture and source traceability

```text
Browser → FastAPI → comparison service → PlanSource → local JSON catalog
                 → ComparisonStore → SQLite snapshots
```

| Source | Responsibilities / requirement groups |
| --- | --- |
| `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` | Form, validation, API calls, saved-result loading, presentation and accessibility: UI-01–UI-12. |
| `backend/models.py` | Request, plan, monthly-cost and result schemas: DATA-01–DATA-03 and section 3. |
| `backend/services.py` | Monthly pricing, eligibility filtering, ranking, explanations and result metadata: PRICE-01–PRICE-05. |
| `backend/integrations.py`, `data/plans.json` | `PlanSource` protocol and synthetic JSON catalog. |
| `backend/api/main.py` | Routes, dependency assembly, startup validation and request logging: API-01–API-06, OPS-01. |
| `backend/storage.py` | SQLite initialization, snapshot insert/retrieval and read readiness: STORE-01–STORE-04. |
| `tests/test_advisor.py` | Existing pricing and API regression tests. |
| `requirements.txt`, `requirements-dev.txt`, `README.md` | Dependencies and local execution: OPS-02. |

`create_app` accepts an optional plan source and database path for substitution and testing. These are extension boundaries; real provider integrations and hosted storage are not implemented.

## 8. Acceptance scenarios and current verification

These scenarios describe the existing automated tests in `tests/test_advisor.py`:

| Scenario | Expected result | Existing test |
| --- | --- | --- |
| Oncor credit plan at 999, 1000, and 1001 kWh | Monthly totals are $189.82, $150.00, and $150.18 respectively. | `PricingTests.test_credit_threshold` |
| Oncor usage alternates 500 and 1500 kWh for 12 months | Simple ranks first at $1920.00; credit plan costs $2040.00; only Oncor plans appear. | `PricingTests.test_variable_months_are_not_replaced_with_average` |
| Load app, JavaScript, health and catalog | Root and JavaScript return 200, health reports `ok`, and catalog contains four plans. | `ApiTests.test_comparison_persists_across_app_restarts` |
| Submit ZIP 75201 with 1000 kWh in every month | Creation returns 201; first recommendation costs $1800.00 annually. | `ApiTests.test_comparison_persists_across_app_restarts` |
| Restart with the same database, then retrieve the saved ID | Retrieved JSON equals the original result. A missing all-zero UUID returns 404. | `ApiTests.test_comparison_persists_across_app_restarts` |
| Submit an obsolete tdu field, one usage value, negative usage, or `NaN` | Each request returns 422. | `ApiTests.test_rejects_invalid_or_unsupported_input` |

Other behaviors above were confirmed by source inspection, not by dedicated existing tests. Coverage gaps include browser interaction, rounding edge cases, tie-breaking, CenterPoint-specific expected bills, extra-field/precision limits, malformed UUIDs, readiness failures, and catalog changes after saving.

Validation commands, run from the application directory with dependencies installed:

```sh
python -m unittest discover -s tests -v
node --check frontend/app.js
```

The initial specification review could not run Python tests because the workspace virtual environment lacked `fastapi`. During the subsequent architecture review on 2026-09-10, the declared development dependencies were installed in an isolated temporary environment: all four existing test methods and the JavaScript syntax check passed. See the [architecture review](smart-power-plan-advisor/docs/architecture-review.md#7-verification-evidence) for environment versions, additional failure-path probes, and verification limits. The coverage gaps listed above remain; exploratory probes are not committed regression tests.

## 9. Not implemented

The current baseline includes only the demo in-memory ZIP plan mapping in section 12 and does not include live plan feeds, real tariff or eligibility verification, authoritative address/ZIP lookup, bill uploads, OCR, extraction of approved pricing rules into the calculator, Smart Meter Texas integration, interval usage, forecasts, usage scenarios, customer accounts, authentication, enrollment/switching, notifications, scheduled refresh, hosted application/database deployment, or production monitoring dashboards. PDF text extraction and cited RAG question answering are implemented separately as described below.

These exclusions are scope boundaries, not commitments for future releases. Planned behavior should be specified separately and incorporated into this baseline when implemented and verified.

## 10. Plan-document RAG — implemented

Requested and implemented 2026-09-11: Pinecone vector storage, OpenAI embeddings and LLM, and LangGraph orchestration. User confirmed cited PDF question answering alongside the existing deterministic demo comparison and creation of a new dedicated index. Extracted document content is not an approved pricing catalog and does not change `PlanSource` or calculated bills. User supplied both keys through an ignored local env file; no keys are stored in code or returned by the API.

| ID | Implemented requirement and acceptance criteria |
| --- | --- |
| RAG-01 | A CLI ingests text PDFs beneath application `data/`. Default discovery includes the existing 4Change EFL. Support an offline preview without keys; reject empty/scanned pages and overly large pages with a clear review-required error. No OCR or automatic external-link fetching. |
| RAG-02 | Use table-aware page-parent/child retrieval: detect ruled tables, serialize outer-table rows with cell boundaries and normalized cell whitespace, retain text outside tables, and fall back to line-preserving text when no table is detected. The complete page is the parent (maximum 1,800 tokens); children target 450 tokens with 60-token overlap, prefer line boundaries, and never cross pages/documents. Expand retrieved children to complete parents for generation. Deduplicate identical pages within each PDF, retaining the first page citation. Version the extraction/chunking policy. Acceptance includes preserving a wrapped termination-fee answer without interleaving its question text. |
| RAG-03 | Use `text-embedding-3-large`, explicitly requesting 3,072 dimensions; Pinecone dense index metric is cosine. Use the same embedding configuration at ingestion and query time. Reject incompatible index dimensions/metric. Configuration changes require reingestion. |
| RAG-04 | Use stable document/content/chunk IDs and a corpus-derived namespace beneath a configurable prefix. Upserts are idempotent for unchanged documents/configuration. Publish a local active manifest atomically only after successful upserts. Failed ingestion leaves the prior manifest intact. Older namespaces are not deleted automatically; Pinecone search visibility may lag writes. |
| RAG-05 | Keep source filename, document hash, original PDF page, parent/child text, parent ID and corpus version in metadata. Limit record metadata size. Serve cited local PDFs only through manifest IDs and verify their current hash/path. No arbitrary filesystem or remote URL access through this endpoint. |
| RAG-06 | Add `POST /api/knowledge/ask` accepting a trimmed question of 1–2,000 characters and optional document ID. A bounded LangGraph performs retrieval → deduplicated parent context → grounded generation → citation validation, or abstains when no suitable evidence exists. Retrieve at most 8 children and use at most 4 parent pages. No looping agent, tools, conversation persistence or background indexing. |
| RAG-07 | Default generation model is configurable `gpt-4.1-mini` through OpenAI Responses structured output, with provider timeouts and bounded retries. Return answer, abstention flag and source citations with exact supporting excerpts. Reject unknown citations or excerpts not present in supplied context, including factual explanations accompanying abstention. If the model supplies no evidence, return a fixed abstention message instead of unvalidated generated text. This is structural grounding validation, not a guarantee of factual entailment. Missing facts, such as unspecified TDU rates, must not be invented; document instructions are untrusted content. |
| RAG-08 | Add `GET /api/knowledge/status` reporting configured/indexed state and document summaries without secret values; this is local configuration status, not live provider readiness. Missing keys/index/manifest yields a safe 503 on ask, provider failures a safe 502, invalid input 422, and an unknown document filter 404. Existing comparison and health routes remain usable without RAG configuration. |
| RAG-09 | Add a separate document-question form with document filter, loading/error/abstention states, plain-text answers, and PDF page links plus source excerpts. Identify answers as document explanations, not live offers or calculated recommendations. No user API-key input in the browser. |
| RAG-10 | Add ignored local env-file conventions, a secret-free `.env.example`, optional RAG dependency files, and documented preview/index/ingest/run steps. Index creation is an explicit CLI action, never app startup behavior. Document that source text goes to OpenAI and Pinecone when ingestion/queries run. |
| RAG-11 | Offline tests cover duplicate-page handling, boundaries, stable IDs, oversized/scanned documents, index compatibility, manifest publication failures, namespace/document filtering, abstention, invalid citations, provider failures, API validation and existing comparison regression. Include EFL-specific evaluation questions for credit threshold, contract term, termination fee and missing delivery charges. Distinguish mocked tests from live retrieval/answer-quality evaluation. |

Initial chunk sizes and retrieval limits are engineering defaults exercised on the supplied EFL, not a general retrieval benchmark. The sample EFL says the bill credit applies at usage **greater than 999 kWh**, not a generalized `>= 1000` rule for fractional usage; preserve the source condition exactly. Live offer eligibility and current delivery tariffs are not established by document retrieval.

Implementation: `backend/knowledge/` contains configuration, extraction/chunking, providers, ingestion/CLI, LangGraph and API modules. `frontend/` contains the document-question form. See [RAG architecture and setup](smart-power-plan-advisor/docs/rag.md), [evaluation cases](smart-power-plan-advisor/docs/rag-evaluation.json), and `tests/test_knowledge.py` under the application directory. The original architecture review is a historical comparison-path baseline.

Verification on 2026-09-11: 20 automated Python tests passed (four calculator and 16 RAG tests); JavaScript syntax and DOM-stub checks passed. A new dedicated Pinecone index was created and two chunks from the unique EFL page were uploaded. Six live evaluation cases returned HTTP 200; the three supported factual questions returned page-1 citations, and missing-TDU/bill-total requests abstained. The injection case safely rejected the invented claim with valid evidence but returned `abstained=false` in the final run, a known model-label inconsistency (five of six exact expected-flag checks matched). A citation-validation failure can also cause conservative abstention rather than a detailed explanation. Full browser visual QA was unavailable because no connected browser was exposed. The local server's page, health and configured/indexed status endpoints were checked successfully.

## 11. In-memory ZIP lookup MVP - historical, superseded by section 12

Authorized 2026-09-11. This amendment supersedes UI-01/UI-02/UI-06/UI-10,
DATA-01, the request/result contracts, and the ZIP exclusion in section 9 where
specified below. Other behavior, including pricing and document Q&A, is unchanged.

- ZIP-01: Add a required five-ASCII-digit string ZIP input above Delivery area.
  An explicit lookup button queries GET /api/service-areas?zip_code=.... Return
  zip_code, sorted tdus and data_mode=demo. Invalid syntax returns 422; valid
  unmapped ZIPs return 200 with an empty list and a coverage message in the UI.
- ZIP-02: Use only a Python in-memory dictionary of demo mappings: 75201 and
  75001 -> Oncor; 77002 and 77007 -> CenterPoint. Do not persist lookup data, call
  external services, or claim verified eligibility. Support lists of candidates
  and intersect them with the current plan catalog. Multi-area behavior is tested
  with an injected fictional mapping, not a claimed real overlap.
- ZIP-03: Auto-select a sole candidate; require explicit selection for multiple
  candidates. For this MVP an unmapped ZIP cannot create a new comparison; explain
  limited demo coverage and show supported examples. Editing ZIP clears the area,
  results and saved URL. Ignore stale lookup/comparison/load responses after edits.
- ZIP-04: New comparison requests require zip_code; validate the selected TDU
  against its in-memory mapping before calculating. Reject missing/invalid ZIPs,
  unmapped ZIPs and area mismatches with 422. Retain existing monthly pricing.
- ZIP-05: Save ZIP with each new result in the existing SQLite JSON snapshot.
  Existing records without ZIP remain readable with zip_code=null and render
  without guessing a ZIP; request a ZIP before a new comparison. Restore ZIP,
  usage and area for new saved comparisons. Mapping changes cannot prevent viewing
  saved results, but new calculations must satisfy current mappings.
- ZIP-06: Add backend tests for malformed/missing/leading-zero/unmapped ZIPs,
  single/multiple candidates, catalog filtering, mismatched areas and legacy JSON.
  Add dependency-free DOM tests for lookup, area selection, stale responses and
  saved-result restoration. Run calculator tests, DOM tests and JS syntax checks.

Verification 2026-09-11: eight calculator/API Python tests passed (including four ZIP test methods); five dependency-free DOM-stub tests passed; JavaScript syntax check passed. Tests cover leading-zero preservation, malformed/unmapped ZIPs, multiple candidates, catalog filtering, mismatch rejection, legacy JSON, saved restoration, lookup failure and stale responses. No real-browser visual verification or live ZIP eligibility verification was performed.

## 12. ZIP-only comparisons - implemented

Authorized 2026-09-11. Supersedes delivery-area behavior in UI-01/UI-02/UI-06/UI-10,
DATA-01, PRICE-01, API-02/API-07 and section 11 (historical after this change).

- ZIP-01/ZIP-03 revised: ZIP and monthly usage are the only comparison inputs.
  Remove Delivery area, lookup button/status and lookup requests. A valid ZIP
  enables submission; unknown coverage is reported by the comparison endpoint.
  Keep stale-response protection and restore ZIP/usage for saved results.
- ZIP-02 revised: Replace utility-based mapping with an in-memory ZIP-to-plan-ID
  mapping in integrations.py. Preserve the existing four ZIPs and eligible demo
  plans. Remove service_areas.py, all TDU model/catalog fields, area choices and
  /api/service-areas. /api/plans returns data_mode and plans without tdus.
- ZIP-04 revised: POST comparisons accepts only zip_code and monthly_kwh; reject
  obsolete tdu input as an extra field. Filter by mapped plan IDs. Invalid or
  unsupported ZIP and empty matched catalog return 422. Prices are unchanged.
- ZIP-05 revised: New responses contain ZIP, no tdu. Older snapshots containing
  tdu or lacking ZIP remain readable without recalculation; unknown legacy fields
  are ignored and missing ZIP is null. No old database files are rewritten.
- ZIP-06 revised: Replace area lookup/selection tests with ZIP-only filtering,
  obsolete-route/field removal, legacy snapshot and UI submission/restore/stale
  response tests. Update current README/architecture guidance and specification.

Verification: eight calculator/API tests and five DOM-stub UI tests passed; JavaScript syntax check passed. Covers ZIP-only filtering/submission, removed endpoint and fields, invalid/unsupported ZIPs, missing catalog entries, legacy snapshot loading and stale responses. No full browser visual test was performed.
