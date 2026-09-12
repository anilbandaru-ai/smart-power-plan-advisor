import fcntl
import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from backend.catalog.extract import VERSION, read_pages
from backend.catalog.pricing import validate
from backend.catalog.models import ExtractedPlan
from backend.catalog.tdu import Resolver, needs_tdu


def now():
    return datetime.now(timezone.utc).isoformat()


def sync(store, root, extractor, force=False, retry=False, refresh_tdu=False, resolver=None):
    resolver = resolver or Resolver()
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Data root must be an existing directory')
    # Complete discovery before touching source status; filesystem failures cannot remove records.
    paths = []
    def discovery_error(error):
        raise error
    for directory, _, filenames in os.walk(root, onerror=discovery_error, followlinks=False):
        paths.extend(root.__class__(directory) / name for name in filenames if name.lower().endswith('.pdf'))
    paths.sort()
    store.initialize()
    lock_path = store.path.with_suffix('.sync.lock')
    with lock_path.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another catalog sync is running') from None
        run_id, started = str(uuid4()), now()
        summary = {'files': len(paths), 'extracted': 0, 'reused': 0, 'failed': 0, 'removed': 0}
        with store.connection() as db:
            db.execute('INSERT INTO runs VALUES (?,?,NULL,NULL)', (run_id, started))
        batch_cache = {}
        for path in paths:
            relative = path.relative_to(root).as_posix()
            digest = None
            try:
                if not path.resolve().is_relative_to(root) or not path.is_file():
                    raise ValueError('Source path escapes root or is not a file')
                content = path.read_bytes()
                if len(content) > 20 * 1024 * 1024:
                    raise ValueError('PDF exceeds 20 MB limit')
                digest = sha256(content).hexdigest()
                previous = store.previous_source(relative)
                if previous and previous['status'] == 'failed' and previous['sha256'] == digest and not (retry or force):
                    store.source(relative, digest, None, 'failed', previous['error'], now())
                    summary['failed'] += 1
                    continue
                cached = batch_cache.get(digest)
                if cached is None and not force:
                    cached = store.cached(digest, VERSION, extractor.model)
                    if cached and refresh_tdu and cached['payload'] and needs_tdu(ExtractedPlan.model_validate_json(cached['payload'])):
                        cached = None
                    if cached and retry and (cached['status'] != 'ready' or json.loads(cached['issues'])):
                        cached = None
                if cached is None:
                    pages, warnings = read_pages(content)
                    plan = extractor.extract(pages)
                    plan = resolver.enrich(plan, pages)
                    issues, checks = validate(plan, pages)
                    cached = {'id': str(uuid4()), 'sha256': digest, 'version': VERSION, 'model': extractor.model,
                        'payload': plan.model_dump_json(), 'pages': json.dumps(pages), 'warnings': json.dumps(warnings),
                        'issues': json.dumps(issues), 'checks': json.dumps(checks), 'status': 'ready', 'extracted_at': now()}
                    store.revision(cached)
                    summary['extracted'] += 1
                else:
                    summary['reused'] += 1
                batch_cache[digest] = cached
                # Re-read before publication to avoid associating extracted terms with changed bytes.
                if sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('Source changed during extraction; rerun sync')
                store.source(relative, digest, cached['id'], cached['status'], None, now())
            except Exception as error:
                # Provider bodies may contain secrets; expose only a safe category, never str(error).
                reason = f'{type(error).__name__}: extraction/read failed; review source and rerun with --retry'
                store.source(relative, digest, None, 'failed', reason, now())
                summary['failed'] += 1
        summary['removed'] = store.deactivate_missing([p.relative_to(root).as_posix() for p in paths], now())
        with store.connection() as db:
            db.execute('UPDATE runs SET finished_at=?,summary=? WHERE id=?', (now(), json.dumps(summary), run_id))
        return summary
