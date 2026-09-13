import hashlib
import re
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse


def create_router(store, data_root):
    router = APIRouter(prefix='/api/catalog', tags=['Plan catalog'])

    def find(plan_id):
        if not re.fullmatch('[a-f0-9]{24}', plan_id):
            raise HTTPException(404, 'Plan not found')
        plan = next((p for p in store.all_plans() if p['id'] == plan_id), None)
        if plan is None:
            raise HTTPException(404, 'Plan not found')
        return plan

    @router.get('/status')
    def status():
        return {'data_mode': 'pdf', **store.status()}

    @router.get('/utilities')
    def utilities(zip_code: str = Query(..., pattern=r'^[0-9]{5}$')):
        from backend.catalog.utilities import resolve_utilities
        result = resolve_utilities(store, zip_code)
        if result['error']:
            raise HTTPException(503, result['error'])
        return result

    @router.get('/txu')
    def txu(zip_code: str = Query(..., pattern=r'^[0-9]{5}$', min_length=5, max_length=5)):
        from backend.catalog.txu import public_cache
        return public_cache(store, zip_code)

    @router.get('/records')
    def records(source_type: str | None = Query(None, pattern='^(pdf|txu)$'),
                zip_code: str | None = Query(None, pattern=r'^[0-9]{5}$'),
                utility_id: str | None = Query(None, max_length=36),
                calculable: bool | None = None,
                limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        from backend.catalog.records import records as read_records, CONTRACT_VERSION
        values = read_records(store, source_type, zip_code)
        if utility_id:
            from backend.catalog.utilities import cached_utilities, area_name
            discovery = cached_utilities(store, zip_code) if zip_code else None
            selected = next((u for u in discovery['utilities'] if u['id'] == utility_id), None) if discovery and not discovery['stale'] else None
            values = [p for p in values if p['utility_id'] == utility_id or (p['source_type'] == 'pdf' and selected and area_name(p['service_area'] or '') == area_name(selected['name']))]
        if calculable is not None:
            values = [p for p in values if p['calculation_eligible'] == calculable]
        return {'schema_version': CONTRACT_VERSION, 'total': len(values),
                'limit': limit, 'offset': offset, 'records': values[offset:offset + limit]}

    @router.get('/records/{record_id}')
    def record(record_id: str):
        from backend.catalog.records import records as read_records
        if re.fullmatch('[a-f0-9]{24}', record_id):
            result = next((p for p in read_records(store) if p['id'] == record_id), None)
            if result:
                return result
        raise HTTPException(404, 'Catalog record not found')

    @router.get('/plans')
    def plans(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
              provider: str | None = Query(None, max_length=200), service_area: str | None = Query(None, max_length=100),
              calculable: bool | None = None):
        values = store.all_plans()
        if provider:
            values = [p for p in values if provider.casefold() in (p['plan'].get('provider') or {}).get('value', '').casefold()]
        if service_area:
            values = [p for p in values if service_area.casefold() == (p['plan'].get('service_area') or {}).get('value', '').casefold()]
        if calculable is not None:
            values = [p for p in values if p['calculation_eligible'] == calculable]
        return {'data_mode': 'pdf', 'total': len(values), 'offset': offset, 'limit': limit, 'plans': values[offset:offset + limit]}

    @router.get('/plans/{plan_id}')
    def plan(plan_id: str):
        return find(plan_id)

    @router.get('/plans/{plan_id}/document')
    def document(plan_id: str):
        plan = find(plan_id)
        for source in plan['source_documents']:
            path = (data_root / source['filename']).resolve()
            if path.is_relative_to(data_root.resolve()) and path.is_file() and path.suffix.lower() == '.pdf':
                if hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']:
                    return FileResponse(path, media_type='application/pdf', filename=path.name, content_disposition_type='inline')
        raise HTTPException(404, 'Source PDF changed or is missing; run catalog sync.')

    return router
