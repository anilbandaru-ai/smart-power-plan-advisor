# Smart Power Plan Advisor

Explicit legacy PDF mode uses the custom EFL formula described below. The default combined catalog uses structured component pricing.

Current PDF pricing (`custom-efl-v4`): Energy = usage times the mapped EFL average / 100; add PDF base/usage fees and fixed/per-kWh delivery, then subtract eligible credits. This user-authorized custom formula repeats effects embedded in published EFL averages, so it is labeled Custom estimate, not an actual tariff bill. Each plan uses its own examples and charge conditions. Original ranges remain: first price through the second threshold, preceding price at exact thresholds, highest above its threshold. Rankings, savings and scenarios use these custom totals. Renewal escalates energy/base/delivery; retain/drop applies to separate credits. Saved older results retain their original calculation; Compare plans again to apply the new formula. Catalog validation and demo calculations remain component-based.

A local web application connecting a browser UI, FastAPI, deterministic pricing,
and SQLite. Compare synthetic demo plans, validated PDF plans, or cached TXU
offers. The calculator and TXU sync need no API keys.

Optional **plan-document Q&A** uses Pinecone, OpenAI and LangGraph to answer questions
about EFL PDFs with page citations. It requires your OpenAI and Pinecone keys.
See [RAG setup, models, chunking and architecture](docs/rag.md). Document answers do
not change the calculator's pricing data.

## Run the UI locally

The UI is served by the FastAPI backend. **One server runs both the UI and API**;
there is no separate frontend server, npm installation, or frontend build.
Open the HTTP URL below rather than opening `frontend/index.html` directly.

### macOS / Linux

From the cloned repository root (the folder containing `spec.md`):

```sh
cd smart-power-plan-advisor
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.api.main:app --reload --reload-dir backend --host 127.0.0.1 --port 8000
```

If you are already in the application folder containing `backend/`, `frontend/`
and `requirements.txt`, skip the `cd` command. If your environment is already set
up, run only the last command.

### Windows / PowerShell

From the cloned repository root:

```powershell
cd smart-power-plan-advisor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --reload --reload-dir backend --host 127.0.0.1 --port 8000
```

Skip `cd` if already in the application folder. These commands use the virtual
environment directly, so PowerShell activation is not required.

### Open and use the UI

Keep the server terminal running, then open **http://127.0.0.1:8000/** in your
browser. Press **Ctrl+C** in the terminal to stop the server.

1. **Plan Assistant** opens by default. Document chat requires the optional
   [RAG setup](docs/rag.md), configured keys and an indexed document corpus.
2. Select **Compare Plan Costs**, enter your ZIP and twelve monthly usage values,
   then click **Compare plans**. Eligible PDF and TXU plans are included together;
   there is no source dropdown. Choose a utility only if the ZIP has multiple.
3. Populate the catalog using the sync commands below. Missing or unsupported
   data never falls back to synthetic prices. Synthetic demo comparisons remain
   available through the API using `data_source: "demo"`.


Expand a result for its monthly breakdown. Saved comparison links reload results
from SQLite and open the cost tab directly. API documentation is at
http://127.0.0.1:8000/docs and the health endpoint is
http://127.0.0.1:8000/api/health.

### Populate TXU offers for the UI

In a second terminal, from the same inner application folder, run:

```sh
# macOS / Linux
.venv/bin/python -m pip install -r requirements-rag.txt
.venv/bin/python -m backend.catalog.cli sync-txu --zip 79756 --zip 78681
```

```powershell
# Windows / PowerShell
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
.\.venv\Scripts\python.exe -m backend.catalog.cli sync-txu --zip 79756 --zip 78681
```

The extra requirements provide PDF extraction; **TXU sync does not require API
keys**. In the browser, open **Compare Plan Costs**, compare both PDF and TXU imports automatically,
enter one of the synced ZIPs and click **Compare plans**. Select a utility if
prompted. The page shows cached offers and reasons for any pricing exclusions.
Repeat sync to refresh the cache, which expires after 24 hours.

TXU pricing now uses API terms directly. Missing PDFs do not block comparison;
hidden offers and incomplete or unsupported billing rules remain excluded. See the
[TXU integration guide](docs/txu-integration.md) for details.

### Optional document chat and startup troubleshooting

For an already configured and indexed document assistant, install
`requirements-rag.txt` and add `--env-file .env` to your server command. For example,
on macOS/Linux:

```sh
.venv/bin/python -m uvicorn backend.api.main:app --env-file .env --reload --reload-dir backend --host 127.0.0.1 --port 8000
```

On Windows, use `.\.venv\Scripts\python.exe` instead of `.venv/bin/python`.
Follow the [RAG guide](docs/rag.md) for first-time configuration and ingestion.

- **`No module named backend` or missing requirements file:** run from the inner
  application folder containing `backend/` and `requirements.txt`.
- **`No module named uvicorn`:** install dependencies into the same environment
  used to start the server. From the inner application folder, run
  `.venv/bin/python -m pip install -r requirements.txt` on macOS/Linux, or
  `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` on Windows.
  The repository root and inner application folder can have separate `.venv`
  directories; installing into one does not install into the other. A `(.venv)`
  shell prompt alone does not identify which environment your command uses.
- **Port 8000 is already in use:** stop the existing server, or use `--port 8001`
  and open `http://127.0.0.1:8001/`.
- **The page loads but TXU requests fail after an update:** restart the backend
  and refresh the browser so both use the latest code.
- **Assistant is unavailable:** configure its optional dependencies, keys and
  index, or use **Compare Plan Costs** for the key-free calculator.

## Update SQLite and RAG with one script

Use the cross-platform `update_data.py` script from this application folder.
It loads your existing `.env`, updates the local PDF catalog, and publishes the
RAG corpus when it changes. Install `requirements-rag.txt` first using the same
Python environment; both configured keys and an existing compatible Pinecone
index are required for a real update.

**macOS / Linux:**

```sh
.venv/bin/python -m pip install -r requirements-rag.txt
.venv/bin/python update_data.py --check
.venv/bin/python update_data.py
```

**Windows / PowerShell:**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
.\.venv\Scripts\python.exe update_data.py --check
.\.venv\Scripts\python.exe update_data.py
```

Add `--zip 79756 --zip 78681` to also refresh TXU offer snapshots in SQLite.
Managed TXU PDFs are downloaded and included in RAG only when you add `--include-txu-rag`; current
unreadable downloads can still fail RAG validation. Blocked TXU pricing is not
cleared by this script. `--check` makes no writes or provider calls; an actual
update can incur embedding/provider costs. Use `--force` to republish unchanged
data. See [combined update instructions](docs/update-data.md) for options,
configuration and partial-failure handling.

## Validate

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check frontend/app.js
node --test tests/zip-ui.test.cjs
```

Node is only needed for JavaScript syntax checks and UI tests; there is no frontend
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

The calculator includes PDF imports from the SQLite catalog alongside TXU plans.
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

For explicit PDF custom or demo comparisons, select **Explore alternatives** to explore contracts, usage, renewal assumptions and hypothetical rates/credits. Successful scenarios update the same comparison results; invalid or failed requests retain the last result. See [comparison chat](docs/comparison-chat.md) for examples, supported actions, configuration and recovery behavior.

### TXU cached offers

Fetch TXU utilities and offers for selected ZIPs, then compare both PDF and TXU imports automatically
in Compare Plan Costs:

```sh
python -m backend.catalog.cli sync-txu --zip 79756 --zip 78681
```

Install `requirements-rag.txt` for PDF extraction; this command needs no API key.
Offer availability expires after 24 hours. TXU PDFs are optional; incomplete or unsupported API pricing
remains visible with exclusions. See [TXU integration](docs/txu-integration.md) for
configuration, API contracts, refresh behavior and current provider limitations.

### Independent PDF and provider-API imports

PDF plans and provider-API offers are separate source records, including TXU.
Import PDFs using their document evidence; import API offers using their own
API response. Do not merge prices, fill one source from the other, or require a
matching API offer to import a PDF. API availability/freshness rules apply to API
offers. PDF prices retain their document date and unverified live availability.

A PDF under `data/_txu/` remains a PDF source. The strict importer now parses
these files independently of API offers; normal evidence/pricing checks apply.
An explicitly reviewed published-example benchmark may be imported with clear
unresolved-source warnings, but cannot enter exact ranking. See the
[import instructions](docs/validated-import.md#keep-pdf-and-api-imports-separate).
Historical skipped files need individual retry; they were not all reimported.

### Shared catalog API flow

PDFs → extract/validate → SQLite → catalog API data → comparison.
TXU APIs → validate/store → the same catalog API data → comparison.
RAG uses PDF text for cited explanations; it does not determine comparison prices.

Browse `/api/catalog/records?source_type=pdf` or
`/api/catalog/records?source_type=txu&zip_code=78681`. These records expose all
extracted/source fields, charge components, eligibility reasons and provenance.
Comparison uses the same records. TXU no longer needs a PDF to qualify: complete
supported API rates are sufficient. Existing SQLite data works without migration;
restart the backend after updating. See [the data flow](docs/data-flow.md).

The comparison form automatically includes both PDF and TXU catalog imports;
there is no source dropdown. New UI requests use `data_source: "catalog"`.
A utility selector appears only when needed. Missing or stale TXU data does not
block eligible PDF imports for a known delivery area. Individual-source API modes
and existing saved comparisons remain compatible.

### Rough costs for plans with incomplete billing rules

Comparison now includes a separate **Rough cost estimates** section. Each plan
shows its method, limitations and editable assumptions. Change the assumptions
and click **Compare plans** to recalculate; saved links retain the values used.
Hidden offers remain hypothetical, and rough results never enter winner selection.
See the [63-plan review](docs/plan-rule-review.md) and
[calculation methods and controls](docs/rough-estimates.md).

### Clean import: accept only validated plans

```sh
python -m backend.catalog.cli import-validated
```

Processes PDFs one at a time, imports only passing plans and logs rejected/skipped
files before continuing. Results are under `.data/import-logs/<run-id>/`.
Use `--file "choosetexaspower/EFL-1.pdf"` to retry a single corrected source.
See [validated-only import](docs/validated-import.md) for logs, Windows commands,
optional delivery-rate lookups and the distinction from diagnostic bulk sync.

Flat-rate PDFs do not need tier data. Explicit block-tier PDFs are also supported
for reviewed layouts, including Reliant Get More, Save More 12 and 36. Each tier
charges only consumption within its stated range; missing or ambiguous tiers are
not inferred. See [validated import rules](docs/validated-import.md) for commands,
validation requirements and the separate reviewed-estimate option.

Reviewed overnight/free-time plans can be imported with explicit
`--allow-reviewed-estimates` when their source rates, free-period rules and
assumptions have been reviewed and all example checks pass. Reliant Free Overnight
12 is supported; see the [overnight import instructions](docs/validated-import.md#reviewed-overnight-and-other-free-time-plans).

Month-to-month variable plans can also be imported as explicitly reviewed
estimates. Reliant Clear Flex preserves its stated term and usage-fee threshold;
months 2–12 use an editable price-change scenario. See [variable import rules](docs/validated-import.md#reviewed-month-to-month-variable-plans).

Comparison chat is not yet available for combined catalog or TXU comparisons; their existing comparison and rough-assumption controls remain available.
