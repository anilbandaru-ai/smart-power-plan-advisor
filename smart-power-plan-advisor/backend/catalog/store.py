"""SQLite is the catalog source of truth; all writes are local sync operations."""
import json
import copy
from hashlib import sha256
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class CatalogStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS revisions (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, version TEXT NOT NULL, model TEXT NOT NULL, payload TEXT, pages TEXT, warnings TEXT NOT NULL, issues TEXT NOT NULL, checks TEXT NOT NULL, status TEXT NOT NULL, extracted_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS sources (path TEXT PRIMARY KEY, sha256 TEXT, revision_id TEXT, active INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, synced_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, summary TEXT)')

    def cached(self, digest, version, model):
        with self.connection() as db:
            row = db.execute('SELECT * FROM revisions WHERE sha256=? AND version=? AND model=? ORDER BY extracted_at DESC LIMIT 1', (digest, version, model)).fetchone()
            return dict(row) if row else None

    def revision(self, row):
        with self.connection() as db:
            db.execute('INSERT INTO revisions VALUES (:id,:sha256,:version,:model,:payload,:pages,:warnings,:issues,:checks,:status,:extracted_at)', row)

    def previous_source(self, path):
        with self.connection() as db:
            row = db.execute('SELECT * FROM sources WHERE path=?', (path,)).fetchone()
            return dict(row) if row else None

    def source(self, path, digest, revision, status, error, timestamp):
        with self.connection() as db:
            db.execute('INSERT INTO sources VALUES (?,?,?,1,?,?,?) ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256, revision_id=excluded.revision_id, active=1, status=excluded.status, error=excluded.error, synced_at=excluded.synced_at', (path, digest, revision, status, error, timestamp))

    def deactivate_missing(self, present, timestamp):
        with self.connection() as db:
            old = [r[0] for r in db.execute('SELECT path FROM sources WHERE active=1')]
            missing = set(old) - set(present)
            db.executemany('UPDATE sources SET active=0,status="missing",synced_at=? WHERE path=?', [(timestamp, path) for path in missing])
            return len(missing)

    def all_plans(self):
        with self.connection() as db:
            rows = db.execute('SELECT DISTINCT r.* FROM revisions r JOIN sources s ON s.revision_id=r.id WHERE s.active=1 AND s.status="ready" ORDER BY r.id').fetchall()
            result = []
            for row in rows:
                if not row['payload']:
                    continue
                sources = [r[0] for r in db.execute('SELECT path FROM sources WHERE revision_id=? AND active=1 AND status="ready" ORDER BY path', (row['id'],))]
                plan = json.loads(row['payload'])
                issues = json.loads(row['issues'])
                result.append({'id': row['sha256'][:24], 'revision_id': row['id'], 'document_sha256': row['sha256'],
                    'extraction_version': row['version'],
                    'extraction_method': 'deterministic' if 'Recognized deterministic EFL parser' in plan.get('extraction_notes', []) else 'model',
                    'extraction_model': None if 'Recognized deterministic EFL parser' in plan.get('extraction_notes', []) else row['model'], 'extracted_at': row['extracted_at'],
                    'calculation_eligible': not issues, 'calculation_issues': issues, 'warnings': json.loads(row['warnings']),
                    'price_checks': json.loads(row['checks']), 'sources': sources, 'plan': plan,
                    'source_documents': [{'filename': path, 'sha256': row['sha256']} for path in sources],
                    'document_url': f"/api/catalog/plans/{row['sha256'][:24]}/document"})
            # A force/retry run may leave duplicate-byte paths on older revisions; expose the latest only.
            unique = {}
            for item in sorted(result, key=lambda p: p['extracted_at']):
                old = unique.get(item['id'])
                if old:
                    item['sources'] = sorted(set(item['sources'] + old['sources']))
                    item['source_documents'].extend(old['source_documents'])
                unique[item['id']] = item
            grouped = {}
            for item in unique.values():
                identity_payload = copy.deepcopy(item['plan'])
                if identity_payload.get('tdu_lookup') and identity_payload['tdu_lookup'].get('source'):
                    identity_payload['tdu_lookup']['source'].pop('fetched_at', None)
                identity = sha256(json.dumps(identity_payload, sort_keys=True).encode()).hexdigest()[:24]
                if identity in grouped:
                    current = grouped[identity]
                    current['sources'] = sorted(set(current['sources'] + item['sources']))
                    current['source_documents'].extend(item['source_documents'])
                else:
                    item['id'] = identity
                    item['document_url'] = f'/api/catalog/plans/{identity}/document'
                    grouped[identity] = item
            return sorted(grouped.values(), key=lambda p: ((p['plan'].get('name') or {}).get('value', ''), p['id']))

    def status(self):
        with self.connection() as db:
            sources = [dict(row) for row in db.execute('SELECT path,status,error,active,synced_at FROM sources ORDER BY path')]
            run = db.execute('SELECT * FROM runs ORDER BY started_at DESC LIMIT 1').fetchone()
        plans = self.all_plans()
        return {'plans': len(plans), 'calculable_plans': sum(p['calculation_eligible'] for p in plans),
                'sources': sources, 'last_run': dict(run) if run else None}
