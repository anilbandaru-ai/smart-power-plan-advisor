"""Run python -m backend.knowledge.cli --help from the application directory."""

import argparse
import json

from backend.knowledge.config import Settings
from backend.knowledge.models import DocumentReviewRequired, KnowledgeUnavailable


def main():
    parser = argparse.ArgumentParser(description="Preview or index local plan PDFs for cited Q&A.")
    parser.add_argument("--env-file", help="Optional ignored local env file; existing environment takes precedence")
    parser.add_argument("command", choices=["preview", "create-index", "ingest"])
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
        manifest, records = build_corpus(settings)
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
