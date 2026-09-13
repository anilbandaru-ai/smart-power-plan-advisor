"""Cached TXU API pricing and optional EFL document evidence."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4
import httpx

from backend.catalog.extract import VERSION, read_pages
from backend.catalog.locking import catalog_lock
from backend.catalog.models import ExtractedPlan
from backend.catalog.parser import parse_known
from backend.catalog.pricing import validate
from backend.catalog.sync import now
from backend.providers.txu import TxuClient, TxuError, document_url, zip_code

MODEL = 'txu-reviewed-parser-v1'
PREFIX = '_txu/'
MAX_AGE = timedelta(hours=24)


def error_detail(error, operation):
    if isinstance(error, TxuError):
        detail = str(error)
    elif isinstance(error, httpx.HTTPStatusError):
        detail = f'TXU returned HTTP {error.response.status_code}'
    else:
        detail = type(error).__name__
    return f'{operation}: {detail}; review source and rerun sync-txu.'


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS txu_refreshes (id INTEGER PRIMARY KEY, zip_code TEXT NOT NULL, fetched_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT, error TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS txu_refresh_zip ON txu_refreshes(zip_code,id)')


def save_refresh(store, zip_value, payload, error=None):
    with store.connection() as db:
        db.execute('INSERT INTO txu_refreshes(zip_code,fetched_at,status,payload,error) VALUES (?,?,?,?,?)',
                   (zip_value, now(), 'failed' if error else 'ready',
                    json.dumps(payload, default=str) if payload is not None else None, error))


def cached(store, zip_value):
    zip_code(zip_value)
    with store.connection() as db:
        latest = db.execute('SELECT * FROM txu_refreshes WHERE zip_code=? ORDER BY id DESC LIMIT 1', (zip_value,)).fetchone()
        success = db.execute('SELECT * FROM txu_refreshes WHERE zip_code=? AND status="ready" ORDER BY id DESC LIMIT 1', (zip_value,)).fetchone()
    data = json.loads(success['payload']) if success else {'utilities': [], 'offers': []}
    timestamp = success['fetched_at'] if success else None
    stale = (not success or latest['status'] != 'ready'
             or datetime.now(timezone.utc) - datetime.fromisoformat(timestamp) >= MAX_AGE)
    return {'zip_code': zip_value, 'status': 'missing' if not latest else 'stale' if stale else 'ready',
            'stale': stale, 'fetched_at': timestamp,
            'last_attempt_at': latest['fetched_at'] if latest else None,
            'last_error': latest['error'] if latest else None, **data}


def ingest_efl(store, root, content):
    digest = sha256(content).hexdigest()
    relative = f'{PREFIX}{digest}.pdf'
    directory = root / '_txu'
    if directory.is_symlink():
        raise ValueError('Managed TXU directory must not be a symlink')
    directory.mkdir(exist_ok=True)
    if not directory.resolve().is_relative_to(root):
        raise ValueError('Managed TXU directory escapes data root')
    path = root / relative
    if path.is_symlink():
        raise ValueError('Managed TXU file must not be a symlink')
    if not path.exists() or sha256(path.read_bytes()).hexdigest() != digest:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temp:
            temporary = temp.name
            temp.write(content)
        try:
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    revision = store.cached(digest, VERSION, MODEL)
    if revision is None:
        pages, warnings = read_pages(content)
        plan = parse_known(pages)
        if plan is None:
            plan = ExtractedPlan(name=None, provider=None, service_area=None, issue_date=None,
                product_type=None, contract_term=None, termination_terms=None, components=[], examples=[],
                unsupported_rules=['Unrecognized TXU EFL layout: parser review required'], extraction_notes=[])
        issues, checks = validate(plan, pages)
        revision = {'id': str(uuid4()), 'sha256': digest, 'version': VERSION, 'model': MODEL,
            'payload': plan.model_dump_json(), 'pages': json.dumps(pages), 'warnings': json.dumps(warnings),
            'issues': json.dumps(issues), 'checks': json.dumps(checks), 'status': 'ready', 'extracted_at': now()}
        store.revision(revision)
    store.source(relative, digest, revision['id'], 'ready', None, now())
    return relative, revision


def sync_txu(store, root, zip_values, client=None, *, download_efls=False):
    zip_values = list(dict.fromkeys(zip_code(z) for z in zip_values))
    if not zip_values or len(zip_values) > 50:
        raise ValueError('Provide between 1 and 50 ZIP codes')
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Data root must be a directory')
    store.initialize()
    owned = client is None
    client = client or TxuClient()
    summary = {'zips': len(zip_values), 'failed': 0, 'offers': 0, 'blocked': 0}
    downloads = {}
    try:
        with catalog_lock(store.path.with_suffix('.sync.lock')):
            for zip_value in zip_values:
                try:
                    utilities = client.get_utilities(zip_value)
                    # Complete all listings before publication. Never infer removal
                    # from a failed utility call or silently publish a partial ZIP.
                    listings = [(utility, client.get_plans(zip_value, utility['id'])) for utility in utilities]
                except Exception as error:
                    save_refresh(store, zip_value, None, error_detail(error, 'TXU listing refresh failed'))
                    summary['failed'] += 1
                    continue
                offers = []
                for utility, listing in listings:
                    for raw in listing:
                        offer = {'external_id': raw['id'], 'name': raw['name'], 'utility_id': utility['id'],
                            'active': raw['active'], 'visible': not raw['hideOnGrid'], 'raw': raw,
                            'efl_url': None, 'source_path': None, 'revision_id': None,
                            'document_sha256': None, 'issues': [], 'document_issues': []}
                        try:
                            links = {d['url'] for d in raw.get('documents', []) if d.get('type') == 'Efl'}
                            if len(links) == 1:
                                offer['efl_url'] = document_url(links.pop())
                            elif download_efls:
                                raise TxuError('Missing or ambiguous EFL document link')
                            url = offer['efl_url']
                            if download_efls and url:
                                if url not in downloads:
                                    try:
                                        downloads[url] = ingest_efl(store, root, client.get_efl(url))
                                    except Exception as error:
                                        downloads[url] = error_detail(error, 'EFL download/extraction failed')
                                if isinstance(downloads[url], str):
                                    offer['document_issues'].append(downloads[url])
                                else:
                                    path, revision = downloads[url]
                                    offer.update(source_path=path, revision_id=revision['id'], document_sha256=revision['sha256'])
                                    offer['document_issues'].extend(json.loads(revision['issues']))
                        except Exception as error:
                            offer['document_issues'].append(error_detail(error, 'Optional EFL ingestion failed'))
                        from backend.catalog.records import txu_record
                        record = txu_record(offer, utility, zip_value, None)
                        offer['issues'] = record['calculation_issues']
                        offers.append(offer)
                save_refresh(store, zip_value, {'utilities': utilities, 'offers': offers})
                summary['offers'] += len(offers)
                summary['blocked'] += sum(bool(o['issues']) for o in offers)
    finally:
        if owned:
            client.close()
    return summary


def public_cache(store, zip_value):
    from backend.catalog.records import txu_record, finish
    data = cached(store, zip_value)
    documents = {(source['filename'], source['sha256']): plan['document_url']
                 for plan in store.all_plans() for source in plan['source_documents']}
    utilities = {u['id']: u for u in data['utilities']}
    for offer in data['offers']:
        record = txu_record(offer, utilities[offer['utility_id']], zip_value, data['fetched_at'])
        if data['stale']:
            record['calculation_issues'].append('TXU availability is stale; run sync-txu for this ZIP')
            finish(record)
        offer.pop('raw', None)
        offer['document_url'] = documents.get((offer.get('source_path'), offer.get('document_sha256')))
        offer['record_url'] = record['record_url']
        offer['issues'] = record['calculation_issues']
        offer['calculation_eligible'] = record['calculation_eligible']
    return data


def comparison_records(request, store):
    # Compatibility import for existing callers; all pricing uses the API contract.
    from backend.catalog.records import comparison_records as select
    return select(request, store)
