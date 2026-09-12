import hashlib
import re
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse


def create_router(store, data_root):
    router = APIRouter(prefix='/api/catalog', tags=['PDF plan catalog'])

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
