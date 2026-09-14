"""Portable orchestration of existing SQLite and RAG ingestion boundaries."""
import argparse
from dataclasses import dataclass, replace
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = ('fastapi', 'httpx', 'pdfplumber', 'tiktoken', 'dotenv', 'openai', 'pinecone')


class UpdateError(ValueError):
    """Controlled, safe error text for the command line."""


@dataclass
class Configuration:
    settings: object
    db: Path
    zips: list[str]
    include_txu_rag: bool = False
    force: bool = False
    refresh_tdu: bool = False


def resolve_path(value):
    path = Path(value).expanduser()
    return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def install_command():
    args = [sys.executable, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-rag.txt')]
    return subprocess.list2cmdline(args) if os.name == 'nt' else shlex.join(args)


def require_dependencies():
    missing = [name for name in DEPENDENCIES if importlib.util.find_spec(name) is None]
    if missing:
        raise UpdateError(f'Missing packages: {", ".join(missing)}. Install into this interpreter with: {install_command()}')


def configuration(args):
    require_dependencies()
    from dotenv import load_dotenv
    from backend.knowledge.config import Settings
    from backend.providers.txu import zip_code

    env_file = resolve_path(args.env_file or '.env')
    if args.env_file and not env_file.is_file():
        raise UpdateError('The requested env file does not exist.')
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    settings = Settings.from_env()
    missing = [name for name, value in (('OPENAI_API_KEY', settings.openai_key),
                                        ('PINECONE_API_KEY', settings.pinecone_key)) if not value]
    if missing:
        raise UpdateError(f'Missing configuration: {", ".join(missing)}. Set it in the application .env or environment; do not paste secrets into logs.')
    if not settings.index_name or not settings.namespace_prefix:
        raise UpdateError('PINECONE_INDEX and PINECONE_NAMESPACE must not be empty.')
    data_dir = resolve_path(args.data_dir or os.getenv('PLAN_DATA_DIR') or ROOT / 'data')
    db = resolve_path(args.db or os.getenv('PLAN_CATALOG_DB_PATH') or ROOT / '.data' / 'plans.sqlite3')
    manifest = resolve_path(args.manifest or os.getenv('RAG_MANIFEST_PATH') or ROOT / '.data' / 'knowledge.json')
    if not data_dir.is_dir():
        raise UpdateError('The PDF data directory must already exist.')
    if db == manifest or db == manifest.with_suffix('.update.lock'):
        raise UpdateError('SQLite, manifest and update lock paths must be distinct.')
    for output in (db, manifest):
        if output.exists() and not output.is_file():
            raise UpdateError('SQLite and manifest output paths must be files, not directories.')
    try:
        zips = list(dict.fromkeys(zip_code(value) for value in args.zips))
    except ValueError:
        raise UpdateError('Each --zip value must contain exactly five digits.') from None
    if len(zips) > 50:
        raise UpdateError('Provide at most 50 ZIP codes per update.')
    return Configuration(replace(settings, data_dir=data_dir, manifest_path=manifest), db, zips,
                         args.include_txu_rag, args.force, args.refresh_tdu)


def source_files(config):
    root = config.settings.data_dir.resolve()
    files = []
    def discovery_error(error):
        raise error
    for directory, directories, filenames in os.walk(root, followlinks=False, onerror=discovery_error):
        if Path(directory) == root and not config.include_txu_rag:
            directories[:] = [name for name in directories if name != '_txu']
        for name in filenames:
            path = Path(directory) / name
            if path.suffix.lower() == '.pdf':
                if not path.resolve().is_relative_to(root) or not path.is_file():
                    raise UpdateError('A PDF source is missing or escapes the data directory.')
                files.append(path)
    return sorted(files)


def assert_sources_unchanged(settings, manifest):
    root = settings.data_dir.resolve()
    for document in manifest['documents']:
        path = (root / document['filename']).resolve()
        if (not path.is_relative_to(root) or not path.is_file()
                or sha256(path.read_bytes()).hexdigest() != document['sha256']):
            raise UpdateError('A prepared PDF changed during the update. Rerun with stable source files.')


def manifest_unchanged(path, prepared):
    try:
        return json.loads(path.read_text()) == prepared
    except (OSError, ValueError):
        return False


def progress(message):
    print(message, file=sys.stderr, flush=True)


def update(config, report):
    # Imports are delayed until after preflight, so --help works in a fresh venv.
    from backend.catalog.extract import Extractor
    from backend.catalog.locking import catalog_lock
    from backend.catalog.store import CatalogStore
    from backend.catalog.sync import sync
    from backend.catalog.txu import sync_txu
    from backend.knowledge.documents import build_corpus
    from backend.knowledge.ingest import publish
    from backend.knowledge.providers import Providers

    settings = config.settings
    settings.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with catalog_lock(settings.manifest_path.with_suffix('.update.lock')):
        store = CatalogStore(config.db)
        if config.zips:
            report['stage'] = 'txu'
            report['txu'] = {'status': 'running'}
            progress('Refreshing TXU offers in SQLite...')
            summary = sync_txu(store, settings.data_dir, config.zips, **({"download_efls": True} if config.include_txu_rag else {}))
            report['txu'] = {'status': 'partial' if summary['failed'] else 'updated', **summary}
            if summary['failed']:
                raise UpdateError('Some TXU listing refreshes failed. Successful SQLite snapshots are retained; rerun to retry.')

        report['stage'] = 'prepare_rag'
        report['rag'] = {'status': 'preparing'}
        progress('Preparing PDF text and citations for RAG...')
        from backend.knowledge.audit import audit_corpus, write_audit
        paths = source_files(config)
        audit = audit_corpus(settings, paths)
        audit_path = settings.manifest_path.parent / 'rag-audit.json'
        write_audit(audit, audit_path)
        if audit['failed']:
            raise UpdateError('RAG audit found unreadable pages; review rag-audit.json before retrying.')
        prepared, records = build_corpus(settings, paths=paths)
        report['rag'] = {'status': 'prepared', 'documents': len(prepared['documents']), 'chunks': len(records)}

        report['stage'] = 'sqlite'
        report['sqlite'] = {'status': 'running'}
        progress('Updating the SQLite PDF catalog...')
        extractor = Extractor(settings)
        try:
            summary = sync(store, settings.data_dir, extractor, retry=True,
                           force=config.force, refresh_tdu=config.refresh_tdu)
        finally:
            extractor.close()
        report['sqlite'] = {'status': 'partial' if summary['failed'] else 'updated', **summary}
        if summary['failed']:
            raise UpdateError('Some SQLite PDF sources failed. Successful changes are retained; RAG was not published. Review catalog status and retry.')

        report['stage'] = 'rag'
        assert_sources_unchanged(settings, prepared)
        if not config.force and manifest_unchanged(settings.manifest_path, prepared):
            report['rag'].update(status='unchanged', remote_state_checked=False)
            progress('RAG manifest is unchanged; skipping embeddings and upserts. Use --force to republish.')
        else:
            progress('Publishing embeddings to the configured RAG index...')
            providers = Providers(settings)
            try:
                providers.connect()
                assert_sources_unchanged(settings, prepared)
                publish(settings, prepared, records, providers,
                        before_activate=lambda: assert_sources_unchanged(settings, prepared))
            finally:
                providers.close()
            report['rag'].update(status='updated', namespace=prepared['namespace'])
        report['stage'] = 'complete'
        report['status'] = 'complete'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Update SQLite plan data and the existing RAG index on macOS or Windows.')
    parser.add_argument('--env-file', help='Default: application .env; existing environment takes precedence')
    parser.add_argument('--data-dir', help='PDF directory (relative paths resolve from the application directory)')
    parser.add_argument('--db', help='SQLite catalog path')
    parser.add_argument('--manifest', help='Active RAG manifest path')
    parser.add_argument('--zip', action='append', dest='zips', default=[], help='Also refresh TXU for this ZIP; repeat as needed')
    parser.add_argument('--include-txu-rag', action='store_true', help='Include managed TXU PDFs in RAG; strict document checks still apply')
    parser.add_argument('--force', action='store_true', help='Reextract SQLite sources and republish unchanged RAG data')
    parser.add_argument('--refresh-tdu', action='store_true', help='Refresh missing/dependent TDU delivery rates during SQLite sync')
    parser.add_argument('--check', action='store_true', help='Check local dependencies/configuration without writes or provider calls')
    args = parser.parse_args(argv)
    report = {'status': 'running', 'stage': 'preflight', 'sqlite': {'status': 'not_started'},
              'txu': {'status': 'not_requested' if not args.zips else 'not_started'}, 'rag': {'status': 'not_started'}}
    try:
        config = configuration(args)
        report.update(data_dir=str(config.settings.data_dir), sqlite_path=str(config.db),
                      manifest_path=str(config.settings.manifest_path), include_txu_rag=config.include_txu_rag)
        if args.check:
            report.update(status='check_passed', pdf_files=len(source_files(config)),
                          credentials_present=True, live_readiness_checked=False,
                          interpreter=sys.executable, txu_zips=config.zips)
        else:
            update(config, report)
    except Exception as error:
        public_errors = [UpdateError]
        try:
            from backend.knowledge.models import DocumentReviewRequired
            public_errors.append(DocumentReviewRequired)
        except ImportError:
            pass  # A fresh venv may not yet have even the base dependencies.
        report['status'] = 'failed'
        stage = report['stage']
        key = 'rag' if stage in ('prepare_rag', 'rag') else stage
        if key in ('sqlite', 'txu', 'rag') and report[key]['status'] != 'partial':
            report[key]['status'] = 'failed'
        if isinstance(error, tuple(public_errors)):
            report['error'] = str(error)
        elif isinstance(error, ModuleNotFoundError):
            report['error'] = f'Missing ingestion dependency. Install with: {install_command()}'
        else:
            report['error'] = f'{type(error).__name__}: update failed; check source files, existing index configuration and connectivity. Provider details are omitted.'
        report['note'] = 'Completed SQLite changes remain. A failed RAG upsert does not replace the previous active manifest.'
    print(json.dumps(report, indent=2))
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
