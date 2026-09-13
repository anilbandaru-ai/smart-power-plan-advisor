"""Sequential, reviewed-parser-only import. Rejected data stays in logs, not SQLite."""
import json
import os
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from backend.catalog.extract import VERSION, read_pages
from backend.catalog.locking import catalog_lock
from backend.catalog.parser import parse_known
from backend.catalog.pricing import validate
from backend.catalog.sync import now
from backend.catalog.tdu import Resolver

MODEL = 'validated-reviewed-parser-v1'


class ReviewRequired(ValueError):
    pass


def reviewed_estimate(plan, digest, issues):
    """Only explicitly approved source snapshots can cross the estimate gate."""
    from backend.catalog.rough import registry, fingerprint, capability, estimate
    payload = json.loads(plan.model_dump_json())
    identity = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    entry = registry().get('pdf:' + identity, {})
    approval = entry.get('import_approval')
    if not approval or any(issue not in approval['allowed_issues'] for issue in issues):
        return None
    record = dict(id=identity, revision_id='pending', source_type='pdf', name=plan.name.value,
                  term_months=int(plan.contract_term.value) if plan.contract_term.value.isdigit() else None, source_details=payload,
                  source_documents=[{'sha256': digest}], calculation_eligible=False,
                  calculation_issues=issues, examples=payload['examples'],
                  record_url=f'/api/catalog/records/{identity}')
    if entry['fingerprint'] != fingerprint(record):
        return None
    cap = capability(record)
    if cap.get('review_status') != 'reviewed_snapshot':
        return None
    result = estimate(record, [e.kwh for e in plan.examples])
    checks = []
    for example, month in zip(plan.examples, result['monthly_costs']):
        actual = Decimal(month['total']) * 100 / example.kwh
        checks.append(dict(kwh=example.kwh, stated_cents_per_kwh=str(example.cents_per_kwh),
                           calculated_cents_per_kwh=str(actual),
                           passed=abs(actual-example.cents_per_kwh) <= Decimal('0.15'),
                           basis='published_benchmark' if cap['method'].endswith(':benchmark') else 'reviewed_estimate', assumptions=result['assumptions_used']))
    if {c['kwh'] for c in checks} != {500, 1000, 2000} or not all(c['passed'] for c in checks):
        return None
    return checks, result['assumptions_used']


def import_validated(store, root, *, files=None, log_dir=None, refresh_tdu=False, progress=None, allow_reviewed_estimates=False):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Data root must be a directory')
    if files:
        paths = sorted(set((Path(f) if Path(f).is_absolute() else root / f) for f in files))
        for p in paths:
            if not p.resolve().is_relative_to(root) or p.suffix.lower() != '.pdf' or not p.is_file():
                raise ValueError('Each --file must be an existing PDF inside the data root')
    else:
        paths = []
        def discovery_error(error):
            raise error
        for directory, _, names in os.walk(root, followlinks=False, onerror=discovery_error):
            paths.extend(Path(directory)/name for name in names if name.lower().endswith('.pdf'))
        paths.sort()
    store.initialize()
    run_id = now().replace(':','').replace('+','_') + '-' + uuid4().hex[:8]
    directory = (log_dir or store.path.parent/'import-logs')/run_id
    directory.mkdir(parents=True, exist_ok=False)
    summary = {'run_id':run_id, 'files':len(paths), 'imported':0, 'rejected':0, 'skipped':0,
               'reused':0, 'estimated':0, 'log_directory':str(directory.resolve()), 'started_at':now()}
    events = []
    resolver = Resolver() if refresh_tdu else None
    with catalog_lock(store.path.with_suffix('.sync.lock')), (directory/'events.jsonl').open('x') as log:
        for number, path in enumerate(paths,1):
            relative = path.relative_to(root).as_posix()
            event = {'sequence':number,'file':relative,'sha256':None,'name':None,'outcome':None,
                     'stage':'read_pdf','issues':[],'warnings':[],'price_checks':[],'revision_id':None}
            plan, pages = None, None
            try:
                if not path.resolve().is_relative_to(root) or not path.is_file():
                    raise ReviewRequired('Source escapes data root or is not a file')
                if path.stat().st_size > 20*1024*1024:
                    raise ReviewRequired('PDF exceeds 20 MB limit')
                content=path.read_bytes();event['sha256']=sha256(content).hexdigest()
                pages,event['warnings']=read_pages(content)
                event['stage']='parse'
                plan=parse_known(pages)
                if plan is None:
                    raise ReviewRequired('Unrecognized PDF layout: reviewed parser required; no model guesses imported')
                event['name']=plan.name.value if plan.name else None
                if resolver:
                    event['stage']='delivery_enrichment';plan=resolver.enrich(plan,pages)
                event['stage']='validate'
                event['issues'],event['price_checks']=validate(plan,pages)
                reviewed = reviewed_estimate(plan,event['sha256'],event['issues']) if allow_reviewed_estimates and event['issues'] else None
                if reviewed:
                    event['exact_price_checks'] = event['price_checks']
                    event['exact_validation_issues'] = event['issues']
                    event['issues'] = [i for i in event['issues'] if not i.startswith('Price example mismatch at ')]
                    event['price_checks'], event['assumptions'] = reviewed
                    event['calculation_mode'] = 'rough_estimate'
                if event['issues'] and not reviewed:
                    event['outcome']='rejected'
                else:
                    event['stage']='source_recheck'
                    if sha256(path.read_bytes()).hexdigest()!=event['sha256']:
                        raise ReviewRequired('Source changed during validation; rerun this file')
                    event['outcome']='ready_to_import'
            except Exception as error:
                # No provider response bodies or arbitrary exception messages enter logs.
                detail = str(error) if isinstance(error, ReviewRequired) else f'{type(error).__name__}: {event["stage"]} failed; review source file'
                event.update(outcome='rejected',issues=[detail])
            if event['outcome']=='ready_to_import':
                event['stage']='publish'
                existing=store.cached(event['sha256'],VERSION,MODEL)
                reusable=existing and existing['payload']==plan.model_dump_json() and json.loads(existing['issues']) == event['issues']
                revision=existing['id'] if reusable else str(uuid4())
                timestamp=now()
                # Do not catch database errors as source errors: failed publication
                # aborts rather than claiming a rejected or imported file.
                with store.connection() as db:
                    if not reusable:
                        db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            (revision,event['sha256'],VERSION,MODEL,plan.model_dump_json(),json.dumps(pages),
                             json.dumps(event['warnings']),json.dumps(event['issues']),json.dumps(event['price_checks']),'ready',timestamp))
                    db.execute('INSERT INTO sources VALUES (?,?,?,1,?,?,?) ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,revision_id=excluded.revision_id,active=1,status=excluded.status,error=NULL,synced_at=excluded.synced_at',
                               (relative,event['sha256'],revision,'ready',None,timestamp))
                event.update(outcome='imported',revision_id=revision,reused=bool(reusable))
                summary['reused']+=bool(reusable)
                summary['estimated']+=event.get('calculation_mode') == 'rough_estimate'
            elif event['outcome']=='rejected':
                # Remove only this association; retain historical valid revisions.
                with store.connection() as db:
                    db.execute('DELETE FROM sources WHERE path=?',(relative,))
            event['finished_at']=now();summary[event['outcome']]+=1
            log.write(json.dumps(event,ensure_ascii=False)+'\n');log.flush();os.fsync(log.fileno())
            events.append(event)
            if progress:progress(event)
    summary['finished_at']=now()
    (directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    lines=['# Validated-only import report','',f"Imported: {summary['imported']}; rejected: {summary['rejected']}; skipped: {summary['skipped']}.",'',
           f"Published records include {summary['estimated']} reviewed rough estimates, excluded from exact ranking. PDF imports are independent of provider API availability.",'']
    for event in events:
        lines.extend([f"## {event['sequence']}. {event['file']} — {event['outcome']}",'',f"Plan: {event['name'] or 'Not established'}",f"Stage: {event['stage']}",''])
        lines.extend('- '+issue for issue in event['issues'])
        lines.extend('- Warning: '+warning for warning in event['warnings'])
        if event['outcome']=='imported':
            label = 'Reviewed estimate checks passed; exact pricing remains unsupported. Assumptions: '+json.dumps(event['assumptions']) if event.get('calculation_mode') == 'rough_estimate' else 'All strict pricing/evidence checks passed.'
            lines.append(label+' Revision: '+event['revision_id'])
        lines.append('')
    (directory/'report.md').write_text('\n'.join(lines))
    return summary
