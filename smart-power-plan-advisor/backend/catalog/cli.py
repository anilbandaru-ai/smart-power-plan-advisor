"""Incremental ingestion: python -m backend.catalog.cli --env-file .env sync."""
import argparse
import json
import os
from pathlib import Path

from backend.knowledge.config import ROOT, Settings
from backend.catalog.store import CatalogStore


def main():
    parser = argparse.ArgumentParser(description='Sync local PDF plan terms into SQLite; does not publish Pinecone data.')
    parser.add_argument('--env-file')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--db', type=Path)
    parser.add_argument('command', choices=['sync', 'sync-txu', 'import-validated', 'status'])
    parser.add_argument('--zip', action='append', dest='zips', help='ZIP to fetch from TXU; repeat for multiple ZIPs')
    parser.add_argument('--download-efls', action='store_true', help='Also download TXU PDFs as optional document evidence')
    parser.add_argument('--file', action='append', help='For import-validated: PDF path relative to data root; repeat for selected files')
    parser.add_argument('--log-dir', type=Path, help='For import-validated: directory for per-run logs')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--retry', action='store_true')
    parser.add_argument('--allow-reviewed-estimates', action='store_true', help='Allow explicitly approved, fingerprint-matched rough estimates in import-validated')
    parser.add_argument('--refresh-tdu', action='store_true', help='Refresh provider rates for TDU-dependent or missing-rate plans')
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    store = CatalogStore(args.db or Path(os.getenv('PLAN_CATALOG_DB_PATH', str(ROOT / '.data' / 'plans.sqlite3'))))
    extractor = None
    try:
        if args.command == 'status':
            store.initialize()
            print(json.dumps(store.status(), indent=2))
            return
        if args.command == 'import-validated':
            from backend.catalog.validated import import_validated
            def progress(event):
                print(f"[{event['sequence']}] {event['outcome']}: {event['file']}", flush=True)
            result = import_validated(store, args.data_dir or Path(os.getenv('PLAN_DATA_DIR', str(ROOT / 'data'))),
                files=args.file, log_dir=args.log_dir, refresh_tdu=args.refresh_tdu, progress=progress, allow_reviewed_estimates=args.allow_reviewed_estimates)
            print(json.dumps(result, indent=2))
            if result['rejected']:
                raise SystemExit(1)
            return
        if args.command == 'sync-txu':
            from backend.catalog.txu import sync_txu
            result = sync_txu(store, args.data_dir or Path(os.getenv('PLAN_DATA_DIR', str(ROOT / 'data'))), args.zips or [], download_efls=args.download_efls)
            print(json.dumps(result, indent=2))
            if result['failed']:
                raise SystemExit(1)
            return
        from backend.catalog.extract import Extractor
        from backend.catalog.sync import sync
        extractor = Extractor(Settings.from_env())
        result = sync(store, args.data_dir or Path(os.getenv("PLAN_DATA_DIR", str(ROOT / "data"))), extractor, force=args.force, retry=args.retry, refresh_tdu=args.refresh_tdu)
        print(json.dumps(result, indent=2))
        if result['failed']:
            raise SystemExit(1)
    except Exception as error:
        guidance = ('Check paths, SQLite, PDF dependencies and import logs; no OpenAI key is required.' if args.command == 'import-validated'
                    else 'Check ZIPs, paths, PDF dependencies and TXU reachability.' if args.command == 'sync-txu'
                    else 'Check paths, optional RAG dependencies and OpenAI configuration.')
        print(f'Catalog operation failed ({type(error).__name__}). {guidance}')
        raise SystemExit(1) from None
    finally:
        if extractor:
            extractor.close()


if __name__ == '__main__':
    main()
