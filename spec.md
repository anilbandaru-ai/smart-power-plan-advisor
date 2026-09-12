# Smart Power Plan Advisor — Implemented Specification

Status: current implementation baseline, API version `0.1.0`.
Reviewed: 2026-09-11.

This specification records the functionality present in the repository. Requirement IDs describe existing behavior unless explicitly marked planned or deferred. Future changes can reference these IDs and update their acceptance criteria alongside implementation and tests. All source paths below are relative to the application directory, [`smart-power-plan-advisor/`](smart-power-plan-advisor/).

## 1. Purpose and scope

The application is a local Texas electricity-plan comparison demo. A user enters a five-digit ZIP code and supplies 12 monthly electricity-usage values. The application computes each eligible plan's monthly charges, ranks plans by annual cost, and saves a retrievable comparison.

The legacy demo calculator catalog is synthetic. The browser now defaults to the separately ingested PDF catalog described in section 12; PDF rates are document-date estimates, not live offers. Comparison results are estimates in USD, not available electricity offers. Calculator pricing and explanations use deterministic Python logic with no API key. The separate document Q&A feature in section 10 uses OpenAI, Pinecone and LangGraph to explain indexed PDFs with citations.

## 2. User workflow

| ID | Implemented requirement |
| --- | --- |
| UI-01 | Serve the application at `/`, with a five-digit ZIP input, a required usage textarea, and a Compare plans button. Explain that plans are fictional and taxes and switching fees are excluded. |
| UI-02 | Enable comparison when the ZIP contains five ASCII digits. No catalog/coverage request is needed before submission. ZIP or usage edits clear results and invalidate in-flight responses. |
| UI-03 | Prepopulate usage with `800, 750, 700, 850, 1100, 1400, 1600, 1500, 1200, 950, 750, 850`, labeled January through December. |
| UI-04 | Accept exactly 12 comma-separated usage values. Trim each token; require digits with an optional decimal portion of one to four digits, and a numeric value at most `99999999.9999`. Zero is allowed. Reject empty tokens, negative numbers, exponent notation, and incomplete decimals in the browser. |
| UI-05 | On invalid browser input, clear results and display `Enter 12 non-negative usage numbers with no more than four decimal places.` Do not send a comparison request. |
| UI-06 | On valid submission, disable the button, clear previous results, display `Comparing plans…`, and POST the ZIP code and usage values as decimal strings. Re-enable the button after success or failure. |
| UI-07 | Render assumptions followed by ranked plan cards showing rank, name, annual cost, explanation, and source. Label the first plan `Lowest estimated cost among these demo plans`. |
| UI-08 | Provide an expandable monthly breakdown for each plan with month, kWh, energy, base fee, delivery, credit, and total columns. Display money using US-dollar currency formatting. Explain that credits are subtracted. |
| UI-09 | After creation, display `Comparison saved locally.`, replace the browser URL with `/?comparison=<id>`, and provide a link to that saved comparison. |
| UI-10 | On initial load with a nonempty `comparison` query parameter, retrieve and render the saved result directly, without a catalog request. Restore ZIP and usage; legacy snapshots without ZIP remain readable but require ZIP entry before another comparison. Ignore responses made stale by edits. |
| UI-11 | Show a string API `detail` as an error message when available; otherwise show `Request failed (<status>). Check your inputs and try again.` Network errors are displayed using the thrown error's message. |
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
| DATA-01 | Require `zip_code` to be exactly five ASCII digits as a string. The in-memory ZIP-to-plan-ID map supports 75201, 75001, 77002 and 77007; it does not verify actual address eligibility. |
| DATA-02 | Require exactly 12 nonnegative decimal usage values, with Pydantic constraints `max_digits=12` and `decimal_places=4`. Numeric JSON values and decimal strings are supported. Non-finite values such as `NaN` are invalid. |
| DATA-03 | Reject additional top-level comparison-request fields. Backend validation is authoritative and is separate from the browser's token-format check. |

### 3.2 Plan model and catalog

`Plan` contains `id`, `name`, `energy_rate`, `base_fee`, `delivery_rate`, `delivery_fee`, `credit_threshold`, `credit_amount`, `term_months`, and `source`.

- Rates, fees, credit amounts, and non-null thresholds use the same nonnegative decimal constraints as usage.
- `credit_threshold` defaults to `null`, `credit_amount` to zero, and `term_months` to 12.
- Every shipped plan has a 12-month term. The model defaults to 12 but does not enforce a 12-only term; calculations always use the 12 supplied months.
- `JsonPlanSource` reads and validates `data/plans.json` each time `list_plans()` is called. No caching or remote retrieval is implemented.

The current catalog is listed below. “Area” describes the fixture naming only; there is no TDU field in the Plan model. ZIPs 75201/75001 map to the two oncor plan IDs and 77002/77007 to the two centerpoint plan IDs:

| Plan ID | Name | Area | Energy $/kWh | Base $/month | Delivery $/kWh | Delivery $/month | Credit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo-oncor-simple` | Demo Simple | Oncor | 0.105 | 0 | 0.05 | 5 | None |
| `demo-oncor-credit` | Demo Usage Credit | Oncor | 0.13 | 5 | 0.05 | 5 | $40 at usage ≥ 1000 kWh |
| `demo-centerpoint-simple` | Demo Simple | CenterPoint | 0.10 | 0 | 0.055 | 5 | None |
| `demo-centerpoint-credit` | Demo Usage Credit | CenterPoint | 0.125 | 5 | 0.055 | 5 | $40 at usage ≥ 1000 kWh |

All four plans have source `Synthetic fixture: data/plans.json`.

### 3.3 Comparison result

| Field | Implemented content |
| --- | --- |
| `id` | Newly generated UUID4 string. |
| `created_at` | UTC timestamp serialized with Python `isoformat()`. |
| `data_mode` | `"demo"`. |
| `zip_code` | Requested ZIP; null for legacy snapshots. No TDU response field. |
| `assumptions` | Statements covering synthetic offers, USD and constant 12-month rates, excluded taxes/enrollment/early-termination fees, synthetic ZIP coverage, and monthly line-item rounding. |
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
| PRICE-01 | Filter catalog plans by the plan IDs mapped to the supplied ZIP. Unknown ZIPs raise `This ZIP code is not covered by the demo lookup.`; no matching catalog plans raises `No demo plans are available for this ZIP code.` |
| PRICE-02 | Calculate each month independently using Decimal arithmetic. Do not substitute average usage for the monthly profile. |
| PRICE-03 | Apply the credit at an inclusive threshold. Round the energy amount, combined delivery amount, base fee, and credit separately before calculating the monthly total. |
| PRICE-04 | Sum monthly totals to get annual cost. Sort ascending by `(annual_cost, plan_id)` and return every eligible plan. |
| PRICE-05 | Generate template explanations stating the estimated 12-month cost, separate monthly calculation, included energy/base/delivery charges, and number of months with a positive credit. |

There is no minimum-total clamp, tax calculation, time-of-use calculation, variable-rate adjustment, or generalized provider billing-rule engine.

## 5. HTTP API

| ID | Method and route | Success behavior | Implemented error behavior |
| --- | --- | --- | --- |
| API-01 | `GET /api/health` | 200: `{"status":"ok","data_mode":"demo","storage":"sqlite"}` after checking storage and reading the catalog. | 503 with `detail: "Storage or plan source is unavailable"` if either check raises an exception. |
| API-02 | `GET /api/plans` | 200: `data_mode` and the full validated `plans` list. No TDU list or service-area endpoint. | No custom catalog-failure response is implemented for this endpoint. |
| API-03 | `POST /api/comparisons` | 201: calculate, save, and return a `ComparisonResult`. | 422 for invalid requests; comparison-service `ValueError` messages become string `detail` responses, including an unsupported ZIP. |
| API-04 | `GET /api/comparisons/{comparison_id}` | 200: return the stored comparison without recalculation. | 422 for an invalid UUID; 404 with `detail: "Comparison not found"` for a valid UUID with no saved result. |
| API-05 | `GET /` and `/static/*` | Serve `frontend/index.html` and files from `frontend/`, respectively. | Standard framework file-serving behavior. |
| API-06 | `GET /docs` | Expose FastAPI's interactive API documentation. | Standard framework behavior. |

FastAPI validation errors use the framework's structured `detail` format. Storage failures during save/retrieval and other uncaught errors have no custom application error mapping. The API does not return a successful creation response before storage succeeds.

## 6. Persistence and runtime

| ID | Implemented requirement |
| --- | --- |
| STORE-01 | Use SQLite at application-relative `.data/advisor.sqlite3` by default. Allow `ADVISOR_DB_PATH` to override the path; an explicit `create_app(db_path=...)` argument takes precedence. |
| STORE-02 | On application startup, create parent directories and initialize `comparisons (id TEXT PRIMARY KEY, payload TEXT NOT NULL)` if absent. Read the catalog during startup so invalid catalog data prevents normal startup. |
| STORE-03 | Insert the complete serialized comparison as a snapshot, keyed by its generated ID. Read and validate the saved JSON when retrieving it. Provide no update, deletion, or listing endpoint. |
| STORE-04 | Preserve saved comparisons across application restarts using the same database file. Retrieval does not recalculate against current rates, and the browser retrieves a saved comparison without a catalog dependency. |
| OPS-01 | For requests that return through the middleware, log HTTP method, URL path, response status, and elapsed milliseconds using the `uvicorn.error` logger. Log exceptions encountered by the readiness check. |
| OPS-02 | Use FastAPI and Uvicorn as runtime dependencies, with HTTPX added for API tests. Run locally on loopback as documented in the README. |

The health check verifies that the comparisons table can be queried and that the catalog can be read/validated. It does not perform a write probe or reject an empty catalog. No authentication or ownership checks exist for comparison snapshots; anyone with server access and a comparison ID can retrieve that comparison. Agent threads separately require an opaque session capability.

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
| Submit Oncor with 1000 kWh in every month | Creation returns 201; first recommendation costs $1800.00 annually. | `ApiTests.test_comparison_persists_across_app_restarts` |
| Restart with the same database, then retrieve the saved ID | Retrieved JSON equals the original result. A missing all-zero UUID returns 404. | `ApiTests.test_comparison_persists_across_app_restarts` |
| Submit an unknown area, one usage value, negative usage, or `NaN` | Each request returns 422. | `ApiTests.test_rejects_invalid_or_unsupported_input` |

Other behaviors above were confirmed by source inspection, not by dedicated existing tests. Coverage gaps include browser interaction, rounding edge cases, tie-breaking, CenterPoint-specific expected bills, extra-field/precision limits, malformed UUIDs, readiness failures, and catalog changes after saving.

Validation commands, run from the application directory with dependencies installed:

```sh
python -m unittest discover -s tests -v
node --check frontend/app.js
```

The initial specification review could not run Python tests because the workspace virtual environment lacked `fastapi`. During the subsequent architecture review on 2026-09-10, the declared development dependencies were installed in an isolated temporary environment: all four existing test methods and the JavaScript syntax check passed. See the [architecture review](smart-power-plan-advisor/docs/architecture-review.md#7-verification-evidence) for environment versions, additional failure-path probes, and verification limits. The coverage gaps listed above remain; exploratory probes are not committed regression tests.

## 9. Not implemented

The current baseline does not include live plan feeds, real tariff or eligibility verification, live address/ZIP eligibility lookup, bill uploads, OCR, extraction of approved pricing rules into the calculator, Smart Meter Texas integration, interval usage, forecasts, usage scenarios, customer accounts, authentication, enrollment/switching, notifications, scheduled refresh, hosted application/database deployment, or production monitoring dashboards. PDF text extraction and cited RAG question answering are implemented separately as described below.

These exclusions are scope boundaries, not commitments for future releases. Planned behavior should be specified separately and incorporated into this baseline when implemented and verified.

## 10. Plan-document RAG — implemented

Requested and implemented 2026-09-11: Pinecone vector storage, OpenAI embeddings and LLM, and LangGraph orchestration. User confirmed cited PDF question answering alongside the existing deterministic demo comparison and creation of a new dedicated index. RAG-retrieved text alone is not an approved pricing catalog and does not change the demo `PlanSource`. Section 12 separately introduces validated structured PDF calculations. User supplied both keys through an ignored local env file; no keys are stored in code or returned by the API.

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

## 11. Document ReAct agent — first increment implemented; broader proposal retained

Planning request dated 2026-09-11. The user confirmed **document questions only** and **in-memory conversations**. The table below records the broader proposal. Sections 11.1–11.2 identify the delivered subset and deferred work; section 10 remains implemented. The detailed [architecture review and implementation plan](smart-power-plan-advisor/docs/react-agent-plan.md) defines phases, API contracts, limits and acceptance scenarios. The first end-to-end implementation follows the explicit scope adjustments below.

| ID | Planned requirement and acceptance criteria |
| --- | --- |
| AGENT-01 | Build an explicit LangGraph `StateGraph` with message state using `add_messages`, a tool-bound OpenAI model, reason/action nodes, matching `ToolMessage` observations and conditional routing. Demonstrate a bounded second retrieval after observing insufficient first-search evidence. Do not substitute a prebuilt agent factory for the requested fundamentals. |
| AGENT-02 | Support document Q&A and contextual follow-ups only. Allowlist indexed-document discovery, evidence search and user clarification tools. Do not expose pricing, enrollment, arbitrary filesystem/network access, ingestion or index administration. Preserve the existing calculator and single-question RAG contracts. |
| AGENT-03 | Reuse the existing embedding, Pinecone and chunking contracts. Discover only active-manifest documents; apply corpus, document hash, page and optional document-scope checks. Use stable evidence identities across searches. Each factual turn must retrieve its own supporting evidence; prior conversation is not a source of truth. |
| AGENT-04 | Return structured, source-linked claims with exact supporting excerpts and PDF page links, validated before presentation. Preserve source units and qualifiers. Allow at most one citation repair; unsupported output ends with a fixed insufficient-evidence response. Structural validation is not a guarantee of semantic correctness. |
| AGENT-05 | Compile an application-scoped graph with `InMemorySaver` and bounded isolated sessions. Retain conversations and interruptions only within one running process; use one worker, a 30-minute inactivity expiry, at most 100 active threads and 20 user turns per thread. Clear/reset deletes session checkpoints; restart/expiry requires a new conversation. Keep secrets and provider clients outside checkpoint state. |
| AGENT-06 | Clarify ambiguous document questions using a dedicated `interrupt` node and resume with `Command` on the same thread. Validate pending interruption IDs, retain consumed budgets and handle node replay safely. Serialize each thread and deduplicate completed requests by request ID. Bind conversation access to an opaque browser session capability; this is not customer authentication. |
| AGENT-07 | Initially limit each logical turn to six model calls including finalization/repair, eight tool calls, three searches, one citation repair, recursion limit 30 and 120 seconds of active execution excluding human waiting. Bound model input context to 12,000 tokens while preserving complete tool-message groups. Validate tool schemas and reject unexpected parallel batches. Budgets, provider failures and invalid output must terminate safely. |
| AGENT-08 | Add the separate agent status, thread creation, message, resume and clear endpoints specified in the plan. Responses distinguish answered, needs-input, insufficient-evidence and limit-reached states; infrastructure errors remain safe HTTP errors. Expose no raw checkpoints, prompts, secrets or hidden reasoning. Missing optional AI dependencies/configuration must not break calculator-only operation. |
| AGENT-09 | Add a document conversation panel with follow-ups, clarification, citations, loading/error states, reset and restart/expiry messaging. Show only sanitized tool activity summaries. Keep safe text rendering and prevent overlapping submissions. No streaming or durable conversation history is required initially. |
| AGENT-10 | Pin corpus version per logical turn; invalidate pending work if the active corpus changes before resume. Re-resolve and retrieve current evidence on later turns. Expanding the on-disk corpus requires a separate review/ingestion step and is not automatic agent behavior. |
| AGENT-11 | Add scripted graph and API tests for multi-search loops, grounding, clarification/resume, budgets, malformed tools, prompt injection, session isolation, deduplication, concurrency, expiry and restart. Preserve all existing regression tests; separately document browser verification and live answer-quality/cost/latency evaluation before marking implemented. |

Planning review evidence: all 20 existing Python tests and JavaScript syntax checking passed. The repository contains 22 PDFs (41 pages), but the local active manifest lists one document. Two incoming PDFs have zero-text second pages that fail current extraction policy; two incoming metadata JSON files are invalid and unused. These findings do not change the active corpus or the implemented RAG contract. See the plan for exact files and verification limits.

### 11.1 First end-to-end increment — implemented scope

The user authorized the base flow on 2026-09-11. Implement AGENT-01–AGENT-11 as a first increment with these explicit simplifications overriding the broader proposal: reuse the installed OpenAI Responses SDK with an adapter to LangGraph messages instead of adding `langchain-openai`; use a separate structured finalization call and the existing exact-excerpt validator (claim-by-claim semantic checking and citation repair remain deferred); allow five reasoning calls plus one finalization, eight tool calls, three searches and recursion 30. Enforce a 12,000-token context ceiling by safely stopping rather than automatic history summarization. Provider calls have 30-second timeouts and no agent-model retries; an overall hard cancellation deadline is deferred. In-memory sessions expire after 30 idle minutes, cap at 100 threads and 20 turns, use server-generated bearer capabilities held only in browser memory, serialize requests and cache completed request IDs. Refresh starts a new chat. No streaming, history restoration, production authentication or live corpus expansion is included. A separate chat script preserves existing form behavior. Automated tests must exercise actual API-to-graph execution with scripted providers, including clarification and repeated retrieval; live checks use already configured keys if available. Broader unimplemented requirements remain explicitly deferred rather than marked complete.

Baseline reconciliation: the newly merged `main` now accepts a five-digit `zip_code` plus monthly usage instead of selecting a TDU. The catalog uses a demo ZIP-to-plan-ID mapping; saved legacy snapshots remain readable. Sections 1–7 have been reconciled with ZIP input; historical acceptance examples in section 8 predate that change. This increment does not modify ZIP behavior. The 24 Python and five ZIP UI tests are the current regression baseline.

Implemented adjustment specified before the follow-up fix: require a tool call until the current logical turn has attempted retrieval, so the model cannot silently reuse an earlier turn's evidence. The finalizer receives an explicitly identified latest question and only current-turn clarification; prior turns resolve references rather than becoming a list of questions to answer again.

### 11.2 Implementation and verification status

The base end-to-end document agent is implemented in `backend/agent/`, the shared grounding functions in `backend/knowledge/evidence.py`, and the separate frontend `agent.js` conversation panel. See the [agent run guide](smart-power-plan-advisor/docs/agent.md) and [live evaluation record](smart-power-plan-advisor/docs/agent-evaluation.json).

| Requirements | Delivered first-increment status |
| --- | --- |
| AGENT-01–AGENT-03 | Implemented explicit ReAct nodes/messages, three allowlisted document tools, fresh retrieval per turn, active-manifest scope checks and stable evidence IDs. OpenAI Responses SDK adapter replaces the proposed additional LangChain model adapter. |
| AGENT-04 | Exact-excerpt citation validation and conservative abstention implemented. Claim-by-claim answer schema, semantic verification and automatic citation repair deferred. |
| AGENT-05–AGENT-06 | InMemorySaver, isolated bearer-capability threads, lazy idle expiry, capacity/turn limits, explicit clear, interruption/resume, per-thread locks and completed-request deduplication implemented. Browser refresh starts a new conversation; no durable recovery. |
| AGENT-07 | Reasoning/tool/search/recursion bounds and conservative context-size stopping implemented. No automatic context trimming/summarization, citation-repair loop or hard overall cancellation deadline; those remain deferred. |
| AGENT-08–AGENT-10 | Separate status/thread/message/resume/clear API, safe errors, optional dependency boundary, document chat, current-turn grounding and corpus-change rejection during clarification implemented. No streaming or transcript restoration. |
| AGENT-11 | 33 Python tests and eight JavaScript DOM-stub tests pass, including 24 pre-existing Python and five ZIP UI regressions. Three sequential live OpenAI/Pinecone smoke cases passed: cited contract term, cited termination-fee follow-up, and supported abstention on an exact bill request. Live HTTP clarification/resume and cited PDF serving also passed. Broader adversarial live evaluation, cost benchmarking and full visual browser QA remain deferred; no connected browser was available. |

The first live follow-up attempt exposed missing re-retrieval; the tool-selection and latest-question finalization fix was specified first, implemented and verified by repeating the live sequence. Initial restricted-network connection errors were retried with authorized network access. No index creation/reingestion or key modification was needed. The older planned table and architecture proposal remain as a roadmap; only the subset explicitly listed here is claimed implemented.

### 11.3 Unified chat interface — implemented

Replace the two document-question forms with one document chat workspace. Keep all user messages, assistant answers, clarification questions, errors and source excerpts together in a scrollable conversation; use one anchored composer and a document selector in the chat header. Provide an empty state, prompt suggestions, readable message bubbles, expandable sources, an in-progress indicator, Enter-to-send with Shift+Enter for a newline, and focus restoration after requests. Keep the calculator available separately in a collapsible section. Preserve text-only safe rendering, request deduplication, session/reset behavior and the existing knowledge API for compatibility. This is a presentation change, not durable history: refresh/restart still starts a new conversation. Acceptance: only one document chat form, multiple turns remain visible together, clarification stays in the transcript, sources remain attached to their answer, errors do not erase history, responsive layout and existing calculator/UI regressions pass.

UI verification: ten JavaScript tests pass, covering multiple turns in one transcript, safe expandable citations, clarification, retry deduplication, reset/expiry, keyboard submission and existing ZIP behavior. Both scripts pass syntax checks. Full visual browser QA remains unavailable. RAG-09’s original standalone form is superseded by this unified chat; its backend API remains supported.
## RAG-01/RAG-02 amendment: blank PDF pages - implemented

For indexing the expanded data corpus, skip pages with no extracted text and no
PDF objects (characters, images or vector drawings). Preserve original page
numbers, record skipped_blank_pages per document, and reject documents without
any usable pages. Continue rejecting scanned/nonblank short pages and oversized
pages. Version the extraction policy. Test blank-page skipping, original page
citations, all-blank rejection and existing scanned-page rejection before ingestion.

Verification: 17 RAG tests passed. Created power-plan-documents (3072 dimensions, cosine) and ingested all 22 PDFs into power-plans-992a431d5dda47a05af9294d. Verified all 59 vectors by ID and document coverage, plus a successful filtered retrieval. Two truly blank trailing pages were skipped; original PDF files and page numbers were preserved. Active manifest: smart-power-plan-advisor/.data/knowledge.json. Policy: table-page-parent-1800-child-450-overlap-60-v3-skip-blank.



## 12. PDF plan catalog and incremental ingestion — implemented

User confirmed that extracted PDF plans should be usable by the calculator and that ingestion should run through an explicit incremental sync command. SQLite is the authoritative structured catalog; Pinecone remains the independent semantic-search index. No assumption that the existing Pinecone manifest already includes all on-disk PDFs.

| ID | Planned behavior and acceptance |
| --- | --- |
| CATALOG-01 | Recursively discover all case-insensitive PDF extensions under configured data root. Track each source path, SHA256, extraction version, original pages and status in a separate `.data/plans.sqlite3`. Deduplicate identical PDF bytes into one plan while preserving all source paths. |
| CATALOG-02 | `python -m backend.catalog.cli sync` discovers new/changed files; unchanged successful extraction is reused without model calls. Reattempt failed/review-required extraction with `--retry`; `--force` regenerates all. A process lock prevents overlapping sync runs. Store each result transactionally; retain revision history. Missing files become inactive, never silently serve stale changed-file terms as current. Missing/unreadable root must not deactivate the catalog. |
| CATALOG-03 | Extract page-preserving text using existing table-aware extraction. Skip structurally blank pages (no characters, images or drawing content) with an explicit warning; fail scanned/nontext, oversized and corrupt documents individually. Duplicate pages preserve first-page evidence. No OCR, remote downloads, or folder watching in this version. |
| CATALOG-04 | Use deterministic extraction for reviewed EFL layouts, with configured OpenAI structured extraction as a review-required fallback to obtain plan identity, provider, service area, document issue date, contract term, product type, termination terms, recurring charges/credits, price examples and limitations. Require page/exact-quote provenance for facts and components. Validate numeric amounts against quoted text. Unknown facts are null/absent, never inferred from advertised average rates. Store extraction model/version and validation issues; machine extraction is not a guarantee of tariff accuracy. |
| CATALOG-05 | Support calculator components for a single flat energy rate, fixed monthly base/delivery charges, delivery per kWh, and conditional usage charges/credits with explicit inclusive/exclusive thresholds. All monetary values use Decimal, explicit USD or cents/kWh units and existing line-item rounding. Missing mandatory charges, variable rates, tiered/time-of-use/seasonal rules, incomplete extraction, missing identity/service area, terms shorter than the 12-month comparison horizon or failed advertised-price reconciliation make a plan non-calculable with reasons. Do not infer missing TDU rates or allocate time-of-use from monthly totals. |
| CATALOG-06 | Reconcile supported rules against the PDF's 500/1000/2000 kWh price examples (tolerance 0.15 cents/kWh); retain per-example checks. This is a consistency check, not independent approval or live-offer verification. Prices are document-date estimates with constant-rate assumptions, taxes and nonrecurring fees excluded. |
| CATALOG-07 | Add `GET /api/catalog/plans` with pagination and provider/service-area/calculable filters, `GET /api/catalog/plans/{id}`, `GET /api/catalog/status`, and hash-checked `GET /api/catalog/plans/{id}/document`. List current source-backed records, including blocked plans; provide per-file ingestion status and failure summaries. No unauthenticated ingestion/upload mutation endpoint. Existing `/api/plans` remains the demo compatibility API. |
| CATALOG-08 | Extend comparison input with optional `data_source` (`demo` default for API compatibility, or `pdf`). PDF comparisons query SQLite, use only calculable unique plans matching the existing limited ZIP-to-area map, and never mix demo rates. Unknown/uncovered ZIP or no eligible plans yields an actionable 422. Store PDF result snapshots with document revision IDs, source links and exclusion reasons; legacy snapshots remain readable. |
| CATALOG-09 | Calculator UI defaults to PDF mode and offers explicit demo mode, labels document-date assumptions, shows source links and excluded-plan reasons, and invalidates stale responses on mode changes. Update synthetic-only labels. No change to the document-only agent's tool scope. |
| CATALOG-10 | Tests cover new/unchanged/changed/missing/duplicate PDFs, failed/retried extraction, blank/scanned pages, revision retention, hash-safe serving, pagination/filtering, Decimal credit boundaries, rule exclusions, price reconciliation and PDF comparison persistence. Run ingestion on all repository PDFs and verify a second sync makes zero extraction calls. Retain prior calculator, chat and RAG regressions. |

Current scope intentionally separates catalog sync from RAG publishing. Adding a PDF then running catalog sync updates the plan API/calculator; chat availability still follows the existing explicit Pinecone ingestion process. A later unified dual-store publishing workflow can be added without making Pinecone the source of structured pricing records.

Implemented catalog extraction refinement, specified before implementation: recognized EFL layouts use deterministic label/table extraction for identity, flat charges, credits and examples, with exact page provenance. OpenAI is a fallback for unfamiliar layouts, and fallback records are always review-required rather than calculator-approved. This replaces automatic calculator eligibility based on model extraction alone after live probes showed misassigned charge conditions. Future PDFs matching supported layouts can become calculable after deterministic checks; unknown layouts are browsable pending a parser extension. Version the parser and reprocess when that version changes. Tiered/interval/seasonal cases remain excluded. Zero base charges may be represented only when the source explicitly states zero or a recognized exhaustive list of recurring charges omits a base charge; retain that statement as provenance and record the derivation.

Implemented catalog duplicate refinement, specified before implementation: different PDF bytes can contain identical extracted terms (for example, re-exported PDFs). Group identical validated extraction payloads into one API plan with all source filenames and per-source hashes, while retaining each file/revision in ingestion history. Comparisons must not rank the same extracted plan twice. Plan IDs derive from extracted content; a changed tariff produces a new content identity and saved results retain their original revision reference.

Implemented supported-layout gate, specified before implementation: calculator eligibility also requires a reviewed structural text fingerprint. Normalize whitespace and numeric values, but preserve labels, operators and prose. New/changed pricing language therefore cannot silently reuse a provider-name match; it goes through model extraction as review-required. Numeric/date changes within a reviewed layout can be parsed incrementally. Checked-in layout fingerprints are a versioned allowlist, not automatically learned during sync.


### 12.1 Verification and operational status

Implemented in `backend/catalog/` with a separate SQLite store, versioned deterministic parser/layout allowlist, optional model fallback, incremental CLI, catalog routes and PDF calculator. The calculator selector defaults to PDF mode; demo API compatibility and saved legacy snapshots remain supported. New `PlanComparison` fields `source_url`/`source_revision` default to null and `ComparisonResult.excluded_plans` defaults to an empty list.

Verified against all 22 repository PDFs: 20 unique extracted plans, eight calculation-eligible plans, twelve excluded with explicit reasons, and no failed source files in the final parser-v3 sync. Structurally blank pages were recorded and skipped; original PDFs were not modified. A second final-version sync reused all 22 files with zero extraction calls. No Pinecone data was changed. Initial model-only extraction trials were not used as calculator inputs; current source records point to deterministic-parser revisions while prior revisions remain in local history.

45 Python tests and 11 JavaScript tests pass, including real-PDF parsing, structural-layout change rejection, price example reconciliation, exact threshold behavior, incremental sync, saved PDF comparisons, source-path guards and existing chat/demo regressions. Browser script syntax checks pass. Full visual browser QA remains unavailable. See [catalog guide](smart-power-plan-advisor/docs/plan-catalog.md) and [evaluation results](smart-power-plan-advisor/docs/catalog-evaluation.json). All current PDFs describe Oncor plans; CenterPoint ZIP requests in PDF mode return no-eligible-plan errors rather than demo substitutions.

The catalog does not establish current market availability, approved tariffs or actual service eligibility. OpenAI fallback records remain review-required. Tiered, interval-based and seasonal pricing, terms under 12 months, unrestricted ZIP lookup, OCR, automated folder watching and combined SQL/Pinecone publishing are not implemented.

## 13. Provider TDU-charge fallback during catalog sync — implemented

When a PDF omits delivery charges, ingestion discovers its provider TDU link and attempts a controlled provider-specific lookup. Initially support the verified 4Change residential table at `https://www.4changeenergy.com/tdu-charges`; recognize other provider links for review and extension without assuming identical layouts. Do not let an LLM invent rates or follow arbitrary PDF instructions/URLs.

| ID | Planned behavior and acceptance |
| --- | --- |
| TDU-01 | Detect TDU/TDSP-charge links in extracted PDF text, normalize scheme/host spelling, and record the candidate link. Use an approved provider-to-URL mapping before any network fetch. The supplied 4Change URL is the explicit fallback for 4Change provider identity even if the link is absent. Other detected provider links remain discoverable with an unsupported-source explanation until a parser is approved. |
| TDU-02 | Fetch only approved HTTPS URLs with no redirects, credentials, query parameters or arbitrary ports; bound response size and timeout, reject non-HTML responses. Cache success or failure per URL within one sync. Parse table rows deterministically, matching the plan's service area and residential labels; reject absent, duplicate, ambiguous or invalid rates. |
| TDU-03 | Store rate amounts/units, service area, source URL, exact normalized table snapshot, snapshot hash, fetched-at timestamp and published date/date label. An “Updated” label is a publication date, not a claimed legal effective date. Require a parseable dated table no later than the PDF issue date before enabling document-date comparison; newer tables remain review-required. Keep original PDF charges when present and never overwrite them. |
| TDU-04 | Missing charges may be filled only from verified lookup results. External components use web provenance, never fake PDF page citations. Continue all existing pricing/layout gates and advertised-price checks. Show external TDU source/date in comparison responses/UI and preserve its snapshot in saved results. A failed lookup leaves the plan browsable and non-calculable with a clear reason. Suppress secondary price-example mismatches when mandatory recurring rates are missing. |
| TDU-05 | Bump extraction version so the next sync processes existing PDFs. Normal sync reuses successful unchanged snapshots; `sync --refresh-tdu` re-fetches TDU-dependent/missing-rate plans without refreshing unrelated PDFs. `--retry` retries blocked lookups too. Failed refresh must not leave prior external rates active. API/catalog reads never fetch the network. |
| TDU-06 | Test dated area matching, unit conversion, exact provenance, missing/ambiguous/newer rates, network failure, unapproved URLs, existing-rate preservation, refresh invalidation and regression behavior. Verify the real 4Change PDF and public rate page end to end. Other tariff limitations (tiered/interval/seasonal pricing) remain enforced. |

Verification on 2026-09-11: all 52 Python tests and 11 JavaScript tests passed; JavaScript syntax checking passed. Live sync processed 22 files into 20 unique plans, with nine calculable after resolving the 4Change Oncor delivery charges. The running comparison API returned HTTP 200 and $804.12 for that plan at 1,000 kWh each month, including the provider URL, publication date and table snapshot. See `docs/tdu-evaluation.json`. Only the approved 4Change page is fetched initially; other discovered provider pages require a reviewed adapter. Full browser visual QA remains unavailable. Section 12’s original eight-plan evaluation predates this fallback.

Integration verification after merging `origin/main` (`896a69b`): preserved the upstream RAG blank-page amendment and catalog/TDU requirements; all 53 Python tests, 11 JavaScript tests and both browser-script syntax checks passed.

## CATALOG-02 portability fix - implemented

The calculator frontend can update while an older non-reloading server still runs;
restart with backend reload so the running schema accepts data_source. Catalog sync
must work on Windows as well as POSIX: use msvcrt byte locking on Windows and flock
on POSIX through one context manager. Preserve nonblocking single-sync exclusion,
release on success/error and reuse of the lock file. Verify contention/release and
catalog regressions, then sync local PDFs and verify PDF comparison via HTTP.

Verification: project .venv retry processed 22 PDFs with 22 extracted and zero failures, producing 20 unique plans and nine calculable plans. The earlier all-file failure was ModuleNotFoundError under system Python, which lacks pdfplumber. Live POST /api/comparisons with data_source=pdf and ZIP 75201 returned HTTP 201 with nine recommendations. Twelve of 13 catalog tests passed, including cross-process lock contention and release after errors; the remaining pre-existing symlink test was blocked by Windows privilege error 1314 before testing path escape. Server restarted with backend reload and network access. Windows setup/retry instructions recorded in docs/plan-catalog.md.


## 14. Deterministic recommendations - implemented

Authorized 2026-09-12. Extend comparisons with a persisted recommendation_result;
legacy snapshots default this field to null. Existing bills, cost ordering, ZIP
coverage and document-agent scope remain unchanged. No provider/model call occurs
while recommending. Recommendation policy v1 prioritizes supplied-usage cost.

- REC-01: Reuse demo/PDF calculators for five shared scenarios: supplied usage and
  uniform multipliers 0.8, 0.9, 1.1, 1.2, preserving month order and rounding usage
  to four decimals. Filter by optional maximum contract length before scenario
  ranking; the baseline can remain outside that preference filter. Only currently
  calculable, ZIP-matched plans qualify. Return up to three, deterministic ties,
  cost winner and minimax-regret winner. Empty preference result yields no winner.
- REC-02: Regret is scenario cost minus minimum candidate cost in that scenario.
  Maximum regret is over these five scenarios only; no probabilities or forecast
  claims. Show alternative's additional supplied-usage cost and ranking changes.
- REC-03: Report positive-credit months, annual credits and scenario months where
  credit value decreases. Probe every credit boundary at b-0.0001, b, b+0.0001 kWh
  (nonnegative only), preserving strict/inclusive and upper/lower bounds. Show
  bills/credits at probes and nearby months within 10% of boundary (floor 1 kWh).
- REC-04: Add optional recommendation_options: usage provenance (unknown default,
  estimated, bills, meter), max_contract_months, baseline_plan_id, switching_cost.
  Baseline must be a currently calculable ZIP-matched plan from the chosen source;
  invalid baseline rejects input. Savings use the same 12 months and calculator.
  Without baseline return null. Gross and net savings are distinct; unknown
  switching cost leaves net savings and payback null. Staying on baseline costs
  zero to switch. Negative savings are retained. Find earliest month after which
  cumulative net savings stay nonnegative through month 12, if any.
- REC-05: Confidence exposes evidence, provenance, scenario stability, freshness
  and unverified availability separately. High is not claimed with unverified
  live eligibility. Unknown/estimated usage, demo evidence, stale/unparseable issue
  dates or unstable best-plan ranking give low confidence; otherwise moderate.
  Freshness heuristic is 365 days, not legal validity. No probability/confidence %.
- REC-06: Break-even conditions include switching-cost recovery and sampled
  usage-scenario brackets where cost preference between best and alternatives
  changes. Brackets are explicitly not exact crossing points or guarantees of
  one crossing; credit discontinuities and untapped scenarios remain warnings.
- REC-07: Include key_tradeoffs, warnings, evidence_refs, confidence_reasons,
  assumptions, scenario definitions, horizon and policy version. Per-plan analysis
  includes scenario costs/ranks/regret, maximum regret, credit analysis and source
  references. PDF references preserve pages/quotes/revisions and TDU evidence;
  calculation references identify reproducible saved scenario outputs. Missing
  baseline/preferences/verified eligibility never receive invented values.
- REC-08: UI exposes provenance, optional contract ceiling, optional current-plan
  selection from the comparison and optional switching cost, preserving old calls.
  Render primary/alternative, top three, confidence reasons, tradeoffs, scenario
  table, credit sensitivity, sampled break-even conditions, savings, warnings and
  source references. Persist options in recommendation output and restore them
  without refetching catalog; invalidate stale results on edits. Retain raw monthly
  breakdowns. Legacy results remain readable without recommendation data.
- REC-09: Tests cover independently calculated cost/regret and ranking reversals,
  strict/inclusive lower and upper credit bounds, decimal probes, equal/zero usage,
  one/no eligible plans, preference filters, missing/invalid baseline, switching
  payback and negative savings, confidence reasons, PDF/demo evidence and snapshots,
  and UI input/render/restore behavior. Document unimplemented live verification,
  arbitrary current-plan uploads, renewable preference ranking, probability models
  and exact continuous break-even solvers as beyond available data/policy.

Verification 2026-09-12: all eight recommendation test methods passed. Full regression: 61 of 62 Python tests passed; the pre-existing catalog symlink test is blocked by Windows privilege error 1314. All 14 JavaScript DOM-stub tests and app.js syntax checking passed. Live PDF POST returned HTTP 201 with three top plans and five scenarios; GET returned an identical saved snapshot. Optional catalog-baseline savings, explicit switching cost and payback were verified through HTTP. No full browser visual test was available. The app is running with backend reload on port 8000. See smart-power-plan-advisor/docs/recommendations.md for the implemented policy, wire contract and limitations.


## 15. Two-tab application navigation — IMPLEMENTED

Requested 2026-09-12. This section supersedes the expandable calculator layout.

- UI-13: Browser title and visible main heading are Smart Power Plan Advisor. Remove demo from site branding; retain accurate synthetic-data labels in the calculator.
- UI-14: Provide Plan Assistant and Compare Plan Costs tabs. Assistant is the default; a nonempty comparison query parameter opens Compare Plan Costs immediately, including while loading or displaying a retrieval error. Keep document chat and its controls in the assistant panel; keep calculator inputs, recommendations, breakdowns, status and saved comparison links in the comparison panel.
- UI-15: Switching tabs hides/shows existing panels without reconstructing content, clearing state, submitting requests or changing the URL. Pending responses must not switch tabs or move focus into the hidden panel. Refresh retains existing chat reset behavior.
- UI-16: Use tablist/tab/tabpanel roles, linked accessible names, aria-selected, one tab stop and hidden inactive panels. Left/Right arrows wrap and activate tabs; Home/End select first/last; standard buttons support Enter/Space. Responsive tabs fit narrow screens and retain visible keyboard focus.

Acceptance: verify default and saved-link selection, pointer and keyboard navigation, retained panel contents, and existing calculator/chat UI regressions. No API, pricing, recommendation or agent capability changes. Record automated verification and any browser testing limits when complete.

Verification 2026-09-12: all 18 JavaScript DOM-stub tests passed (calculator, chat and tabs), including keyboard wrapping, default/saved-link selection, retained panel contents and hidden-assistant response focus. Syntax checks passed for tabs.js, app.js and agent.js; git diff --check passed. Live HTTP checks returned 200 for the page and tab script and confirmed the main title, unique element IDs and single navigation script. No full browser visual or assistive-technology test was performed; responsive layout was checked by source inspection. Backend behavior is unchanged.

## 16. Agent plan-name clarification and citation recovery — IMPLEMENTED

Reported and reproduced 2026-09-12: sending Frontier Saver Plus 12 as a first message retrieves evidence but returns an exact-excerpt validation failure.

- AGENT-12: Instruct the decision model to call ask_user for a standalone plan/document name with no stated question, rather than generate an unsolicited factual summary. Preserve explicit summary requests and context-resolved follow-ups/clarification answers. Include the current clarification question along with its answer in finalization context so the user's intent remains explicit.
- AGENT-04 amendment: Explain the exact citation contract to the agent finalizer: known source IDs, contiguous verbatim excerpts, whitespace normalization only, 20–1200 characters, no paraphrases or stitched table rows. If a non-abstaining generated answer fails citation validation, allow one fresh finalization attempt against the same current-turn evidence, with citation-specific guidance. Never loosen validation, fabricate supporting quotes, or publish the rejected draft. If repair fails, retain insufficient_evidence with no unvalidated citations.
- AGENT-07 amendment: Keep six total model calls per logical turn. A repair is allowed only if the reasoning calls plus initial finalization leave one call available; no repair after five reasoning calls. No retries for deliberate abstention, absent retrieval evidence or provider failures. No additional retrieval/index writes. Record only a sanitized recovery activity message.

Acceptance: scripted graph/API tests cover valid recovery, repeated failure, no repair for abstention/no evidence, exhausted call budget and preserved clarification context. Verify the real first-message Frontier case and a specific document question using the configured application when possible. No pricing, comparison or Pinecone ingestion changes. Semantic claim verification remains deferred.

Verification 2026-09-12: all 12 agent tests and 17 knowledge tests passed. Scripted tests verified repair success/failure, unchanged evidence, no repair for abstention/missing evidence/exhausted budget, and current clarification context. Live HTTP first-message Frontier Saver Plus 12 returned needs_input; resuming with the contract-term question returned answered with 12 months and the exact excerpt Contract Term: | 12 Months from choosetexaspower/EFL-4.pdf page 1. This live case did not need citation repair; repair is verified by scripted tests. git diff --check passed. Model-directed clarification is not a deterministic guarantee for every wording; semantic entailment checking remains deferred. App restarted on port 8000; existing in-memory conversations must be restarted after reload. See docs/agent.md for current bounds.

### 16.1 Citation selection from prepared excerpts — IMPLEMENTED

AGENT-04 follow-up, 2026-09-12: the live Frontier rates case reproduced quote corruption (the cents symbol became a NUL-containing escape and table rows were reordered). Fees succeeded in this diagnostic run; the reported failures are variable model output, not proof of missing indexed pages.

Replace free-form quote generation in the agent finalizer with selection of server-prepared excerpt IDs. Split each current-turn source into contiguous windows of at most 1000 characters with 200-character overlap; retain exact original text and page/source identity, and omit windows whose whitespace-normalized text is shorter than 20 characters. Send these excerpts instead of duplicate full-page text. The model returns answer, abstained, and at most eight excerpt IDs. Resolve every ID against the current invocation's map into the existing GeneratedAnswer evidence contract, then use the unchanged exact-excerpt validator. Unknown IDs must reject the entire answer, not be dropped or reassigned. Preserve one bounded repair attempt and the six-call limit. The HTTP citation schema and legacy knowledge API remain unchanged. Semantic entailment is still not automatically verified; instructions require each factual claim to be supported by selected excerpts.

Acceptance: verify exact symbol/table preservation, window bounds and overlap, unknown-ID rejection, empty/refused output, repeated source citations, and existing graph/knowledge regressions. Repeat the actual plan-name -> fees clarification -> rates follow-up via configured providers and validate cited excerpts. No reingestion or index mutations.

Verification 2026-09-12: all 14 agent tests and 17 knowledge tests passed; git diff --check passed. Tests cover original Unicode cents symbols, raw table newlines, exact slices and overlap, multiple citations on one page, unknown-ID rejection, missing evidence/refusal, adapter conversion and bounded repair. Live Runtime/graph execution against configured OpenAI/Pinecone reproduced plan name -> fees clarification -> rates follow-up: both factual responses were answered with exact PDF citations, including unchanged cents symbols, with no repair needed. This validates the reported sequence, not every possible model answer or semantic entailment. No index mutations or browser visual tests were performed. The original prompt-only repair was insufficient for the broader rates question and is superseded by excerpt selection in the agent adapter; the legacy knowledge adapter is unchanged.

## 17. Hide assistant source selector - IMPLEMENTED

UI-17 (2026-09-12): Hide the Sources label and document dropdown in Plan Assistant, including from keyboard navigation and accessibility exposure. Retain the existing hidden selector and its empty default value for compatibility with agent.js; fresh conversations search all indexed documents. Preserve answer citations, the Answers with citations indicator, chat behavior and Compare Plan Costs controls. Acceptance: inspect hidden markup and run existing agent UI regressions. No API changes.

Verification 2026-09-12: inspected native hidden attributes on both label and select, with existing all-document default retained. All six existing agent UI tests passed. No full browser visual test performed.

### 17.1 Restore source selector - IMPLEMENTED

UI-17 revision: supersede the hidden-selector behavior above at the user's request. Show the Sources label and dropdown again, retaining All indexed documents as the default and existing readiness/busy/clarification disabling behavior. Preserve source filtering and citations. Acceptance: remove native hidden attributes from both elements and run existing agent UI checks. No API changes.

Verification: both hidden attributes removed and all six existing agent UI tests passed. No full browser visual test performed.

## 18. Compact comparison workspace - IMPLEMENTED

UI-18: Restyle Compare Plan Costs with a compact responsive form: ZIP and plan source side by side on desktop, a short labeled January-December usage textarea, optional preferences in a collapsed section with a two-column field grid, and a clear comparison action. Keep existing IDs, validation, data defaults, request payloads and saved-input restoration. Retain essential estimate/synthetic-data limitations; move lengthy help to disclosures and remove developer API links from the form.

UI-19: Present a compact recommendation summary with annual cost, clearly labeled average monthly cost (annual divided by 12, not a bill forecast), confidence, top-plan cards and savings availability. Keep tradeoffs accessible and show the first warning with an expandable full list. Group confidence reasons, scenarios, credit sensitivity, break-even conditions and source evidence into collapsed details. Show all compared plans as compact expandable rows with plan name, contract term and annual price; retain explanations, source links and full monthly breakdowns inside each row. Do not alter ranking, pricing, savings meaning, negative/unknown amounts, exclusions or legacy-result support. Keep distinction between recommendation-qualified plans and all raw cost comparisons.

Acceptance: existing comparison/chat/tab tests pass; check disclosure structure and retained recommendation/billing information, unknown savings and legacy/no-eligible states. Responsive layouts stack on narrow screens, controls remain labeled, focus remains visible and wide tables scroll. Verify rendered layout in a browser if available; report limits honestly. No backend changes.

Verification: all 18 existing calculator/chat/tab UI tests passed, including option restoration, unknown savings, legacy snapshots and no-qualifying-plan results. app.js syntax and git diff --check passed. Headless Edge rendered the actual FastAPI application through a local TestClient with a temporary comparison database: PDF comparison produced nine plan rows, initially collapsed; annual/monthly metric labels rendered; opening a plan and monthly breakdown exposed all 12 rows; switching tabs retained ZIP and results. Desktop 1280px and mobile 390px screenshots were visually reviewed, with no horizontal page overflow including expanded monthly tables and no browser JavaScript errors. Screenshots are local ignored artifacts under .data/compare-desktop.png and .data/compare-mobile.png. No external document-service calls or production comparison writes were needed for browser verification.
