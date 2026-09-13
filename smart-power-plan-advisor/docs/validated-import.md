# Import validated plans one file at a time

Use this command from the inner application directory for a clean catalog:

```sh
python -m backend.catalog.cli import-validated
```

It processes preserved PDF files sequentially in sorted path order. Each ordinary
PDF is read, parsed by a reviewed parser, checked for source evidence, required
fields, supported billing rules, a twelve-month term and all three price examples,
and checked again for changed bytes. Only a passing plan is committed to SQLite.
The revision and source association are written in one transaction.

Rejected plans are recorded in logs, not imported. The next file is still
processed. PDF plans and provider-API offers are independent sources; PDF import
does not require a matching API offer. This command does not fetch TXU offers
or restore their old snapshots. Unknown layouts receive no model-based
fallback. Existing source files and reset backups remain unchanged.

To retry just one file after correcting its parser or data:

```sh
python -m backend.catalog.cli import-validated --file "choosetexaspower/EFL-1.pdf"
```

Repeat `--file` to select several files. Paths are relative to `--data-dir` (default
`data/`) and must stay within that root. Unselected records are unchanged. If a
selected source previously passed but now fails, its old active association is
withdrawn so stale terms cannot continue appearing in the API. Historical valid
revisions remain available in SQLite.

Use `.venv/bin/python` on macOS or `.\.venv\Scripts\python.exe` on Windows if your
environment is not activated. The command uses portable Python and the existing
cross-platform catalog lock. PDF dependencies are in `requirements-rag.txt`, but
this command does not need API credentials.

Default validation is offline. `--refresh-tdu` explicitly enables the existing
approved delivery-rate lookup, retaining its provider, date and evidence checks.
Missing or unsupported delivery rates otherwise remain rejected; no delivery
rate is inferred from an advertised average.

Logs are created under `.data/import-logs/<run-id>/` (or `--log-dir`):

- `events.jsonl`: one flushed event per file, including sequence, path, hash,
  stage, name, outcome, issues, warnings, price checks and imported revision ID.
- `summary.json`: counts, start/end timestamps and log location.
- `report.md`: readable per-file results and issues.

Exit status 1 means at least one file was rejected; passing imports remain saved.
Infrastructure failures stop the run; previously committed files remain and the
JSONL journal records completed outcomes. Rerunning revalidates files and reuses
identical validated revisions.

The older `sync`, `sync-txu` and combined RAG updater retain their diagnostic
behavior, including storing review-required records. Use `import-validated` for
this validated-only workflow rather than those bulk diagnostic sync commands.

After importing, `/api/catalog/records` and `/api/catalog/plans` show the accepted
plans. `calculation_eligible` means the implemented validation passed, not a
provider guarantee of current price or address eligibility.

Explicitly approved rough estimates can be imported with
`python -m backend.catalog.cli import-validated --file "Reliant/EFL - Reliant Energy Retail Services-10.pdf" --allow-reviewed-estimates`.
The default remains strict. The reviewed Flextra snapshot must retain its exact
source fingerprint and pass all three example checks using the displayed 32%
free-usage assumption. It remains excluded from exact ranking, with editable
assumptions and estimate notes in comparison. Missing evidence and unreviewed
sources cannot use this option to bypass validation. Logs preserve the original
exact checks separately from assumption-based checks and count estimated imports.

The reviewed **Reliant Power Savings 9** PDF is also approved with
`--allow-reviewed-estimates`. Its nine-month contract and stated tariff are
preserved. The 12-month comparison uses an editable post-contract bill adjustment
only for months 10–12 (default 0%); renewal pricing is unknown. Select it with
`--file "Reliant/EFL - Reliant Energy Retail Services-3.pdf"`.

## Keep PDF and API imports separate

- A PDF is validated from its document evidence, even if its provider is TXU or
  its filename is under `_txu/`. Do not require an API match or copy API prices
  into the PDF record.
- API offers are validated independently using their own rates, utility/ZIP
  availability and freshness. Do not use a PDF to repair an API offer's data.
- Preserve distinct source records and provenance. The same plan name does not
  establish that a PDF and API offer are identical. A shared comparison view does
  not authorize merging their fields.
- PDF prices are document-date calculations/estimates; live availability remains
  unverified. This is a disclosure, not a reason to require API linkage.
- Retain the existing evidence, missing-charge, supported-rule and reviewed
  assumption checks. Source separation does not mean every PDF automatically passes.

`import-validated` now parses `_txu/` PDFs like other PDF sources. Unknown
layouts or invalid document data reject normally; no API listing is required.
Historical skip entries remain historical until those files are retried.

## Flat and tiered energy rates

A provider does not need to supply tiers: one stated flat energy rate is valid.
When the source explicitly supplies marginal/block tiers, import each rate with
its stated lower/upper usage boundary. The API represents these as `energy_tier`
components; only consumption within that block is charged at its rate. Delivery
charges and base fees are applied separately. Do not invent missing rates or tiers,
or treat a whole-usage conditional rate as a marginal tier.

The reviewed Reliant Get More, Save More 12 and 36 PDFs are supported by the strict
importer without `--allow-reviewed-estimates`. Tiers must cover zero through
unlimited usage without gaps, overlaps or mixing flat and tier energy charges.
Source evidence, required delivery charges and all three price examples must pass.
Other layouts require parser review before import; failures remain in the logs.

```sh
python -m backend.catalog.cli import-validated --file "Reliant/EFL - Reliant Energy Retail Services-4.pdf" --file "Reliant/EFL - Reliant Energy Retail Services-5.pdf"
```

## Reviewed overnight and other free-time plans

A free-time plan can be imported as a reviewed estimate when its source explicitly
states the free hours, paid rates, eligible waived charges and fixed fees, and a
reviewed usage assumption reproduces all three EFL examples. Missing rates or
unreviewed/changed snapshots remain rejected. A single monthly total cannot
establish actual usage during free hours; these plans stay outside exact ranking.

Reliant Free Overnight 12 is approved for the inspected source: 9 p.m.–6 a.m.
every day, 32% nighttime usage by default, 100% variable-delivery waiver, and
$4.06 fixed delivery retained. Assumptions and limitations appear in comparison
and can be edited. No external TDU lookup is needed for this PDF.

```sh
python -m backend.catalog.cli import-validated --file "Reliant/EFL - Reliant Energy Retail Services-9.pdf" --allow-reviewed-estimates
```

## Reviewed month-to-month variable plans

A stated month-to-month term is valid source data. Preserve `Month to Month` in
`contract_term`; `term_months` is null because there is no fixed-duration contract.
Such plans require `--allow-reviewed-estimates`, source-specific review, complete
rates/fee conditions and passing examples. They remain outside exact annual ranking.

Reliant Clear Flex is approved for the inspected PDF. Its $9.95 usage fee applies
below 800 kWh and becomes $0 at/above 800. First-cycle pricing is calculated from
the source; months 2–12 assume unchanged charges by default, with an editable
subsequent bill-change percentage. Future variable prices are unknown. The source
states no termination fee. Missing terms, rates, or changed/unreviewed source
snapshots cannot bypass the import gate.

```sh
python -m backend.catalog.cli import-validated --file "Reliant/EFL - Reliant Energy Retail Services-8.pdf" --allow-reviewed-estimates
```

## Explicitly reviewed published-example benchmarks

The inspected TXU Free Pass 24 PDF with hash prefix `0160b2be` is approved only
as a document benchmark estimate using its printed 500/1000/2000 kWh prices.
Delivery rates remain missing and its 0.000% free-usage disclosure is flagged as
inconsistent. No rates or free-usage share are inferred. This is a narrow reviewed
snapshot exception, not permission to import arbitrary incomplete pricing.
Checks labeled `published_benchmark` reproduce source examples; they do not
independently reconcile the tariff. Exact pricing remains ineligible.

```sh
python -m backend.catalog.cli import-validated --file "_txu/0160b2be9238adb9647f00d1028d84dc61a694b3c7a94328a5ca259b27e1ebb2.pdf" --allow-reviewed-estimates
```
