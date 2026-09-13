"""Run python -m backend.knowledge.cli --help from the application directory."""

import argparse
import json
import os
from pathlib import Path

from backend.knowledge.config import Settings
from backend.knowledge.models import DocumentReviewRequired, KnowledgeUnavailable


def source_files(settings, include_txu=False):
    root = settings.data_dir.resolve()
    files = []
    def discovery_error(error):
        raise error
    for directory, directories, filenames in os.walk(root, followlinks=False, onerror=discovery_error):
        if Path(directory) == root and not include_txu:
            directories[:] = [name for name in directories if name != "_txu"]
        files.extend(Path(directory) / name for name in filenames
                     if Path(name).suffix.lower() == ".pdf")
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="Preview or index local plan PDFs for cited Q&A.")
    parser.add_argument("--env-file", help="Optional ignored local env file; existing environment takes precedence")
    parser.add_argument("command", choices=["preview", "create-index", "ingest"])
    parser.add_argument("--include-txu-rag", action="store_true", help="Include downloaded _txu PDFs; strict page validation still applies")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    settings = Settings.from_env()
    providers = None
    try:
        if args.command == "create-index":
            from backend.knowledge.providers import create_index
            print(create_index(settings))
            return
        from backend.knowledge.documents import build_corpus
        manifest, records = build_corpus(settings, paths=source_files(settings, args.include_txu_rag))
        if args.command == "preview":
            print(json.dumps(manifest, indent=2))
            return
        from backend.knowledge.providers import Providers
        from backend.knowledge.ingest import publish
        providers = Providers(settings)
        providers.connect()
        publish(settings, manifest, records, providers)
        print(f"Upserted {len(records)} chunks from {len(manifest['documents'])} documents. Active manifest published; Pinecone search visibility may take a short time.")
    except Exception as error:
        # Third-party exceptions can include request details. Do not print their bodies.
        if isinstance(error, (KnowledgeUnavailable, DocumentReviewRequired)):
            print(str(error))
        elif isinstance(error, (ValueError, FileNotFoundError)):
            print(f"Document preparation failed: {type(error).__name__}. Run preview and review PDF text/page size and file configuration.")
        else:
            print(f"Operation failed ({type(error).__name__}). Check dependencies, credentials, index configuration and connectivity.")
        raise SystemExit(1) from None
    finally:
        if providers:
            providers.close()


if __name__ == "__main__":
    main()
