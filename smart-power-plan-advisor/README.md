# Smart Power Plan Advisor

Current PDF pricing (`custom-efl-v4`): Energy = usage times the mapped EFL average / 100; add PDF base/usage fees and fixed/per-kWh delivery, then subtract eligible credits. This user-authorized custom formula repeats effects embedded in published EFL averages, so it is labeled Custom estimate, not an actual tariff bill. Each plan uses its own examples and charge conditions. Original ranges remain: first price through the second threshold, preceding price at exact thresholds, highest above its threshold. Rankings, savings and scenarios use these custom totals. Renewal escalates energy/base/delivery; retain/drop applies to separate credits. Saved older results retain their original calculation; Compare plans again to apply the new formula. Catalog validation and demo calculations remain component-based.


A local demo connecting a web form, FastAPI, a JSON plan source, deterministic
pricing, and SQLite. Calculator plans and rates are synthetic; the calculator needs no API keys.

Optional **plan-document Q&A** uses Pinecone, OpenAI and LangGraph to answer questions
about EFL PDFs with page citations. It requires your OpenAI and Pinecone keys.
See [RAG setup, models, chunking and architecture](docs/rag.md). Document answers do
not change the calculator's pricing data.

## Run locally (PowerShell)

From this repository directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. **Plan Assistant** opens by default for document questions.
Select **Compare Plan Costs**, enter a supported ZIP and 12 monthly usage values,
and compare plans. Switching tabs preserves your work; saved comparison links open
the cost tab directly. Expand each result for a monthly breakdown. The saved-result
link reloads the comparison from SQLite. API documentation is at `/docs`.

For runtime-only installation, use `requirements.txt` instead.

## Validate

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check frontend/app.js
node --test tests/zip-ui.test.cjs
```

Node is only needed for the optional JavaScript syntax check; there is no frontend
build or npm installation.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Check catalog and SQLite readiness |
| GET | `/api/plans` | List demo plans |
| POST | `/api/comparisons` | Calculate, rank and save a comparison |
| GET | `/api/comparisons/{id}` | Retrieve a saved comparison |

Example comparison request:

```json
{"zip_code":"75201","monthly_kwh":[800,750,700,850,1100,1400,1600,1500,1200,950,750,850]}
```

Monetary values in comparison responses are decimal strings. The calculation
rounds monthly line items to cents and then sums monthly totals. SQLite lives at
`.data/advisor.sqlite3`; set `ADVISOR_DB_PATH` to choose another file.

## In-memory ZIP plan coverage

Enter ZIP and monthly usage, then click **Compare plans**. Supported demo ZIPs
are `75201`, `75001`, `77002` and `77007`. Coverage is an in-memory ZIP-to-plan-ID
mapping in `backend/integrations.py`; no lookup request or external service is
needed. Unsupported ZIPs return a coverage error on comparison.

The API accepts only `zip_code` and `monthly_kwh`. Delivery-area controls, the
service-area endpoint and TDU fields have been removed. Old snapshots remain
readable; results without a ZIP need one before a new comparison. Snapshots still
use SQLite. Sample coverage does not establish actual service eligibility.

## Scope and extension

This version supports fixed energy and delivery charges, base fees, and a single
inclusive monthly bill-credit threshold. It excludes taxes and switching fees.
All plans have a 12-month term. Service eligibility is not verified against an
address. This is a local, unauthenticated demo, not a live shopping service.

See the [architecture review and diagrams](docs/architecture-review.md) for a detailed
code-based assessment, request/data flows, and verified findings.
See [architecture and extension points](docs/architecture.md) for the mapping to
all six diagram layers and the features deferred to later iterations. Replace
`JsonPlanSource` through the `PlanSource` interface to add a plan feed; extend
pricing rules and their expected-bill tests together.

## Team

Team Name: Team #20


Team Members:


    Vasanth Rajesh Barre
    Sivakumar Sambandam
    Jagdish Hunnolli
    Vishwesh Patil
    Vimaleswaran Ganeshan
    Anil Bandaru

## Document ReAct agent

The page now also offers **Chat with the document agent**: contextual document
questions, iterative evidence search, clarification and page citations using
LangGraph fundamentals, OpenAI and Pinecone. It uses the same optional RAG
installation and `.env` configuration. Conversations live only in the running
process and expire after 30 idle minutes. Run one worker.

See the [agent guide](docs/agent.md) for run instructions, API contracts, graph,
limits and tests. The [implementation plan](docs/react-agent-plan.md) records the
broader proposal; the root specification identifies the delivered first increment.

## PDF plan API and ingestion

The calculator now offers **Extracted PDF plans** backed by a SQLite catalog.
To ingest new or changed PDFs under `data/`, run from this directory:

```sh
python -m backend.catalog.cli --env-file .env sync
```

Browse `/api/catalog/plans` and `/api/catalog/status`. Incomplete or unsupported
plans remain visible with exclusion reasons; the calculator never substitutes demo
rates. Unchanged files are reused. See the [catalog guide](docs/plan-catalog.md) for
filters, retry options, supported pricing, storage choices and the separate Pinecone
chat-ingestion workflow.

Missing delivery charges can now be resolved from the approved 4Change TDU page,
with dated web evidence and price reconciliation. Use
`python -m backend.catalog.cli --env-file .env sync --refresh-tdu` to refresh
dependent plans. Other provider pages require a reviewed parser; details are in
the catalog guide.


## Recommendations

Comparisons now include lowest-cost and lowest-scenario-regret recommendations,
top three, credit-threshold sensitivity, confidence reasons, optional current-plan
savings and sampled break-even conditions. Open **Recommendation preferences and
current plan** in the calculator to supply usage provenance, a contract ceiling,
and optional baseline/switching cost. See [recommendation policy and API](docs/recommendations.md).


The comparison workspace groups ZIP, plan source and monthly usage into a compact
form. Expand **Preferences & savings** for optional inputs. Results show annual
cost and average monthly cost, a shortlist, and expandable plan rows. Confidence
reasons, usage scenarios, bill credits, warnings and evidence remain available in
disclosures. The monthly average is annual cost divided by 12; actual bills vary.


Comparison period: setting the maximum contract to 24 or 36 months now ranks
eligible plans over that full period. Review the editable renewal escalation and
credit assumptions under preferences. Results separate document-term costs from
modeled renewal costs and use the same period for savings and regret. See
[recommendation policy](docs/recommendations.md) for details and legacy fields.

## Comparison chat

After comparing plans, select **Explore alternatives** to explore contracts, usage, renewal assumptions and hypothetical rates/credits. Successful scenarios update the same comparison results; invalid or failed requests retain the last result. See [comparison chat](docs/comparison-chat.md) for examples, supported actions, configuration and recovery behavior.
