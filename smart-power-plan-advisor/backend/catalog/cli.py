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
    parser.add_argument('command', choices=['sync', 'status'])
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--retry', action='store_true')
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
        from backend.catalog.extract import Extractor
        from backend.catalog.sync import sync
        extractor = Extractor(Settings.from_env())
        result = sync(store, args.data_dir or Path(os.getenv("PLAN_DATA_DIR", str(ROOT / "data"))), extractor, force=args.force, retry=args.retry, refresh_tdu=args.refresh_tdu)
        print(json.dumps(result, indent=2))
        if result['failed']:
            raise SystemExit(1)
    except Exception as error:
        print(f'Catalog operation failed ({type(error).__name__}). Check paths, optional RAG dependencies and OpenAI configuration.')
        raise SystemExit(1) from None
    finally:
        if extractor:
            extractor.close()


if __name__ == '__main__':
    main()
