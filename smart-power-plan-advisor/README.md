# Smart Power Plan Advisor

A thin local demo connecting a web form, FastAPI, a JSON plan source, deterministic
pricing, and SQLite. All plans and rates are synthetic; no API keys are needed.

## Run locally (PowerShell)

From this repository directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Choose a delivery area, enter 12 monthly usage values,
and compare plans. Expand each result for a monthly breakdown. The saved-result
link reloads the comparison from SQLite. API documentation is at `/docs`.

For runtime-only installation, use `requirements.txt` instead.

## Validate

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check frontend/app.js
```

Node is only needed for the optional JavaScript syntax check; there is no frontend
build or npm installation.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Check catalog and SQLite readiness |
| GET | `/api/plans` | List demo plans and delivery areas |
| POST | `/api/comparisons` | Calculate, rank and save a comparison |
| GET | `/api/comparisons/{id}` | Retrieve a saved comparison |

Example comparison request:

```json
{"tdu":"Oncor","monthly_kwh":[800,750,700,850,1100,1400,1600,1500,1200,950,750,850]}
```

Monetary values in comparison responses are decimal strings. The calculation
rounds monthly line items to cents and then sums monthly totals. SQLite lives at
`.data/advisor.sqlite3`; set `ADVISOR_DB_PATH` to choose another file.

## Scope and extension

This version supports fixed energy and delivery charges, base fees, and a single
inclusive monthly bill-credit threshold. It excludes taxes and switching fees.
All plans have a 12-month term. The selected area is not verified against an
address. This is a local, unauthenticated demo, not a live shopping service.

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
