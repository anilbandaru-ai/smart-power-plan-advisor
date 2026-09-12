# Thin architecture

See the [detailed architecture review and diagrams](architecture-review.md) for
component and sequence diagrams, data flows, verified findings, and proposed next steps.

The original comparison architecture below now has an optional parallel
[plan-document RAG feature](rag.md), implemented with OpenAI, Pinecone and LangGraph.
It answers cited document questions without supplying pricing rules to the calculator.

The browser calls FastAPI, which invokes the deterministic comparison service.
The service reads plans through a `PlanSource` interface, calculates each month,
sorts annual totals, and creates template explanations. The API saves the complete
result in SQLite before returning it. Saved comparisons are immutable snapshots.

| Diagram layer | Thin implementation | Later extension |
| --- | --- | --- |
| Frontend | Plain HTML/CSS/JS served by FastAPI | React or Angular with the same API |
| API | Validated plan, comparison, retrieval and health endpoints | Authentication and customer profiles |
| Core services | Monthly pricing, area filtering, ranking, template explanation | Usage scenarios, full pricing rules, RAG and bounded orchestration |
| External sources | JSON adapter with four synthetic plans | Authorized plan feeds, EFL ingestion, SMT and tariff adapters |
| Storage | Source JSON and SQLite comparison snapshots | PostgreSQL, documents, vectors and interval usage |
| Evaluation/monitoring | Independent expected-price tests, API tests, request timing logs, readiness check | Extraction/LLM evals, scheduled refresh and customer alerts |

## Supported pricing contract

Only the synthetic 12-month fixed-price plans in the repository are supported.
Rates are dollars per kWh. Each month's energy, delivery, base fee and credit
amounts round to cents using half-up rounding before summing. A credit applies
when monthly consumption reaches its inclusive threshold. Annual cost sums the
12 monthly totals. Ties sort by plan ID. This is a demonstration contract, not a
general implementation of provider billing rules.

The service never infers delivery eligibility from a ZIP code. Users manually
select a demo area. No real tariffs, offer availability or customer eligibility
are verified. The comparison path does not call RAG or an LLM. The separate document
Q&A path uses OpenAI and Pinecone; OCR, authentication, forecasts, notification
delivery and background scheduling remain unimplemented.

## Extension boundaries

1. Implement `PlanSource` for a real provider and validate its pricing fields.
   Add availability, source versions and explicit live/demo provenance before
   enabling real recommendations; current API responses are always labeled demo.
2. Extend the pricing model and independent expected-bill tests together.
3. Replace `ComparisonStore` when customer accounts and shared hosting are added.
4. Add document extraction and review before publishing extracted pricing rules.
5. Feed verified calculation outputs to an explanation provider; keep calculation
   and ranking in Python.

## Local scope

Run on loopback. This demo has no authentication: anyone with server access can
read a comparison if they know its ID. It stores only selected delivery area,
usage, costs and explanations; there is no address or account collection.
Add authentication and ownership checks before shared deployment.
