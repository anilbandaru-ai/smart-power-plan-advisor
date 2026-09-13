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


## 19. Agent grounding and scope recovery - IMPLEMENTED

AGENT-04: Restore agent-only citation selection using prepared contiguous source excerpts (up to 1000 characters, 200-character overlap, minimum 20 normalized characters). Model selects at most eight excerpt IDs; Python resolves original quotes and validates them with the existing exact-excerpt validator. Unknown IDs reject the entire draft. One repair attempt is allowed for invalid non-abstaining output if fewer than five reasoning calls were used; total model calls remain at most six. No retry for intentional abstention, missing evidence or infrastructure failures. Keep legacy knowledge API unchanged; semantic entailment is not guaranteed by exact matching.

AGENT-12: A standalone plan name should prompt a question about the user's intent. Preserve current clarification question/reply and earlier user context for follow-ups, with fresh retrieval per factual turn. Unknown plans must not be substituted with similar offers. Respect selected-document scope and explain missing evidence.

AGENT-13: Add an allowlisted redirect_to_comparison tool that returns a fixed document-only limitation pointing to Compare Plan Costs, without collecting billing details. Detect explicit common bill-calculation and recommendation requests before model reasoning, including clarification replies; other phrasings are handled by model instructions/tool choice. Do not block factual questions about documented rates, fees or bill-credit conditions. Redirects use the existing insufficient_evidence/abstained response shape, no fabricated citations, and leave the conversation usable. The merged frontend exposes Compare Plan Costs as a tab.

Acceptance: regression tests for exact Unicode/table citations, unknown IDs, repair budget, clarification context, scoped retrieval, reset, and calculation redirects (including resume) while retaining factual rate/credit support. Live plan name -> fees -> rates, contract term, scoped document, unknown plan and unsupported calculation checks. Record actual test results and live limitations before marking implemented. No index, pricing or comparison changes.

Verification: 17 agent tests, 17 knowledge tests and five chat UI tests passed; git diff --check passed. Live HTTP Frontier plan name -> fees -> rates returned clarification followed by cited answers, with citation URLs serving PDFs. Exact bill request immediately returned the fixed Compare Plan Costs redirect. Scoped Frontier contract-term request answered 12 months using only the selected document. A nonexistent plan returned insufficient evidence. Reported broader failures were reproduced before this change. No index/pricing/UI changes. Arbitrary wording still relies in part on model routing, and exact quote validation does not prove semantic entailment. The application is running in a hidden background process on port 8000. See docs/agent.md for behavior and verification limits.


### 19.1 Main integration - IMPLEMENTED

Merge origin/main into improve-plans-assistant. Retain incoming recommendation and compact tabbed UI requirements, excerpt-ID citation generation and all distinct regression tests; preserve branch calculation redirects and earlier clarification context. Reconcile duplicate agent definitions and documentation. Acceptance: no conflict markers, merged Python and UI regressions, preserved redirect/scope behavior. Record any existing environmental test limitations before committing the merge.

Merge verification: origin/main at 24e25be integrated with branch agent redirects and earlier clarification context. All 18 UI tests and 74 of 75 Python tests passed. The remaining pre-existing catalog symlink test cannot create its fixture on Windows (privilege error 1314). No conflict markers remain; merge combines all distinct agent tests from both branches. No additional live model evaluation was performed for this integration.

## 20. Contract preference visibility - IMPLEMENTED

UI-19 / REC-08 amendment: the maximum contract length already filters recommendation candidates, but the main comparison list still presents longer contracts without a distinction. Use the saved response's recommendation options to show only contracts at or below the maximum in the primary comparison list, with a matching-plan count and the applied limit. Move all longer contracts with their complete costs and sources into a collapsed Longer contracts section labeled as outside the preference. Preserve raw API comparison data, current-plan baseline choices, saved snapshots, price ordering and recommendation logic. Maximum means at most, not an exact-term match. Legacy responses without options retain the full list. If no contracts match, show that state and keep longer contracts accessible.

Acceptance: verify a 12-month preference separates 24-month plans, retains their details in the secondary disclosure, and no preference restores the full list. Existing submission, restore, legacy and no-eligible UI checks must pass. No backend pricing/API changes.

Verification: API checks against the local PDF catalog confirmed max_contract_months=12 already reduces recommendation candidates from nine to seven while raw comparisons remain nine. All 19 UI tests passed after the display fix, including a saved 12-month preference separating a 24-month plan, preserving its breakdown and baseline option, and restoring both rows without a preference. app.js syntax passed. Full browser visual testing was not performed for this change.

## 21. All preference effects visible - IMPLEMENTED

REC-08 / UI-19: Display an Applied preferences summary from the saved response options for all four fields, including no-eligible results: maximum contract, usage provenance, current-plan name, and entered switching costs. Explain field roles: contract filters candidates; provenance informs confidence without changing rates; baseline enables same-usage savings; switching costs affect net savings/payback, not the cost-first ranking. Keep established ranking and API contracts. Distinguish blank switching costs from zero, entered costs from zero effective costs when staying on the baseline, and missing baseline from zero savings. Show negative net savings prominently, not only inside warnings. Clarify that edits require Compare plans again. Preserve all options on saved-result load and all baseline choices. Tests must cover submitted/restored fields, absent baseline, unknown/zero costs, negative savings and no-eligible results without hiding applied preferences.

Verification: all 22 UI tests and eight recommendation tests passed. Coverage includes option submission/restoration, contract separation, visible applied fields, negative net savings, unknown versus zero costs, costs without a baseline and no-eligible states. app.js syntax and git diff --check passed. No browser visual test performed for this change. Existing backend preference calculations and cost-first ranking are preserved.

## 22. Contract-length comparison horizon - IMPLEMENTED

REC-10: max_contract_months also sets comparison_horizon (12..120 months); absent means 12-month comparison without a contract ceiling. Exclude longer contracts from recommendation eligibility. Repeat the supplied 12-month seasonal profile to fill the horizon, including partial years. Use each candidate's own calculator and document rates during its initial term. Keep original first-year annual_cost/monthly_costs fields for compatibility; add explicit horizon_cost, horizon_monthly_costs and comparison_horizon for raw comparisons. Sort comparisons and recommendations by horizon cost, with plan-ID ties. Saved legacy results remain readable without recalculation.

REC-11: Add renewal_escalation_pct (Decimal 0..30, at most two decimals, default 5) and renewal_credit_policy (retain/drop, default retain). These are user-adjustable hypothetical assumptions, not inflation forecasts or available renewal offers. After original term expiration, scale energy, base and delivery components by (1 + annual percentage/100) ** floor((month-1)/12), rounded per component to cents. Hold documented rates constant within the initial contract, including delivery as an explicit assumption. Retain nominal credit amount/conditions or drop renewal credits per policy; do not escalate credits. Model renewal month by month without claiming a future contract or adding invented renewal fees. Initial-term costs remain document-based estimates, not guaranteed future delivery tariffs.

REC-12: For horizons with expired eligible contracts, cross five usage profiles with base, lower and higher renewal assumptions: configured rate, max(0, rate-5 percentage points), and rate+5 points with renewal credits dropped in the higher scenario. No probabilities. Rank primary by supplied usage/base renewal total; regret and stability span the same eligible set and horizon across all tested scenarios. Keep annual fields first-year-only and add horizon fields for scenarios and recommendations. Show total, annualized average, initial-term versus modeled-renewal costs, monthly basis and yearly totals. Confidence is low whenever any eligible alternative needs assumed renewal, even if the winner spans the horizon.

REC-13: Baseline costs, gross/net savings and cumulative payback use the same full horizon and renewal policy. Preserve first-year annual savings aliases with their literal first-year meaning and add gross_horizon_savings/net_horizon_savings; switching costs apply once, zero if staying. Baseline is a hypothetical new full term of its selected tariff; remaining actual contract length is unknown. Exclude early exit, renewal enrollment fees and taxes unless already supplied as the one-time switching cost; explain limits. Negative/unknown savings remain explicit. Never recommend a longer contract when a maximum is provided.

UI-20: Label maximum as comparison period / maximum contract; expose renewal percentage and credit assumptions under preferences, preserve submission/invalidation/restoration. All result cost, regret, savings, payback, credit totals and breakdown labels must identify the chosen horizon. Retain first-year source details and legacy fallbacks; show original-document and modeled renewal months clearly. Longer contracts stay outside the matching list. Use the persisted comparison_horizon, not a newly inferred horizon, for old saved results.

Acceptance: independent 24/36-month arithmetic, different plan rates, renewal-only escalation, eligibility, partial years, credit retention/drop, ranking reversals, shared-scenario regret, baseline/payback beyond year one, request bounds, saved/new/legacy APIs and frontend options/labels. No index changes or live market/inflation claims. Record verification before marking implemented.

Verification: all 11 recommendation tests passed, including independent 24/36-month ranking reversals, own-plan amounts, longer-contract exclusion, 18-month expiration with a partial 25-month horizon, credits, zero/unknown savings compatibility, payback in month 15 and persisted 36-month API projections. Full suite: 77 of 78 Python tests passed; the existing symlink fixture remains blocked by Windows privilege error 1314. All 23 UI tests passed; app.js syntax and git diff --check passed. Headless Edge through the real FastAPI TestClient verified 24/36-month PDF comparisons, full monthly rows, saved option restoration, tab state and mobile overflow; desktop screenshot visually reviewed. Browser runs used a temporary comparison database and did not call external providers. Documentation records the 5% default as an editable hypothetical renewal assumption, not a forecast. Annual fields retain first-year semantics; new horizon fields drive ranking and presentation. Earlier fixed-horizon requirements are superseded by this section.

## 23. Monthly average price - IMPLEMENTED

UI-21: Add Average Price (cents/kWh) immediately after Energy in each monthly cost breakdown, for original and projected months and legacy saved results. Display total monthly cost in USD times 100 divided by monthly kWh, to two decimal places; this includes the displayed fees/delivery and subtracts credits. Show N/A at zero usage. Explain the calculation in the table caption. This display-only calculation does not change backend billing or ranking.

Verification: column position and total-cost/usage calculation checked by source inspection; all 14 existing comparison UI tests and app.js syntax checking passed. No dedicated browser visual check performed.

### 23.1 Published EFL averages - IMPLEMENTED

UI-21 correction supersedes the calculated average: the column after Energy must use each plan's extracted EFL average-price examples, never total/usage or interpolated/nearest-tier values. Persist efl_price_examples (kwh, cents_per_kwh, source page and quote) in each PDF plan comparison. Match the exact monthly usage to an example; otherwise show Not listed. For modeled renewal months show Not available (renewal); original document examples are not renewal offers. Demo and legacy snapshots without examples show Not listed. Show all published examples in the breakdown for reference with source page provenance. Keep existing bills and ranking unchanged. Verify values deliberately different from computed averages, exact/nonmatching usage, renewals and snapshot persistence.

Verification: all 15 comparison UI tests and 11 recommendation tests passed. Checks cover published 19.7/6.8/12.8 examples even when bill-derived averages differ, column order, unmatched/zero usage, renewal months, missing legacy data, PDF example provenance and serialized snapshot preservation. app.js syntax and git diff --check passed. No interpolation or changes to bill calculation were introduced.

### 23.2 User-defined EFL reference ranges - IMPLEMENTED

UI-21 revision: map usage to the first published EFL example with kWh greater than or equal to monthly usage, sorted numerically. The lowest example covers zero through its value; subsequent bands are greater than the previous example through the current example, including fractional usage (500.1 maps to 1000). Above the highest example show Not listed; missing examples and renewal-month handling remain unchanged. Label the column/caption as an EFL reference using user-defined ranges, not an EFL-stated tariff rule or actual effective rate. This is display-only: keep documented component-based bill calculations and ranking unchanged. Acceptance covers zero, exact bounds, fractional boundaries, unsorted examples and above-maximum usage.

Verification: all 15 comparison UI tests and app.js syntax checking passed, including zero, exact/fractional boundaries, unsorted examples, above-highest usage, renewal and missing legacy examples. Mapping is labeled as a display reference and does not change pricing.

### 23.3 Revised reference bands - IMPLEMENTED

UI-21 supersedes 23.2: use each plan's own sorted published examples. Default to the first example, then select the highest example with threshold strictly below usage. Thus 0..1000 uses the 500 price, >1000..2000 uses the 1000 price, and >2000 uses the 2000 price for standard documents. Exact thresholds remain in the preceding band. Apply dynamically to all plans, without hardcoded prices. Missing examples and modeled renewal handling remain unchanged. Explain this user-defined reference mapping in the caption; preserve billing and ranking. Acceptance: zero, exact/fractional thresholds, unsorted examples, above maximum, plan-specific values and missing/renewal cases.

Verification: all 15 comparison UI tests and JavaScript syntax checks passed. All 22 PDFs / 66 published values matched the catalog; headless Edge verified 108 rendered monthly cells across all nine calculable plans using the revised mapping. Billing and ranking code unchanged.

## 24. EFL mapped-average cost estimates - IMPLEMENTED

PRICE-24 / UI-21 / REC-14: New PDF comparisons use each plan's own published average-price examples with section 23.3's mapping (first price through second threshold, preceding price at exact thresholds, highest above maximum). Monthly estimated cost is usage times the selected cents/kWh divided by 100, rounded half-up to cents. This is a user-defined approximation, not a tariff-derived bill. Zero usage produces zero under this approximation. Preserve the component calculator for catalog validation and demo/legacy behavior. Existing calculation-eligibility restrictions remain; missing or ambiguous duplicate example thresholds must not enter average-based comparisons.

Add pricing_basis and average_price_cents to monthly values and pricing_basis to plan comparisons, defaulting to components for legacy data. For mapped-average months, energy holds the inclusive estimated charge; total equals energy. Base, delivery and credit arithmetic fields are zero because their contribution is already embedded in the average, not because the tariff has no fees or credits. UI labels Energy as Estimated charge (all-in), marks those three fields Included, and displays the exact selected rate used in the calculation. Provide a prominent explanation of the approximation. Snapshot restoration must not silently reprice old results.

Use this same calculator for initial months, horizon totals, ranking, scenarios, regret, baseline savings and payback. Original-term rate stays at the mapped document value. Renewal projection escalates that mapped rate using the existing annual factor, then calculates usage times that rate and rounds once. Show the escalated rate and Modeled renewal basis. Separate retain/drop credit policy is not applied to inclusive prices (credits cannot be isolated reliably); explain this in preferences/results and do not claim separate credit savings/losses. Credit analyses are explicitly unavailable/included, without fabricated qualifying months or credit probes. Keep confidence low for the range approximation, include average-example evidence, and use a distinct efl-average-v3 policy version.

Acceptance: independent 1800 kWh at 6.8 cents = $122.40 in both inclusive-charge and total, no added fees or credit subtraction; each plan's own examples; zero/exact/fractional/above-maximum boundaries; renewal rate and total consistency; missing examples; demo/legacy compatibility; comparison/recommendation/baseline agreement; saved metadata and UI labels. Document test results before marking implemented.

Verification: all four dedicated average-pricing tests and all 25 UI tests passed. Full Python suite: 81 of 82 passed; existing catalog symlink fixture blocked by Windows privilege error 1314. Headless Edge verified 1,296 monthly rows across all nine calculable PDF plans at 12/24/36 months with both credit settings, persisted API snapshots, displayed rates/totals, recommendation agreement and mobile overflow. JavaScript syntax and git diff --check passed. No external model/index or live tariff calls were used.

## 25. Custom EFL-average energy calculation - IMPLEMENTED

PRICE-25 supersedes section 24 for new PDF comparisons. With explicit user authorization, use the mapped EFL average as the Energy rate, then add PDF base/usage fees and fixed/per-kWh delivery, and subtract qualifying PDF credits. This deliberately custom formula repeats effects embedded in published averages; label it Custom estimate, not an actual tariff bill. Keep the section 23.3 ranges and each plan's own examples. Use component calculator for non-energy charges and its exact threshold conditions. Round Energy and component groups to cents; total = energy + base/usage + delivery - credit. Preserve negative results rather than silently clamping. Catalog eligibility and demo calculations remain unchanged.

Persist pricing_basis=custom_efl and policy_version=custom-efl-v4; preserve old component and inclusive snapshots without repricing. Use the custom calculator for comparisons, ranking, scenarios, regret, baseline and savings. Renewal escalates the mapped energy rate, base and delivery under the existing factor; retain/drop credits applies again. Display the actual mapped/escalated energy rate, numeric component charges, Custom estimate / Modeled renewal basis, and prominent explanation of the formula and its limitations. Credit probes again use the PDF conditions. Confidence stays low. Acceptance: 1800 at 6.8 gives Energy 122.40 plus delivery 112.59 minus credit 125 = total 109.99 for SimpleSaver 24; per-plan rates, boundaries, renewal and credit policies, persistence, old snapshot compatibility and UI values.

Verification: five pricing tests and all 26 UI tests passed. Full Python suite: 82/83 passed; existing catalog symlink fixture blocked by Windows privilege error 1314. Headless Edge independently checked all nine calculable plans: 1,296 monthly rows / 11,664 cells, 12/24/36 horizons, retain/drop credits, charge and rate boundaries, totals and recommendation agreement. Old inclusive UI and default component compatibility tests passed. JavaScript syntax and git diff --check passed.

## 26. Plan-specific renewal disclosure - IMPLEMENTED

UI-22: In each expanded comparison plan's main details, show a renewal note when its saved horizon_monthly_costs contains modeled_renewal rows. State saved annual renewal escalation percentage (including zero), first modeled-renewal month, number of modeled months and that the assumption is hypothetical. Explain compounding uses whole elapsed years from comparison start, applied after initial term. Use saved response options, not current edited controls; if percentage is absent say not recorded rather than invent a default. Do not mark plans without modeled-renewal rows as using escalation. Keep all pricing and persisted contracts unchanged. Acceptance: renewing plan, full-term plan, saved percentage versus controls, zero and missing percentage, legacy snapshots.

Verification: all 18 comparison UI tests passed, covering saved 8%, zero and absent percentages, first renewal month with unsorted rows, nonrenewing plans and legacy results. JavaScript syntax and git diff --check passed. No pricing changes or browser visual check for this text-only disclosure.

## 27. Comparison scenario chat - IMPLEMENTED

CHAT-01: Add a comparison-specific chat after a successful comparison, separate from document Q&A. Persist sessions in SQLite with frozen eligible source-plan records, original and active scenario, successful history, attempt history and pending clarification. Support reload, original/reset and previous scenario. Preserve current results until successful calculation. Render scenarios with the existing comparison UI, active inputs/overrides and changes; mobile layout must avoid page overflow.
CHAT-02: Typed, allowlisted actions interpret natural language through structured model output; deterministic built-in navigation/explanation is available without model calls. Model never calculates costs. Actions support separate horizon (12..120), maximum/exact term, excluding credit plans, usage replacement/percentage changes with explicit month scope and original/current basis, renewal %, retain/drop, baseline, switching costs, scoped mapped-average/delivery/base/credit amount or credit-boundary overrides and clearing overrides. Clarify ambiguous units, plan scope, contract intent or months. Unknown/unsupported requests do not mutate state. Overrides remain hypothetical and never alter PDF catalog records.
CHAT-03: Extend recommendation options with independent comparison_horizon, exact_contract_months, exclude_bill_credit_plans. Existing max-only form semantics remain. Keep excluded baseline available for savings but not recommendation. Filter main scenario list to qualifying plans, record exclusions/reasons. No candidates returns no-match attempt without silently relaxing constraints. Initial source revisions must match the saved result, otherwise require fresh comparison. Old PDF pricing versions require explicit migration confirmation. Subsequent scenarios use frozen source records and original custom-efl-v4 pricing; inherited scenario overrides are visible.
CHAT-04: Per-session lock/version plus request-ID deduplication and request-body matching prevent duplicate scenarios and stale writes. Commit new active state, saved comparison and successful attempt atomically. Failed/invalid/no-match attempts preserve the active scenario; transient errors can retry the same request ID. Handle missing sessions, expired (24h) sessions, malformed model outputs and provider timeouts with actionable errors. UI blocks overlap, rejects stale responses after reset/new comparison/input edit and offers retry. Persist pending clarifications and context, bounded messages/attempts.
CHAT-05: Deterministic result explanation uses saved costs, confidence, reasons and evidence references. Original comparison differences only report like-for-like savings for same horizons; different periods are labeled. Show ties, single candidate, negative totals/custom formula warning, renewal assumptions and unknown switching costs accurately. Source content is untrusted data. Rate overrides require explicit units and plan IDs; validate full action atomically, preserving exact fee/credit boundaries and zero-vs-unknown distinctions. Do not clamp negative custom totals.
Acceptance: end-to-end happy paths, clarification/correction, no-match recovery, all override kinds and filters, usage bounds/fractions/zero, original/current changes, baseline exclusion, exact-vs-max conflict, renewal boundaries, source drift/frozen revisions, migration, duplicate/retry/stale requests, storage/provider failure recovery, session reload/reset/undo and desktop/mobile UI; report actual verification and provider evaluation limits. No change to the approved custom pricing formula.

Verification: final scenario suite 15/15 and frontend suite 31/31 passed. The full Python suite run passed 95/96 tests; its only failure was the existing catalog symlink fixture blocked by Windows privilege error 1314. Two additional scenario regressions were subsequently added and passed in the final targeted suite. Coverage includes concurrent commits, save rollback/retry, invalid atomic changes, unknown/noncalculable overrides, extreme usage, exact/horizon/baseline behavior, no matches, clarification, deduplication/stale versions, expiry/source drift, migration, persisted overrides and frozen original examples. Headless Edge exercised the real FastAPI application and local PDF catalog with a controlled interpreter: clarification, recalculation, no matches, provider failure, reload, undo, input invalidation and 390px mobile layout. Six final interpretation smoke checks passed (four live model calls, two deterministic explicit commands); general language quality is not exhaustively evaluated. Python compilation, JavaScript syntax and git diff --check passed.

Implementation notes: scenario comparisons persist scenario_context containing validated inputs/overrides and frozen source records so new chats preserve prior hypothetical assumptions. Sessions use optimistic version checks with a SQLite transaction at commit, not a lock held across model calls. Structured interpreter fields are validated before mutation; published EFL examples remain original even when their calculation rate is overridden. Chat scenarios use independent horizons and recommendation filters; manual form submissions retain their earlier max-as-horizon behavior and explicitly start fresh without chat-only overrides. Demo overrides are limited to their existing base/delivery/credit fields; PDF-specific fields require PDF plans. See smart-power-plan-advisor/docs/comparison-chat.md.

## 28. Compact comparison chat and readable breakdown - IMPLEMENTED

UI-23: Comparison chat uses short two-line assistant previews with keyboard-accessible link-styled Show more / Show less buttons expanding the complete original message inline. Show clear outcome labels (updated, clarification needed, no matches, failed) separately; preserve important errors and questions and never duplicate the long response in the status region. Simplify actions: Explore alternatives before starting, Original/Previous secondary controls, New conversation secondary, contextual Reload and Retry only on failure/conflict, suggestion chips that fill the composer. Keep existing session/retry/stale response semantics.
UI-24: Place chat between recommendation summary and compared plans, using full-width results rather than the split grid. Monthly breakdowns use shorter eight-column headers with an emphasized total, phase labels outside the repeated Basis column, and year navigation for multi-year results. Mobile uses expandable monthly cards instead of horizontal table scrolling. Preserve all original monetary values, original/custom/inclusive labels, missing references and renewal distinctions. Keep Custom estimate visible, move detailed formula explanation into a disclosure. Test two-line/expanded replies, action visibility and recovery, year selection, all monetary columns, desktop/mobile overflow and keyboard accessibility. No backend pricing or API changes.

Verification: all 33 UI tests passed, including inline expansion, short status messages, retry/conflict visibility, year navigation, partial years, mobile card values and unchanged monetary columns. Headless Edge verified the real PDF application flow, two-line preview height, Show more/Show less, recommendation/chat/plan ordering, desktop table width, year switching, mobile cards and 390px page overflow; desktop/mobile screenshots visually reviewed. Existing clarification, no-match, retry, reload/undo and invalidation flows passed. JavaScript syntax and git diff --check passed. Pricing and backend APIs unchanged; no provider calls needed for this UI change.

### 28.1 Preserve chat during result replacement - IMPLEMENTED

UI-23/24 bug fix: before any comparison-results replacement, move the persistent chat panel to the stable workspace parent, then restore its position after the recommendation is rendered. Clearing results must not remove chat controls from the document. Preserve handlers and request-generation guards. Invalid manual submission must detach the active chat before clearing results. Acceptance: compare, edit/clear, edit again, compare again, start chat and update; repeat direct manual comparison; no null-element errors or duplicate panels/listeners, and restored chat placement. No pricing changes.

Verification: 33 existing UI tests passed, followed by all 20 comparison UI tests including the new result-clear lifecycle regression. Headless Edge verified repeated ZIP edits, two repeated comparisons, restarting chat and a subsequent scenario update with one attached panel and no page errors, alongside the earlier recovery/mobile checks. JavaScript syntax and git diff --check passed.

### 27.1 Explicit contract-term requests and no-match explanations - IMPLEMENTED

CHAT-02/03 correction: recognize standalone "contract term 24 months" (and equivalent explicit term wording) as exact_contract_months=24 without model inference or changes to other filters/horizon. Preserve credit exclusion and maximum constraints; do not silently relax them. For no matches, report the proposed exact/max term and credit filter, the count of calculable source plans meeting the contract criteria before credit exclusion, and whether all are excluded by their credit conditions. Mention that retaining credit exclusion may require another term; suggest allowing credits only as an explicit next action. Record proposed changes even for failed/no-match attempts. Verification must cover the observed saved case (24-month period, prior exact 12, max 24, exclude credits true), successful exact 24 with credits allowed, and truly absent contract terms. Preserve active results on no matches.

Verification: all 16 scenario tests passed. Read-only reproduction from the reported saved session confirmed two 24-month plans excluded by its active no-credit filter; permitting credits on an in-memory copy returned SimpleSaver 24 and Reliant Power Savings 24. Tests cover exact-term parsing, retained constraints, recorded attempted changes, explicit relaxation, successful recommendations and genuinely absent terms. No saved user preferences or catalog data were modified. git diff --check passed.

## 20. TXU integration — implemented (2026-09-12)

This section extends CATALOG-01–CATALOG-10 and supersedes the no-remote-discovery
scope only for explicit TXU ingestion. Existing demo, local-PDF and chat behavior
remains unchanged; TXU comparisons use a new explicit `data_source: "txu"`.

- TXU-01: Add an explicit `sync-txu --zip ZIP [--zip ZIP ...]` catalog CLI command.
  Fetch `shop.txu.com/api/utilities/?zipCode=ZIP`, read `data.utilities`, then fetch
  the top-level plan array from `/api/plans/` for every returned utility using the
  same ZIP. Validate ZIPs, utility IDs, response shapes and offer utility/provider
  identity. Use bounded timeouts, response sizes and transient retries. No API key
  or model call is required for TXU ingestion.
- TXU-02: SQLite stores immutable per-ZIP refresh snapshots, utilities, raw offers,
  timestamps, external offer IDs and EFL source/revision associations. Publish a
  ZIP only after all its utility listings succeed; failed listing refreshes retain
  history and mark the previous snapshot stale. A successful empty result removes
  current availability only for that ZIP. Availability expires after 24 hours and
  stale results remain browsable but cannot enter new TXU comparisons. Unrelated
  ZIPs, providers, local PDFs and saved comparisons are preserved.
- TXU-03: Download only HTTPS EFL URLs on reviewed TXU document hosts, validating
  each redirect, size and PDF signature. Store immutable content-addressed PDFs
  under reserved `data/_txu/`, reusing extraction by bytes/version. Ordinary local
  catalog sync skips that directory and does not deactivate its records. Retain
  downloadable source evidence and per-offer errors; a missing/failed EFL must not
  reuse prior pricing for a changed offer. Unknown layouts are review-required,
  with no automatic model extraction or inference from marketing copy.
  The observed API uses `shopping.txu.com` and `www.txu.com`, and the latter
  redirects to `residential.txu.com`; allow those exact hosts and validate every
  redirect. Expose controlled error categories (HTTP
  status, non-PDF response, missing EFL, unapproved host) without response bodies.
  Managed downloads are ignored by Git. Catalog metadata identifies unparsed
  TXU documents as review-required rather than claiming model extraction.
  Unparsed TXU documents retain content-hash identities: empty extraction fields
  must not collapse unrelated EFLs into one tariff. The cache provides a verified
  local document URL when a source revision is available, alongside the TXU URL.
- TXU-04: Use reviewed EFL parsers and existing Decimal pricing/evidence checks.
  Normalize API energy/delivery rates from USD/kWh to cents/kWh for cross-checking
  against EFL components; monthly fees stay USD. Check standard usage examples,
  name/term/area identity and reject discrepancies. Empty `billCredits` does not
  establish no credits. Free-time, solar-buyback, tiered and seasonal pricing stay
  excluded unless independently supported by reviewed rules. Implement only EFL
  layouts whose actual documents can be inspected; unavailable documents stay
  blocked rather than being approved from API fields alone.
- TXU-05: Expose read-only cached `GET /api/catalog/txu?zip_code=ZIP` with utilities,
  offers, freshness, last failure and calculation exclusions; it never fetches the
  network. Extend comparison request with `data_source: "txu"` and optional UUID
  `utility_id`. Auto-select exactly one utility; require selection for multiple and
  reject IDs outside the requested ZIP. Rank only active, visible offers tied to
  that ZIP/utility and a validated matching EFL revision. Deduplicate identical
  tariffs; snapshot offer IDs, fetch time and document revisions in results.
- TXU-06: Add TXU cached offers as a form source. On submission use the cached
  lookup; expose a labeled utility selector when needed, show freshness/errors,
  and display blocked offers when no plan can be calculated. Preserve edit-driven
  invalidation and saved-result restoration, including utility selection. Existing
  PDF/demo submissions and saved reads require no extra lookup. TXU downloads do
  not publish to Pinecone or change the assistant corpus.
- TXU-07: Verify response contracts, matching ZIP propagation, multi-utility and
  empty results, malformed/mismatched responses, redirects and size limits,
  unchanged/changed EFLs, missing-credit safeguards, unit conversion, refresh
  failure/expiry, ZIP isolation, duplicate tariffs, local-sync preservation,
  deterministic costs, API snapshots and frontend stale-response handling.
  Record live verification and any unavailable-provider limitations honestly.

Implementation: TXU-01–TXU-07 are implemented for explicit discovery, cached
availability, controlled EFL ingestion, existing reviewed-parser validation and
comparison/UI integration. No new TXU tariff layout has been approved; unfamiliar
or incomplete EFLs remain review-required. The supported comparison path is tested
with a scripted reviewed tariff, not represented as a verified live TXU price.

Verification 2026-09-12: all 81 Python tests and 23 JavaScript DOM-stub tests passed;
JavaScript syntax and git diff --check passed. Tests include 14 TXU-specific Python
methods and five new browser-script cases. A final live sync queried both 79756
and 78681 using their returned Oncor utility, saving 43 listings per ZIP (86
associations), with no listing failures and all 86 excluded from calculation.
There were 43 distinct EFL URLs across the ZIPs: the shopping host returned 28
non-PDF responses; the legacy www host redirected to residential.txu.com and
provided 15 PDF files. Thirteen parsed into review-required records, and two were
rejected by existing page text-length checks. Fourteen listings per ZIP were
hidden by TXU. No unavailable, hidden or unreviewed offer was ranked.

HTTP TestClient verification against the populated local cache returned 200 for
both ZIP lookups and the hash-checked local document endpoint; each ZIP exposed
13 distinct local EFL links. New TXU comparisons correctly returned actionable
422 errors because no offer passed the full gate. Scripted comparison tests
verified $162.31/month and $1,947.72/year at 1,000 kWh/month, utility selection,
ZIP isolation, deduplication, source snapshots and retrieval after withdrawal.
Existing reviewed local-PDF fixture tests intentionally skip managed downloads.
A downloaded Simple Rate 24 EFL page was rendered and visually inspected; it
omits numerical TDU charges and its offer is hidden. No live tariff was approved,
no model or Pinecone operation was used, and no full browser visual test was run.
See smart-power-plan-advisor/docs/txu-integration.md for usage and limitations.

## 21. Cross-platform combined data update — implemented

Requested 2026-09-12. Add one Python entry point, `update_data.py` in the inner
application directory, to update the SQLite catalog and the existing RAG index.
This extends CATALOG-02 and RAG-04; the separate existing CLIs remain available.

- UPDATE-01: Use portable Python/pathlib and the current Python interpreter;
  no Bash, PowerShell activation, shell subprocess, or platform-specific path
  assumptions. Paths default to the application directory regardless of launch
  directory. Load its existing `.env` by default, with environment variables
  taking precedence, and support explicit env/data/SQLite/manifest paths.
  Honor PLAN_DATA_DIR in RAG Settings as well as the existing catalog configuration;
  custom script paths require the server to use matching paths.
- UPDATE-02: Before writes or provider calls, check ingestion dependencies, both
  credential presence (never values), existing data directory, distinct output
  paths and ZIP syntax. `--check` prints a read-only configuration/dependency/file
  summary; it does not create files, extract PDFs, call providers, validate live
  credentials or modify either store. Missing packages identify the exact Python
  environment and the requirements-rag.txt installation command.
- UPDATE-03: An optional repeatable `--zip` refreshes TXU SQLite snapshots first;
  absent ZIPs do not fetch TXU. Then prepare RAG documents, incrementally sync
  ordinary local PDFs to SQLite (retry prior failures), and publish the prepared
  RAG corpus using existing embedding, index compatibility and atomic-manifest
  code. Preserve original relative source paths and citations. No implicit index
  creation, namespace deletion, credential changes, or modification of pricing
  validation/eligibility. Report TXU saved/blocked counts separately.
- UPDATE-04: The combined command excludes reserved `_txu/` downloads from RAG
  by default. `--include-txu-rag` explicitly includes them as document evidence,
  not proof of current offer eligibility. Preserve the strict RAG page validation:
  unreadable documents fail preparation with a source-specific error, never get
  silently skipped or published as a partial replacement corpus. Existing RAG CLI
  discovery is unchanged; extend build_corpus with optional explicit source paths
  for this command, including case-insensitive PDF discovery and root validation.
- UPDATE-05: If the prepared manifest exactly matches the active local manifest,
  skip redundant embeddings/upserts and report `unchanged`; this does not verify
  remote index contents. `--force` reextracts catalog files and republishes RAG.
  `--refresh-tdu` forwards the existing explicit delivery-rate refresh option.
  Verify prepared source hashes before publication and again after upserts before
  activating the local manifest; changed files fail the run. Extend the existing
  publisher with an optional pre-activation check; other callers stay unchanged.
- UPDATE-06: Serialize combined runs sharing a manifest using the existing
  Windows/POSIX lock helper. Print progress and a structured stage summary; return
  nonzero for failed stages, distinguish not-started/updated/unchanged/partial,
  sanitize provider errors and close resources on errors. SQLite and Pinecone
  are not a distributed transaction: completed SQLite changes remain if RAG fails,
  but the old active manifest survives failed upserts. A rerun retries the work.
- UPDATE-07: Document exact macOS and Windows setup/check/update commands, optional
  TXU scope, existing index prerequisite, external embedding/upsert costs and
  partial-failure semantics. Verify preflight without mutation, path independence,
  optional TXU flags, ordering, unchanged/forced publishing, excluded TXU documents,
  source changes, failures/resource cleanup, and existing regressions using mocked
  provider calls. Record native OS and live-provider verification limits honestly.

Implementation: UPDATE-01–UPDATE-07 are implemented in `update_data.py` and
`backend/update_data.py`, with optional source selection and pre-activation checks
in the existing RAG helpers. Existing standalone ingestion defaults are preserved.
README and `docs/update-data.md` include explicit commands for both operating
systems and distinguish configuration checks from real updates.

Verification 2026-09-12: all 103 Python tests and 23 JavaScript tests passed;
git diff --check passed. Fourteen new updater tests cover read-only preflight,
configuration/path resolution, existing env precedence, same-interpreter package
guidance, source containment/uppercase PDFs, stage ordering, optional TXU scope,
unchanged/forced RAG, partial SQLite failures, provider errors, source mutation
during upserts, resource closure, and preservation of the prior manifest. A real
uppercase-named PDF retains working source citations. Native macOS checks using
the inner application venv succeeded both from the application folder and from
an unrelated working directory. Read-only preparation selected all 22 ordinary
PDFs into 59 chunks, excluding managed TXU downloads. Declared RAG dependencies
were installed into that venv; existing key presence was checked without revealing
values. No live embeddings, Pinecone mutations or production SQLite update were
performed for this task. Windows execution was not available: the script uses
portable Python paths and the existing Windows/POSIX lock implementation, with
Windows invocation documented but not claimed as natively tested.

## 22. Shared catalog API pricing flow — implemented

Requested 2026-09-12. This supersedes section 20's mandatory TXU EFL comparison
gate. Extend CATALOG-02: PDF extraction and provider APIs both feed the SQLite
catalog; the catalog API and comparison engine consume the same structured plan
contract. RAG remains a document evidence path, never a price calculator.

- FLOW-01: Expose `/api/catalog/records` and `/api/catalog/records/{id}` with a
  versioned, source-independent contract: identity/revision, provider, area,
  contract term, recurring components with explicit units and usage boundaries,
  examples, eligibility/issues, and source provenance. Preserve all extracted PDF
  fields and the complete TXU offer in source details. Existing PDF audit/document
  endpoints remain compatible. Use SQLite's existing immutable revisions and TXU
  refresh snapshots as storage; a shared adapter projects these into API records.
  Reads require no PDF access, extraction, provider fetch, RAG or model call.
- FLOW-02: Comparison must consume precisely these API records through the same
  server-side catalog service (no self-HTTP request, client-supplied rates or
  direct PDF extraction objects). Preserve `pdf` and `txu` source filters, ZIP and
  utility selection, deterministic Decimal arithmetic, PDF validation outcomes,
  source citations and saved comparisons. PDF validation occurs at ingestion;
  deleting a PDF after ingestion does not prevent calculation from stored terms.
- FLOW-03: TXU sync stores complete API offers and validates API pricing directly.
  EFL downloads become optional (`--download-efls`), with separate document issues
  that do not determine API pricing eligibility. Support complete fixed flat
  tariffs covering at least twelve months: four explicit recurring charges and
  reconciled 500/1000/2000 kWh examples. Reject missing/duplicate/invalid rates,
  unrecognized rate types, unmodeled credits, usage conditions, interval/seasonal
  or solar rules. Never derive a tariff from average prices or marketing text.
  Availability/hidden flags, 24-hour freshness, failed refresh invalidation and
  ZIP/utility isolation remain mandatory. Old cached raw offers use the same new
  adapter without re-downloading documents or changing their freshness timestamps.
- FLOW-04: All PDF fields remain accessible as source details, including unsupported
  rules and evidence. Unsupported records are visible but excluded from ranking.
  API provenance identifies its URL, snapshot timestamp/hash and external offer;
  never invent a PDF page, quote or issue date for provider API data. Distinct
  external offer IDs remain distinct API records. Comparison source links use
  the catalog record endpoint; PDF documents remain optional evidence links.
- FLOW-05: Update UI labels and documentation to explain PDF/API → SQLite catalog
  API → comparison, alongside PDF → RAG for explanations. Existing source choices
  select the ingestion origin, not a separate calculation path. Combined updater
  must retain explicit optional TXU PDF ingestion for RAG. No public write endpoint
  is introduced; existing local sync commands are the trusted ingestion boundary.

Acceptance: tests demonstrate identical API/comparison terms and revisions for
both sources, PDF-independent comparisons, no mandatory EFL calls, correct direct
API cost ($162.31/month at 1,000 kWh for the fixed-rate fixture), incomplete rules
excluded, old raw snapshots reusable, source isolation/freshness and retained
saved results. Run relevant Python and UI regressions; record actual verification.


Implementation: FLOW-01–FLOW-05 are implemented. `backend/catalog/records.py`
projects existing SQLite PDF revisions and TXU snapshots into `catalog-v1` records.
The records API and comparison use the same service and recurring-component model;
comparison no longer constructs PDF extraction objects. Complete API tariffs use
API provenance, while optional EFL ingestion records document issues separately.
The existing `pdf`/`txu` choices now identify catalog ingestion origins in the UI.
The combined updater requests optional PDFs when TXU RAG inclusion is selected.
README, `docs/data-flow.md`, catalog, TXU and updater guides describe the flow.
No additional database migration or public write endpoint is needed.

Verification 2026-09-12: all 109 Python tests and 23 JavaScript DOM-stub tests
passed; JavaScript syntax and git diff --check passed. Six new contract tests
cover both source adapters/API/comparison parity, PDF-independent pricing,
legacy raw snapshots with obsolete EFL errors, unchanged freshness, source
withdrawal/versioning, unsupported PDF rules, and fourteen malformed/incomplete
API pricing cases. Existing TXU tests now verify optional EFL ingestion/security
without gating API pricing, distinct offer identities, failed/expired/empty
refreshes, ZIP/utility isolation and immutable saved comparisons. The combined
updater test confirms explicit TXU RAG inclusion requests PDF downloads.

A SQLite backup of the populated local catalog was exercised through FastAPI
TestClient without modifying production data or calling external providers.
Each of ZIPs 79756 and 78681 returned 43 TXU records, two eligible, and successful
HTTP 201 comparisons: Simple Value 24 ($1,947.72/year) and Simple Rate 12
($1,995.72/year), each at 1,000 kWh/month. Source revisions matched the catalog
record endpoints. These are estimates from existing cached API snapshots, not a
new live-price verification. The same catalog exposed 20 ordinary PDF records,
nine eligible. No PDFs were downloaded, no embeddings or Pinecone writes occurred,
and no native Windows or full browser visual test was performed in this change.

## 23. Compare both catalog sources — implemented

- FLOW-06: Remove the UI's "Plans to compare" source dropdown. Every new UI
  comparison requests `data_source: "catalog"`, combining eligible ordinary PDF
  imports and TXU API imports. Demo and individual-source API modes remain backward
  compatible; reopening an old saved result preserves its snapshot, but a new
  submission uses both real sources.
- FLOW-07: Combine only records for the same delivery area. A fresh TXU utility
  lookup can resolve the ZIP's area for PDF imports, including ZIPs absent from
  the static mapping. Multiple utilities still require explicit selection. Missing,
  failed or stale TXU caches must not prevent comparison of PDF plans for a known
  static ZIP; unavailable TXU data must not enter ranking or establish a new ZIP
  mapping. Report that limitation in assumptions. No eligible source produces an
  actionable error; never fall back to demo. Retain separate source identities.

Acceptance: UI submits both sources without a source control, retains utility
selection and edit/race guards, and loads old saved comparisons. API tests verify
mixed results, utility/area isolation, PDF-only and TXU-only availability, stale
TXU exclusion, missing-area rejection and unchanged legacy modes.


Implementation and verification: FLOW-06–FLOW-07 are implemented in the UI and
shared catalog comparison service. All 112 Python tests and 24 JavaScript tests
passed. Three new API tests verify combined results, fresh utility-based ZIP
resolution, area isolation, PDF-only and TXU-only results, stale/missing-cache
handling and multi-utility selection. UI tests verify absence of the dropdown,
`catalog` submissions, cached utility selection, stale/blocked TXU fallback to
PDF comparison, saved-result loading and edit/race guards. Documentation now
matches the automatic combined flow. No live provider calls, database refreshes
or native browser visual verification were performed for this change.

## 24. Assumption-based cost comparisons — implemented

- ESTIMATE-01: Add a separate persisted `rough_estimates` result list for excluded
  PDF and TXU catalog plans where sufficient trustworthy numerical inputs exist.
  Never promote estimates into recommendations, baseline choices, savings or
  best-plan rankings. Hidden/inactive TXU offers may appear only as explicitly
  hypothetical estimates. Stale/failed TXU snapshots cannot supply rough prices;
  retain ZIP/utility matching. Existing saved results lacking the field still load.
- ESTIMATE-02: Free Pass 12 with complete unambiguous API recurring charges uses
  a versioned seven-free-days scenario: each supplied month is treated as a 30-day
  cycle, uniform daily consumption, energy charge waived for 7/30 of usage; base
  and all delivery charges remain. These are unverified assumptions, not extracted
  contract rules. Round the final monthly total once to cents, then sum 12 months.
- ESTIMATE-03: Other excluded fixed plans covering twelve months can use valid
  published 500/1000/2000 kWh examples. Convert each average into a benchmark bill;
  linearly interpolate total bills between benchmarks. Outside the range, multiply
  usage by the nearest benchmark average rate and prominently mark extrapolation.
  No inferred credit/free-time entitlement or itemized charge breakdown. For PDF
  records reject invalid source/example evidence; for API records validate examples
  independently of duplicated/missing component rates. Never estimate from absent,
  duplicated, negative, non-finite or malformed examples. Other Free Pass records
  without a complete scenario input can use the generic example method.
- ESTIMATE-04: Show monthly/annual rough totals, original pricing exclusions, source
  revision/link, availability, explicit formula/method, and notes that examples may
  assume a different usage pattern (including solar exports), miss threshold jumps,
  and exclude taxes/nonrecurring costs. Hold rates constant for twelve months.
  Allow a successful comparison containing only rough estimates, with no winner.
  Show the assumptions directly in the rough-estimate section and preserve them
  when loading saved results. Full calculators and eligibility remain unchanged.

Acceptance: independent formula/interpolation/extrapolation checks, invalid-input
rejection, fresh utility isolation, hidden/stale handling, mixed and rough-only
results, no recommendation contamination, saved reload and visible UI notes.

### Section 24 refinement after plan-by-plan review — implemented

The user expanded scope to every current plan and reusable future-provider rules,
and selected editable assumptions. This supersedes ESTIMATE-02's single Free Pass
preset and ESTIMATE-03's fixed-plan-only fallback. Audit every distinct local PDF
catalog plan and current TXU offer; record source fingerprints, observations,
missing terms and selected methods in a checked-in review registry/report.

- ESTIMATE-05: Use a provider-independent scenario engine with reviewed profiles
  for recurring rates/threshold credits, marginal tiers, free-usage shares,
  seasonal energy discounts/credits, solar export credits, non-bill rewards,
  variable/short-term projections and benchmark bills. Provider adapters bind
  reviewed profiles to source fingerprints; never select a billing rule from a
  name/keyword alone at runtime. Changed/unreviewed sources use only validated
  benchmark estimates and a review-needed note. Unknown or invalid inputs stay
  excluded. Future providers can bind the same schema without new calculators.
- ESTIMATE-06: Publish per-record rough-estimate capability, method, notes and
  editable parameter definitions in the catalog API. Accept per-plan numerical
  overrides with server-side range/unknown-field validation; reject stale or
  unsupported override IDs. Defaults and edits are visible and persisted in the
  comparison result. Rough-only results and historical reload work in the UI.
- ESTIMATE-07: Only use unambiguous positive recurring API rates for component
  scenarios; zero placeholders or duplicate rates fall back to independently
  validated benchmark examples. For reliable PDF credit thresholds, benchmark
  interpolation adds the known credit back before interpolation and subtracts
  the applicable credit afterward, avoiding a fictitious smooth credit threshold.
  Short/variable plans explicitly assume unchanged prices after term/first cycle,
  with an editable price-change scenario, never a twelve-month price guarantee.
- ESTIMATE-08: Free Pass API and linked EFL conflict in both rate and waiver terms.
  Keep the API illustration explicitly hypothetical (editable free-use share and
  delivery waiver); cite the conflict in notes. Do not merge numerical terms from
  different source revisions. Reliant overnight/Flextra profiles may use reviewed
  same-document rates and the stated 32% example share with both energy and
  per-kWh delivery waived, retaining fixed delivery. Tiered Reliant EFL profiles
  use marginal tiers as supported by their benchmark calculations.
- ESTIMATE-09: Solar scenarios treat entered usage as grid imports, separately
  assume exports/buyback rate, floor bills at zero and explicitly omit rollover.
  Missing export compensation is an editable assumption, never inferred from a
  green-energy label. Non-bill reward realization defaults to zero. Unsupported
  fees/unknown splits can only use benchmark estimates, with no invented breakdown.
  Preserve full verified ranking semantics; all new profiles remain rough-only.


Implementation: ESTIMATE-01–ESTIMATE-09 are implemented with the later refinement
superseding the initial narrow Free Pass proposal. `plan_reviews.json` records 63
reviewed snapshots, their source fingerprints, selected scenarios, notes and
original issues; `docs/plan-rule-review.md` documents every plan and the cross-plan
findings. `rough.py` supplies shared formulas, strict override ranges, benchmark
validation and source-change fallback. Catalog records expose capabilities and
comparison snapshots retain estimates, formulas, notes, parameters, availability
and source revisions. UI controls recalculate through the server and invalidate
old assumptions on ZIP/utility changes; rough plans never enter ranking/baselines.

Verification 2026-09-12: 121 Python tests and 26 JavaScript DOM-stub tests passed.
Tests cover independent free-usage, threshold, seasonal, marginal-tier, solar,
reward, future-price, interpolation and extrapolation arithmetic; malformed
examples/overrides; source changes and reusable provider-independent profiles;
rough-only/mixed API results; hidden/stale exclusion; persistence; and editable
UI controls with saved-result restoration. Git diff --check and JS syntax passed.
All 63 source records were inventoried and reviewed. Local PDF text and stored
source facts were inspected; first pages of Free Pass 12, Reliant Overnight and
Reliant Get More Save More 36 were rendered and visually reviewed. No live price
refresh was performed, and missing/unavailable EFL terms remain explicitly unknown.

Integration verification used a backup of the populated SQLite catalog. Both
79756 and 78681 returned HTTP 201 with 11 calculated plans and 52 separate rough
estimates at 1000 kWh/month. The Free Pass API illustration produced $155.71/month
and $1868.52/year; changing free usage to 40% and delivery waiver to 100% produced
$1418.88/year. All rough source revisions matched the catalog record endpoints,
and saved results were unchanged after edits. These are hypothetical results from
cached snapshots, not live tariffs or verified customer bills. No production
SQLite/RAG changes, model calls, or full native-browser visual test were performed.

## 25. Preserve independent TXU fields during normalization — implemented

- TXU-DATA-01: A duplicate, invalid or unsupported rate must not discard other
  independent valid rates. Normalize known rate types separately. Preserve all
  original data in source_details; omit only an ambiguous/invalid normalized type,
  never choose a duplicate value. Retain valid examples, base and delivery charges.
- TXU-DATA-02: Identify the exact invalid/duplicate type. Distinguish genuinely
  absent entries from invalid or ambiguous entries. If recurring inputs are
  incomplete, expose existing examples with price_checks marked not_checked rather
  than falsely missing or reconciled. Unknown types/applicability fields continue
  to block exact ranking; partial normalization never grants eligibility.
- TXU-DATA-03: Existing cached snapshots are repaired in the read projection without
  changing raw responses, refresh timestamps or reviewed rough profiles. Preserve
  unit conversion, exact ranking and rough-estimate outcomes. Verify raw-to-public
  equality and all independent fields for both cached ZIPs using a database copy.

Acceptance: duplicate energy retains three examples and the other three charges;
malformed/duplicate example isolates just that example; true absence is labeled
missing; units remain Decimal-safe; incomplete prices stay excluded, rough results
and source history remain unchanged, and existing suites pass.


Verification: TXU-DATA-01–TXU-DATA-03 implemented in the catalog adapter.
The root cause was all-or-nothing normalization: normalized_rates raised for an
ambiguous EnergyCharge, leaving the caller's entire rates map empty. The adapter
now groups and validates each rate type independently while the strict helper's
existing behavior remains compatible for other callers.

All 123 Python tests passed. New tests cover duplicate energy, invalid/duplicate/
absent examples, unknown types and applicability fields, preserving independent
rates, raw data and rough support, and explicitly not-checked price comparisons.
TestClient verification against a SQLite backup confirmed all 86 raw offer records
unchanged, all 258 normalized examples retained, original refresh timestamps
unchanged, and repaired output for Saver's Choice 12, Solar Saver 12, Value Edge 12,
e-Saver 10 and e-Saver 12 in each ZIP. Each combined comparison still returned
11 calculated plans and 52 rough estimates. No provider requests or production
SQLite changes were required. git diff --check passed.

## 26. Sequential validated-only import — implemented

- IMPORT-01: Add `catalog.cli import-validated` for the clean rebuild. Discover PDFs
  sequentially in deterministic path order, or accept repeated `--file` selections
  within the configured data root. Preserve all source files. Use reviewed parsers
  only; no model fallback. Default is offline; approved TDU enrichment is explicit
  via `--refresh-tdu`. Unknown layouts and missing/unsupported terms are rejected.
- IMPORT-02: Validate all existing identity/evidence/rate/term/example checks before
  publishing. Recheck file hash. Commit the validated revision and source association
  in one SQLite transaction. No rejected revision/source is inserted. Withdraw a
  previous active association if its selected file now fails, preserving historical
  valid revisions. Unselected files remain unchanged. Managed `_txu/` documents
  cannot establish ZIP availability; log them as skipped rather than import them.
- IMPORT-03: Persist one flushed JSONL event per file with sequence, path, hash,
  name if known, outcome, stage, exact validation issues, warnings, price checks,
  revision ID and time. Produce summary JSON and readable Markdown issue report.
  Continue after per-file failures; logging/DB/infrastructure failures stop the run.
  Serialize writes using the catalog lock. Report counts separately, and return
  nonzero for rejected files without rolling back independently imported good files.
- IMPORT-04: Tests cover good/bad/good order, no rejected rows, atomic publication,
  repeat imports, source mutation, previous-source withdrawal, scoped selection,
  unknown/managed sources, full issue logs and no model/provider calls by default.
  Run this importer against preserved local sources after tests, verify every
  published catalog record is eligible, and report real outcomes and log locations.
  RAG, remote Pinecone and TXU availability remain untouched. Existing diagnostic
  sync commands retain their behavior; document this strict command for clean runs.


Implementation and verification: IMPORT-01–IMPORT-04 implemented in
`catalog/validated.py` and exposed as `import-validated`, with README and dedicated
guide. All 129 Python tests passed, including six new tests for mixed valid/invalid
order, complete logs, idempotent selected imports, withdrawal, unknown/managed
sources, no default model/network calls, source mutation, transaction rollback
and path containment. git diff --check passed.

The real offline run processed all 112 preserved PDF files sequentially:
9 source files imported, 13 rejected and 90 managed TXU PDFs skipped. Nine valid
revisions/sources produce 8 distinct plans after existing semantic deduplication.
Both catalog APIs returned exactly 8 records, all calculation_eligible=true; SQL
confirmed no revision with validation issues. TXU refreshes remain empty. The
run journal has one event for every file, with exact issues, warnings and checks.
Logs: `.data/import-logs/2026-09-13T003833.158945_0000-dfb4bc05/` in the inner app.
Rejected reasons include missing delivery rates, short/variable terms, interval,
tiered and seasonal rules. No model, provider, RAG or Pinecone call occurred.
Source PDFs and the reset backup were preserved. Native Windows execution was
not available; implementation uses portable pathlib and existing OS lock helper.

## 27. Reviewed Flextra estimate import — implemented

- IMPORT-05: Recognize the separately stated Oncor monthly delivery charge with
  page evidence. Do not infer missing values or require a website when the PDF
  already supplies both delivery charges.
- IMPORT-06: Add explicit `import-validated --allow-reviewed-estimates`. Default
  strict imports remain unchanged. An estimate import requires an explicitly
  approved, fingerprint-matched review, complete valid source evidence and rates,
  only the review's allowed exact-calculation limitations, and all three published
  examples reconciled within the existing 0.15 cent tolerance using reviewed
  assumptions. Unknown/changed sources, missing facts and other issues still fail.
  Persist exact-calculation limitations so estimates never enter exact ranking;
  log estimate mode, assumptions and assumption-based checks separately.
- FLEXTRA-01: Approve only the inspected Flextra PDF snapshot initially. Use energy
  21.5394 cents/kWh, delivery 6.0295 cents/kWh, fixed delivery $4.06 and base $0;
  default editable free usage 32%, delivery waiver 100%. Notes describe two highest
  days per Sunday–Saturday week, billing-period caps/proration and fixed charges.
  Exact daily allocation is not modeled. Existing rough API/UI handles estimates.

Acceptance: source $4.06 extracted; strict mode still rejects free-day pricing;
explicit reviewed mode imports as rough only; 500/1000/2000 checks pass; edited
assumptions change costs; missing rates, changed fingerprint or bad examples reject.
Reimport only the selected PDF, preserve source/history and update the original
report with reconciled counts and explicit exact-versus-estimate classification.

Verification: IMPORT-05, IMPORT-06 and FLEXTRA-01 implemented. All 130 Python
tests passed, including source-charge extraction, strict rejection, reviewed-only
acceptance, source fingerprint mismatch, missing rates/facts, changed examples,
idempotence and editable assumptions. API integration against the real catalog
returned 10 records, with 9 exact comparison results and 1 rough Flextra estimate
at $191.53/month for 1,000 kWh; a 40% free-share override changed its cost. Test
comparisons used temporary storage. Backed up SQLite before selected reimport;
source PDFs and prior reports/journals preserved. Original report reconciled to
12 imported PDFs (9 exact plans + 1 estimate after dedup), 10 rejected, 90 skipped.
No provider, RAG, Pinecone or model calls were needed. Native UI was not retested;
existing rough-assumption API/UI contract is unchanged.

## 28. Reviewed nine-month contract import — implemented

- SHORT-TERM-01: Approve the inspected Reliant Power Savings 9 snapshot for the
  existing explicit reviewed-estimate import path. Preserve term_months=9 and
  validate all source charges, the inclusive 1,000 kWh $75 credit and examples.
  Use the actual flat tariff, not interpolation: energy 12.9674 cents/kWh,
  delivery 6.0295 cents/kWh plus $4.06/cycle and zero base.
- SHORT-TERM-02: A shorter contract is not bad source data. The existing annual
  comparison still requires an estimate after expiry: apply editable percentage
  change to the monthly bill only after month 9, default zero change with explicit
  unknown-renewal-pricing notes. Do not imply a 12-month guaranteed tariff or add
  early termination fees when modeling completion of the full nine-month term.
  Unreviewed snapshots and other validation failures remain rejected.

Acceptance: selected import succeeds with preserved nine-month term, all price
examples pass; credit activates at 1,000 kWh; post-term adjustment affects only
months 10–12; fingerprint changes reject. API exposes reviewed flat estimate,
not exact annual ranking. Update original report and preserve backup/history.

Verification: SHORT-TERM-01–02 implemented as a reviewed source profile using
the existing flat calculator and explicit import gate. Eight validated-import tests
passed, including the new nine-month source/credit-boundary/post-term-adjustment
regression. Real SQLite reimport accepted the selected PDF after backup. API
verification returned 11 records and 9 exact + 2 rough comparison results; the
9-month term is retained and a +20% adjustment changes only months 10–12. Test
comparisons were isolated in temporary storage. The original report now records
13 imported source PDFs, 9 rejected and 90 skipped. No provider/model/RAG calls
or native UI checks were needed.

## 29. Explicit block-tier energy tariffs — implemented

- TIER-01: Accept a single flat energy charge when no tiers are stated. Also accept
  explicitly parsed marginal/block energy tiers, represented as `energy_tier`
  components (cents_per_kwh with source-backed lower/upper kWh boundaries). Never
  manufacture tiers, interpret whole-usage bands as marginal tiers, or bypass
  incomplete charges. Recognize the reviewed Reliant 0–1000 / >1000 PDF layouts.
- TIER-02: Require tiers to cover zero through unlimited usage contiguously, with
  positive-width nonoverlapping blocks and no mixed flat/tier energy charges.
  Charge only consumption within each block. Existing flat rates, credits and
  delivery calculations stay unchanged. Shared catalog API and comparison use
  the same explicit component semantics; only fully validated plans enter exact
  ranking. All three published example checks must pass.
- TIER-03: Document import rules for flat, explicit tiered and reviewed-estimate
  plans. Reimport the two reviewed Reliant tier PDFs individually after checks.
  Reconcile the original report from journals, show current SQLite import status,
  charges and example checks for every imported file; preserve report history.

Acceptance: both 12/36-month tier plans validate and compare exactly; boundary
calculations at 0/999/1000/1001/2000 work; malformed/mixed tiers reject; flat-rate
regression stays valid. No source PDF changes, invented rates or external calls.

Verification: TIER-01–03 implemented in parser, component schemas, validator and
shared calculator. All 134 Python tests passed, including both real tier sources,
0/999/1000/1001/2000 boundaries, flat-rate regression and malformed/mixed tier
rejection. Both selected PDFs imported strictly after SQLite backup. API verified
13 records, 11 exact annual results and 2 reviewed estimates. Tier totals were
checked through the API at 1,000/2,000 kWh; comparison test writes were isolated.
All 15 imported source entries in the original report now include active SQLite
charges, contract terms, revisions, assumptions where needed and price checks.
Reconciled totals: 15 imported PDFs, 7 rejected, 90 skipped; 13 distinct plans.
Source PDFs, journals and prior report preserved; no provider/model/RAG calls.
README and import guide describe flat versus block-tier handling. Native UI was
not retested. git diff --check passed.

## 30. Reviewed overnight import — implemented

- NIGHT-01: Recognize the reviewed Reliant daytime delivery label even when PDF
  extraction places its numeric rate before the final word Charges. Retain the
  quoted source evidence. Missing or ambiguous rates are never inferred.
- NIGHT-02: Explicitly approve the inspected Free Overnight 12 source fingerprint
  for `--allow-reviewed-estimates`: daytime energy 18.5982 cents/kWh, daytime
  delivery 6.0295 cents/kWh, fixed delivery $4.06 and base $0. Free hours are
  9 p.m.–6 a.m. daily; both variable charges are zero then. Default editable free
  usage is the EFL's 32%; variable delivery waiver 100%. Fixed delivery remains.
  Annual results are estimates, not exact rankings; no invented interval usage.
  Only matching reviewed sources passing all evidence and example checks import.
- NIGHT-03: Document this class of reviewed free-time plans, back up SQLite,
  import the selected PDF and refresh all imported report entries from SQLite.

Acceptance: correct charges with source quotes, three assumption-based examples
pass, strict import still rejects interval pricing, reviewed import succeeds,
changed source/missing rates reject, editable free share changes comparison cost.

Verification: NIGHT-01–03 implemented. All 135 Python tests passed, including
source delivery extraction, strict rejection/reviewed acceptance, fingerprint and
missing-rate rejection, all examples and edited free usage. Backed up SQLite and
imported the selected overnight PDF. API returned 14 plans and 11 exact + 3 rough
results. Overnight cost at 1,000 kWh was $171.53; a 40% free-share scenario gave
$151.83. Test comparisons used temporary storage. All 16 imported file entries
were refreshed from SQLite in the original report (6 rejected, 90 skipped remain).
Report history and sources preserved. No external/provider/model/RAG calls or
native UI checks. Import instructions updated; git diff --check passed.

## 31. Reviewed month-to-month variable import — implemented

- VARIABLE-01: Parse and preserve the literal evidenced `Month to Month` contract
  term; expose it as `contract_term` in PDF catalog records with term_months=null
  rather than inventing a fixed term. Missing contract terms remain invalid.
- VARIABLE-02: Approve the inspected Reliant Clear Flex snapshot only through the
  explicit reviewed-estimate gate. Use stated energy 12.3174 cents/kWh, delivery
  6.0295 cents/kWh plus $4.06/cycle, and $9.95 usage charge below 800 kWh, zero
  at/above 800. Extend the flat rough calculator with reviewed conditional usage
  charges, preserving existing profiles. No unspecified extra base fee is assumed.
- VARIABLE-03: Apply editable bill-change percentage from month 2 onward, default
  0%; notes explain first-cycle pricing, unknown future rates, threshold fee and
  no termination fee. Keep outside exact annual ranking; all evidence and three
  examples must pass and reviewed source fingerprint must match.
- VARIABLE-04: Document variable-plan import, back up SQLite, import selected PDF,
  refresh every imported entry in original report with current source/term/checks.

Acceptance: month-to-month source and API term preserved; strict rejects variable
pricing; explicit reviewed import succeeds; 799/800 usage threshold and first-cycle
versus later price adjustment tested; missing term/changed source rejects. API
comparison retains assumptions and notes; no source PDFs or prior history lost.

Verification: VARIABLE-01–04 implemented. All 136 Python tests passed, including
month-to-month extraction, missing-term/source-change rejection, strict rejection,
reviewed import, 799/800 fee boundary and post-first-cycle adjustment. Backed up
SQLite and imported the selected PDF. API verified 15 records, 11 exact + 4 rough
results and literal contract_term with null term_months. At 1,000 kWh, first-cycle
cost is $187.53; a +20% scenario changes only months 2–12 to $225.03. Comparison
test saves were isolated. Refreshed all 17 imported file entries from SQLite in
the original report (5 rejected, 90 skipped). Sources and history preserved. No
provider/model/RAG calls or native UI checks. git diff --check passed.

## 32. Independent PDF and provider-API sources — implemented for strict PDF import (section 33)

- SOURCE-01: PDF-derived plans and provider-API offers are independent source
  records, including when both name TXU. Do not join, merge, overwrite or fill
  pricing fields across those sources based on name, provider or folder. A shared
  catalog endpoint or comparison view does not make them one source record.
- SOURCE-02: PDF validation uses its own document evidence, supported explicit
  delivery lookups and reviewed assumptions. No provider API offer match, API
  active/hidden flag, ZIP listing or API freshness is a PDF import prerequisite.
  Preserve document-date pricing and unverified live availability. API imports
  separately validate their own rates, utility/ZIP availability and freshness;
  a PDF cannot establish or repair API-offer eligibility.
- SOURCE-03: A PDF under `_txu/` is still a PDF source. Its directory/download
  origin alone must not skip it. Apply ordinary PDF parsing, evidence, pricing
  and reviewed-estimate gates, logging actual document validation failures.
  This supersedes the managed-document skip policy in IMPORT-02/IMPORT-04.

Status: README, repository instructions and import guide updated. Runtime removal
of the existing `_txu/` skip is planned, not implemented in this documentation-only
request. Existing skipped report entries describe historical behavior and remain
unchanged; no data was imported or API-linked during this update.
Acceptance for the future implementation: a valid `_txu/` PDF imports without
provider requests/snapshots; bad PDFs reject for evidence/pricing issues; importing
one source never mutates the other; provenance and source-specific filters remain.

## 33. Free Pass 24 document benchmark import — implemented

- PDF-BENCH-01: Implement SOURCE-03 for import-validated: parse `_txu/` PDFs as
  independent documents, without provider API calls or availability prerequisites.
  Unknown layouts reject normally. Legacy diagnostic sync remains unchanged.
- PDF-BENCH-02: Approve only the inspected Free Pass 24 PDF fingerprint for a
  published-example benchmark estimate. Its missing TDU charges remain absent;
  retain the contradictory 0.000% free-usage disclosure as a warning. Record the
  seasonal 7/9-day rules and variable-charge waiver in notes. No inferred rates or
  free-usage percentage. This explicitly extends IMPORT-06: approved benchmarks
  may retain reviewed missing-rate issues, but all identity/example evidence and
  the exact approved snapshot must match. No claim of tariff reconciliation.
- PDF-BENCH-03: Benchmark checks are labeled published_benchmark (reproduction,
  not independent validation), with original exact checks retained. API exposes
  warnings and benchmark adjustment; exclude from exact ranking and live-offer
  claims. Back up SQLite and import only the selected PDF, update its report entry.

Acceptance: strict rejection versus approved benchmark import, source/identity
mutation rejection, no provider call, API PDF provenance, unchanged API offers.

Verification: PDF-BENCH-01–03 implemented. Removed folder-based skip from strict
import and PDF API projection. Added reviewed layout and fingerprint-specific
benchmark approval. All 137 tests passed, including independent `_txu/` import,
strict rejection, approved benchmark, missing-rate preservation, source mutation
rejection and no network calls. Backed up SQLite and imported only selected PDF.
API verified 16 records, 11 exact + 5 estimates; benchmark at 1,000 kWh is $171.00.
TXU refresh table remains empty; no API linking occurred. Original report updated
to 18 imported files, 5 rejected and 89 historical skips. Those other files have
not been retried. The pending status recorded in section 32 is superseded for
strict import; legacy diagnostic sync and RAG selection are unchanged. Source
PDF and report history preserved. git diff --check passed.

## Main integration September 13 — implemented and verified

Preserve incoming main contract-horizon projections, custom PDF compatibility mode
and comparison chat alongside local independent PDF/API catalog ingestion,
component-based combined comparisons and reviewed estimates. Default UI remains
combined catalog; explicit legacy PDF mode retains upstream custom pricing.
Resolve overlapping UI handlers to preserve renewal controls, utility selection,
rough assumptions and chat lifecycle. Retain all distinct tests and histories.
Acceptance: no conflicts, local work preserved, Python and UI suites pass.

Integration constraint: incoming comparison chat currently supports only explicit
PDF custom and demo comparisons. Combined catalog/TXU results must not fall through
to its demo branch. Hide chat for those modes and reject session creation clearly;
retain their existing rough-assumption controls. Extending scenario chat to the
combined source model is outside this pull reconciliation.

Integration verification: fast-forwarded feature/jagdish to origin/main c509b26
and restored local tracked/untracked work. Resolved seven overlapping files while
retaining the original stash as backup. All 161 Python tests and 42 UI tests pass.
Real catalog check returned 16 plans, 11 calculated results and 5 reviewed rough
estimates; test comparisons used temporary storage. Combined-mode chat rejects
unsupported session creation rather than using synthetic data. No unresolved Git
conflicts remain; changes are unstaged and uncommitted. git diff --check passed.

Commit portability check — implemented: store the reviewed Free Pass PDF used by the
benchmark regression as a dedicated test fixture, and point the test there so a
fresh checkout does not require ignored download-cache files. Preserve identical
PDF bytes/fingerprint and all test behavior; keep runtime caches/databases ignored.

Portability verification: all 11 validated-import tests passed with the committed
fixture path. The preceding integrated suites passed 161 Python and 42 UI tests;
only fixture location and ignore rules changed afterward.

## 34. ZIP delivery-utility discovery — implemented

- ZIP-01: On comparison submission, query a dedicated utilities endpoint that
  resolves the ZIP through TXU get_utilities, caching only utility identity/name
  for 24 hours independently of offer snapshots. Never fetch plans, import PDFs,
  or refresh offer availability as a side effect. Empty/error responses must be
  explicit; no stale success is presented as a live lookup.
- ZIP-02: Use resolved utility to filter all providers' PDF catalog plans by
  normalized delivery area and API offers by utility ID. Keep provenance/pricing
  separate. Normalize known Oncor/Oncor Electric Delivery and CenterPoint aliases;
  never guess unknown utilities. Multiple utilities require explicit selection.
  UI resolution errors stop submission rather than silently using static ZIPs.
  Existing direct comparison compatibility may use existing snapshot/static map
  only when no dedicated utility lookup has been attempted for that ZIP.
- ZIP-03: Add GET /api/catalog/utilities?zip_code=...; UI calls before comparing,
  shows selected utility, retains ZIP-change/race protection. Existing /txu cache
  stays read-only for offers. ZIP-filtered catalog records use utility resolution
  too, including PDF records when utility_id is supplied.

Acceptance: previously unmapped ZIP finds Oncor PDFs from all providers without
API offers; aliases, multiple/invalid selection, empty/error/stale cache and ZIP
race behavior tested; cached offers remain independent; no import side effects.

Verification: ZIP-01–03 implemented. All 163 Python and 43 UI tests passed.
Live TXU utilities request for 79756 returned Oncor with ID
ea0ad3a5-3fc6-4d9f-894a-e21a751c33fe. End-to-end verification on a temporary
catalog copy found 16 matching records, 11 calculated and 5 rough results; no
plan-offer fetch/import occurred. Unit checks cover independent cache, aliases,
multiple utilities, empty/error/stale lookup, no offer writes and UI ZIP races.
README updated; source records remain independent. git diff --check passed.
Native UI was not manually inspected. Changes are not committed or pushed.

## 35. Catalog comparison chat — implemented

- CHAT-CATALOG-01: Show Explore alternatives for catalog/TXU results, including
  rough-only results. Start from the saved comparison's usage, utility, preferences
  and rough assumptions. Freeze relevant shared catalog records and reviewed rough
  profiles; verify result revision/fingerprint and eligibility against the source
  before starting. Reject changed sources, never substitute demo or PDF-custom
  pricing. Scenario turns use frozen data without network/import/catalog writes.
- CHAT-CATALOG-02: Reuse component-based comparison and horizon projections for
  exact catalog candidates. Preserve rough estimates separately (12-month labeled
  illustrations, never promoted to winners). Support usage/preferences/renewal
  changes and hypothetical existing component overrides on exact candidates,
  including energy/tier rates; reject average-price overrides for component plans
  and component overrides for rough-only plans. Preserve source evidence unchanged.
  Preserve reviewed rough assumptions during usage changes and history/reset.
- CHAT-CATALOG-03: Retain auth, optimistic concurrency, atomic failure, history,
  restore and source isolation. Interpreter context exposes source/pricing mode
  and editable component indices. Existing PDF-custom/demo behavior remains.
  Explain rough-only results without claiming a recommendation. Current key reused;
  automated integration uses mocked interpretation and no paid model calls.

Acceptance: UI panel visible in catalog and TXU modes; mixed PDF/API session can
change usage, term, credit filters, component and renewal assumptions using the
same prices as normal comparison. API prices remain separate from PDF prices;
unknown targets/rough overrides fail without changing results. Rough-only results,
reset/previous, frozen-source drift and no provider access tested. No live bills,
PDFs or production saved comparisons are modified by tests.

Verification: CHAT-CATALOG-01–03 implemented. All 167 Python and 44 UI tests
passed. Added mixed PDF/API, rough-only, API-only, frozen-source drift, energy and
renewal overrides, invalid/atomic no-match and reset/previous coverage. The UI
regression confirms the panel opens for catalog/TXU results. A temporary copy of
the real catalog completed chat startup and a 36-month scenario with 11 calculated
plans plus 5 separate 12-month rough estimates; source records remained unchanged.
Tests used injected interpretation, no paid model/provider calls and no production
saved-comparison writes. Existing configured key retained. README/chat guide
updated; the earlier catalog-chat exclusion is superseded by this section.
Native browser visual QA was not performed. Changes are uncommitted; git diff
--check passed.

## 36. Unverifiable ZIP utility message — implemented

- ZIP-04: Distinguish malformed/incomplete TXU utility data (blank names, invalid
  IDs, duplicate entries or malformed response) from transient connection errors.
  Invalid data must reject the entire lookup, never select its remaining named
  entry. Show: "We couldn't verify the delivery utility for ZIP {zip}. The lookup
  returned incomplete or invalid utility information. Check the utility name on
  your electricity bill or confirm service for your exact address with your local
  utility. We haven't selected a provider or compared plans for this ZIP."
- ZIP-05: Retain generic retry guidance for transport/provider outages, do not
  expose raw responses, and cache failure as unusable so it cannot enable plan
  selection. Do not hardcode PEC/AEP coverage from ZIP or claim the ZIP invalid.
  Existing HTTP error propagation displays the guidance in comparison status.

Acceptance: mocked 78641 response with unnamed entries and AEP North yields the
specific guidance, no partial utility selection; malformed IDs/JSON also classify
as data problems. Timeout retains retry guidance. Existing valid lookups work.

Verification: ZIP-04–05 implemented with a typed invalid-utilities error and safe
user guidance. Four utility tests and 14 TXU tests passed; all 45 UI tests passed.
Tests include 78641-style unnamed/AEP response, invalid IDs, whitespace-only names,
malformed JSON, timeout distinction, unusable failure cache and UI no-submission.
No live provider requests or catalog-plan writes were needed. README updated;
git diff --check passed. Changes are not yet committed or pushed.

## 37. Plan Assistant readiness recovery — implemented

AGENT-05: When Send is disabled by the local readiness check, identify each missing
prerequisite separately: provider configuration, optional dependencies, or the
active document index. Explain that SQLite catalog imports do not index assistant
documents. Provide a Check again action that refreshes readiness without clearing
the draft or conversation; hide it when ready. Do not bypass readiness guards or
trigger remote ingestion from the browser. Link the composer to its status for
accessibility. Document the existing ingestion command and its provider uploads.
Acceptance: unavailable states give specific guidance, prevent submission, and
recover after a successful status refresh while preserving the draft. Existing
conversation, clarification, retry and reset tests must pass.

Verification: all 47 UI tests passed, including missing-index submission guards,
specific setup messages and readiness recovery preserving the draft. Local
settings loaded from .env report configured=true, indexed=false; all four checked
assistant dependencies are installed. No live backend was reachable on port 8000.
No remote indexing/model calls or native browser verification were performed.
The UI recovery is implemented; subsequent authorized ingestion restored the local
corpus, as verified below in section 38.

## 38. Standalone assistant ingestion source selection — implemented

RAG-01 / UPDATE-04 revision: standalone knowledge CLI preview and ingest exclude
reserved top-level `_txu/` downloads by default, matching the combined updater.
Add `--include-txu-rag` to explicitly include these PDFs as document evidence.
Ordinary provider PDFs (including user supplied TXU PDFs outside that cache) stay
included. Preserve strict page validation and atomic publication: invalid selected
PDFs still fail preparation, without remote upserts or replacing the manifest.
Do not modify SQLite or delete PDFs. Acceptance: source-selection tests cover
normal PDF, uppercase extension and explicit cache inclusion; offline preview of
the local ordinary corpus succeeds. Supersedes the standalone discovery exception
in UPDATE-04. Correct README and RAG guide recovery commands accordingly.

Verification: 19 knowledge/CLI tests passed. Offline preview successfully prepared
22 ordinary source PDFs into 59 chunks. No page validation was relaxed. Remote
ingestion failed with ConnectError under sandbox restrictions; elevated retry was
rejected by automatic approval review because explicit authorization to upload
these 22 PDFs to OpenAI/Pinecone was required. The user subsequently explicitly
approved this upload. Retried ingestion successfully upserted 59 chunks from 22
documents and published the active manifest. An in-process HTTP check of
/api/agent/status returned 200 with configured=true, indexed=true,
dependencies_available=true and 22 documents. Remote search visibility may lag
upserts; a live generated answer and native browser were not tested. README and
RAG guide updated.


## Document agent processing-limit recovery (AGENT-07 amendment)

Status: implemented; offline regression verification complete.

Avoid premature context limits by projecting completed-turn history without old
retrieval, document-list or other non-clarification tool exchanges. Preserve user
questions, assistant answers and paired clarification calls/replies so follow-up
references remain resolvable. Keep the current logical turn, including interrupted
clarifications, intact. Fresh evidence remains mandatory for each factual turn.
The context guard counts serialized projected messages and the current evidence
payload separately and uses the larger size rather than adding duplicate source
text present in both. Retain the conservative 10,000-token stopping threshold.
When reasoning/tool budgets are exhausted with current-turn evidence and context
within the limit, use the existing citation-checked finalizer instead of terminating
the conversation. Retain at most five reasoning calls plus one finalization (six
model calls total); citation repair remains allowed only with remaining budget.
No extra retrieval or unvalidated answers. True context overflow and loops without
evidence still stop safely. API schemas and pricing remain unchanged.

Acceptance: reproduce large follow-up history and duplicated current evidence;
verify fresh scoped retrieval, preserved clarification pairs, successful finalization
after five reasoning calls, no over-budget repair, and unchanged no-evidence loop
limits. Run agent and knowledge regressions; record actual verification.

Verification: 27 agent tests and 17 knowledge tests passed, including large-context
follow-ups, clarification pairing, five-call evidence finalization, exhausted
repair budget, no-evidence loops and true context overflow. Live reproduction of
the reported request remains unverified because the triggering question and
conversation context were not supplied. No pricing or index changes.
