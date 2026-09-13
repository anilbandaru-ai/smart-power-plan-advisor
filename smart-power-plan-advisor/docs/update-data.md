# Update SQLite and RAG together

`update_data.py` is a cross-platform Python command for the existing plan catalog
and document RAG index. It uses the same interpreter for the entire operation,
so there is no shell activation or Bash/PowerShell script dependency.

Run the commands below from the **inner application folder** containing
`update_data.py`, `backend/`, `.env` and `requirements-rag.txt`. From the cloned
repository root, first run `cd smart-power-plan-advisor`.

## macOS / Linux

```sh
# One-time dependency setup in the same environment used to run the script:
.venv/bin/python -m pip install -r requirements-rag.txt

# Read-only dependency/configuration check:
.venv/bin/python update_data.py --check

# Update the local PDF catalog and RAG:
.venv/bin/python update_data.py
```

## Windows / PowerShell

```powershell
# One-time dependency setup; no environment activation required:
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt

# Read-only dependency/configuration check:
.\.venv\Scripts\python.exe update_data.py --check

# Update the local PDF catalog and RAG:
.\.venv\Scripts\python.exe update_data.py
```

If the environment does not yet exist, create it with `python3 -m venv .venv` on
macOS/Linux or `python -m venv .venv` on Windows. Installing packages into a `.venv`
in the repository root does not install them into the inner application's `.venv`.
You may also use `python update_data.py` if the correct environment is activated.

## Existing configuration

The command loads the application's `.env` automatically. Existing environment
variables take precedence. It reuses `OPENAI_API_KEY`, `PINECONE_API_KEY`,
`PINECONE_INDEX` and `PINECONE_NAMESPACE`, plus the existing model configuration.
Keys are never printed or changed. The configured Pinecone index must already
exist, be ready, and match the existing 3,072-dimension cosine configuration.
Follow the [RAG setup guide](rag.md) for first-time index configuration.

A real update sends document text for OpenAI embeddings and stores vectors/text
in Pinecone; normal provider usage costs apply. Unknown local PDF layouts can
also use the existing catalog's model extraction. This command does not create
or delete indexes, erase old namespaces, or change tariff approval rules.

`--check` verifies local packages, credential presence, paths and PDF counts. It
does **not** extract PDFs, create files, contact providers, verify credential
validity, or test whether the remote index is ready. `check_passed` is a local
configuration result, not a completed data update.

## Optional TXU refresh

To also fetch current TXU utilities/offers into SQLite:

```sh
python update_data.py --zip 79756 --zip 78681
```

Use your platform's explicit `.venv` Python path above when the environment is not
activated. Repeat `--zip` for additional ZIPs (maximum 50).

By default, RAG uses the ordinary PDFs in `data/` and excludes managed downloads
under `data/_txu/`. This keeps unreviewed TXU downloads from unexpectedly replacing
the assistant corpus. TXU discovery still saves offers even when they are blocked
from cost comparisons. A `blocked` count is not a storage failure.

To explicitly include TXU PDFs in the RAG document corpus:

```sh
python update_data.py --zip 79756 --zip 78681 --include-txu-rag
```

This includes the managed directory's PDFs, including historical or hidden offers;
document evidence does not establish current availability. Strict page/text checks
still apply. A malformed, too-short or oversized page stops RAG preparation with
its source filename/page, and the previous active manifest stays intact. These
failures are **not silently skipped**. The current downloaded TXU collection has
known document-validation failures, so the default excludes it. Adding it to RAG
does not make any offer calculation-eligible.

## Refresh and path options

| Option | Effect |
| --- | --- |
| `--force` | Reextract local catalog files and republish RAG even if its local manifest is unchanged. |
| `--refresh-tdu` | Refresh delivery-rate lookups using the existing catalog policy. |
| `--env-file PATH` | Load another existing env file. |
| `--data-dir PATH` | Override the PDF root for both preparation and SQLite sync. |
| `--db PATH` | Override the SQLite catalog path. |
| `--manifest PATH` | Override the active RAG manifest file. |
| `--help` | Show all options without requiring ingestion packages or keys. |

Relative paths resolve from the application directory, regardless of the terminal's
current directory. Environment overrides `PLAN_DATA_DIR`, `PLAN_CATALOG_DB_PATH`
and `RAG_MANIFEST_PATH` are also supported. Configure the server with matching
paths if you override them; use absolute environment paths for consistent runtime
behavior. Restart the server after changing environment configuration.

## What happens and how failures are reported

1. Validate local dependencies, configuration and paths before writes or calls.
2. If ZIPs were supplied, refresh their TXU snapshots in SQLite.
3. Prepare the selected RAG PDFs using existing chunking and citation rules.
4. Incrementally update the local PDF catalog, retrying prior failed sources.
5. If the prepared manifest is unchanged, report RAG `unchanged` and skip model
   embeddings/upserts. Remote contents are not rechecked in this case; use
   `--force` to rebuild a missing or externally altered index namespace.
6. Otherwise, verify index compatibility, upsert embeddings, recheck source hashes,
   and atomically activate the new local RAG manifest.

Progress is written to stderr. The final JSON on stdout reports overall `status`,
the last `stage`, paths, and separate `sqlite`, `txu` and `rag` results. The command
returns exit code 0 for a completed update/check and 1 for a failed update/check;
invalid command syntax uses argparse's exit code 2. TXU `blocked` counts remain
separate from listing `failed` counts. Successful SQLite sync can still contain
non-calculable plans, consistent with the existing catalog rules.

SQLite and Pinecone are **not one atomic transaction**. For example, if an upsert
fails after SQLite finishes, the JSON shows SQLite `updated` and RAG `failed`.
Completed SQLite work stays saved; the old active RAG manifest remains in use.
Failed upserts may leave partial records in a new inactive namespace. Rerunning
retries the work without removing historical data. A document preparation failure
stops the local catalog/RAG stages, although an earlier requested TXU refresh may
already have completed.

A shared manifest lock prevents simultaneous runs of this combined command on
macOS and Windows. Avoid separately running the standalone RAG CLI at the same
time; it does not acquire this combined-command lock.

## Verification

Tests use temporary SQLite/manifest files and mocked provider operations, including
real atomic-manifest publication, source changes, empty/failed stages, unchanged
and forced updates, TXU selection, uppercase PDF source names, path containment,
credential redaction and no-write preflight. Native verification is on macOS;
Windows commands use the same Python code and the existing Windows lock helper,
but have not been executed on a Windows host during this change. No live RAG
publication is performed as part of these tests.

TXU sync now prices from API terms directly, without requiring PDFs. Combining
`--zip` with `--include-txu-rag` also requests optional EFL downloads before RAG
preparation. Document failures do not block API pricing; RAG validation remains
independent. Both PDF and TXU comparisons use the [shared API records](data-flow.md).
