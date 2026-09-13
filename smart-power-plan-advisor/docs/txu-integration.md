# TXU API ingestion

TXU offers feed the same SQLite-backed catalog API used by PDF imports.
Comparisons use structured API records; a TXU PDF is not required.

From the inner application directory:

```sh
python -m backend.catalog.cli sync-txu --zip 79756 --zip 78681
```

With an inactive virtual environment use `.venv/bin/python` on macOS or
`.\.venv\Scripts\python.exe` on Windows. No provider API key is needed. Existing
`--db`, `--data-dir`, `PLAN_CATALOG_DB_PATH` and `PLAN_DATA_DIR` settings apply.
Restart the backend after updating the code; retain the same catalog database.

Each sync looks up utilities for each ZIP, fetches plans for every returned utility
using that same ZIP, and stores the complete offers in an immutable SQLite
`txu_refreshes` snapshot. All utility requests must succeed before publishing the
ZIP. Different ZIPs can succeed independently. The summary reports `offers` saved,
`blocked` by pricing/availability checks, and `failed` listing refreshes. Only
listing failures produce a nonzero exit status.

## Pricing

The shared adapter supports fixed flat tariffs lasting at least twelve months.
It converts API USD/kWh to cents/kWh with Decimal arithmetic, retains monthly USD
fees, and requires explicit energy, base, delivery energy and delivery fixed
charges. The resulting bills must reconcile with the API's 500/1000/2000 kWh
examples within 0.15 cents/kWh. Average prices are checks, never billing formulas.

Missing or duplicate rates, unknown rate types/applicability fields, unmodeled fees,
credits, conditional/seasonal/free-time and solar pricing remain excluded. An empty
`billCredits` array is insufficient if the description advertises a credit.
Unsupported offers remain visible with specific `calculation_issues`; they are
still stored in SQLite. Hidden/inactive offers also cannot rank.

Availability expires after 24 hours. A subsequent listing failure immediately
invalidates the previous snapshot for comparison; an empty successful response
withdraws those offers. ZIP and utility matching remain mandatory. Existing raw
snapshots are projected through the new adapter without changing their timestamps
or requiring another EFL download. Distinct external offer IDs remain distinct
records, even if they have equal rates.

## API and UI

- `GET /api/catalog/records?source_type=txu&zip_code=78681` exposes the common
  pricing contract, complete original offer under `source_details`, checks,
  components and API provenance. Results are paginated (default 50, maximum 100).
- `GET /api/catalog/records/{id}` returns one current record. It may disappear
  after withdrawal; saved comparison results remain retrievable unchanged.
- `GET /api/catalog/txu?zip_code=78681` returns cached utilities, offer summaries,
  `record_url`, eligibility, issues and freshness. It does not expose raw offers.
- `POST /api/comparisons` uses the same catalog service as the records API.
  No self-HTTP call, provider request, PDF read or model request occurs.

```json
{
  "zip_code": "78681",
  "data_source": "txu",
  "utility_id": "ea0ad3a5-3fc6-4d9f-894a-e21a751c33fe",
  "monthly_kwh": [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000]
}
```

Utility selection is required only when multiple utilities serve the cached ZIP.
In **Compare Plan Costs**, enter a synced ZIP; both PDF and TXU imports are included automatically.
The result links to the exact current catalog record used for pricing. Saved
results retain the source revision, API URL, offer ID, ZIP, utility, fetch time
and raw-offer hash. API records have no invented PDF page or document issue date.

## Optional PDFs and RAG

```sh
python -m backend.catalog.cli sync-txu --zip 78681 --download-efls
```

This explicitly downloads EFLs into reserved `data/_txu/`. HTTPS hosts and redirect
destinations are checked; only bounded PDF responses are accepted. Extraction uses
reviewed deterministic parsers. Download/parser errors appear in `document_issues`
and do not invalidate complete API pricing. Normal local PDF sync skips managed
TXU files so they cannot leak into the local PDF source.

`python update_data.py --zip 78681 --include-txu-rag` requests optional downloads
and includes available managed PDFs in RAG. RAG retains its own strict document
validation, so unreadable documents can stop publication. TXU API pricing does not
require RAG. See [the shared data flow](data-flow.md) and [updater guide](update-data.md).

The comparison form automatically includes both PDF and TXU catalog imports;
there is no source dropdown. New UI requests use `data_source: "catalog"`.
A utility selector appears only when needed. Missing or stale TXU data does not
block eligible PDF imports for a known delivery area. Individual-source API modes
and existing saved comparisons remain compatible.


Normalization validates rate types independently. Duplicate energy entries remain
ambiguous and block exact pricing, but do not discard valid base/delivery charges
or published examples. Original entries remain under `source_details.rates`.
When recurring charges are incomplete, `price_checks` uses `status: "not_checked"`
and `passed: null`; it does not label present examples as missing. Existing caches
use this corrected projection after restarting the backend, without a re-sync.
