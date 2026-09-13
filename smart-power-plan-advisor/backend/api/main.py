import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.integrations import JsonPlanSource, PlanSource
from backend.models import ComparisonRequest, ComparisonResult
from backend.services import compare
from backend.storage import ComparisonStore
from backend.knowledge.api import create_router
from backend.agent.api import create_router as create_agent_router
from backend.catalog.api import create_router as create_catalog_router
from backend.catalog.store import CatalogStore

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("uvicorn.error")


def create_app(db_path: Path | None = None, plan_source: PlanSource | None = None, catalog_path: Path | None = None, scenario_interpreter=None) -> FastAPI:
    source = plan_source or JsonPlanSource(ROOT / "data" / "plans.json")
    store = ComparisonStore(db_path if db_path is not None else Path(
        os.environ.get("ADVISOR_DB_PATH", str(ROOT / ".data" / "advisor.sqlite3"))
    ))

    catalog = CatalogStore(catalog_path or Path(os.getenv("PLAN_CATALOG_DB_PATH", str(ROOT / ".data" / "plans.sqlite3"))))
    agent_router, close_agent = create_agent_router()

    from backend.scenario.api import router as scenario_router
    chat_router, initialize_chat = scenario_router(store, catalog, source, scenario_interpreter)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        initialize_chat()
        catalog.initialize()
        source.list_plans()  # Fail early when the local catalog is invalid.
        try:
            yield
        finally:
            close_agent()

    app = FastAPI(title="Smart Power Plan Advisor", version="0.1.0", lifespan=lifespan)
    app.include_router(create_router())
    app.include_router(agent_router)
    app.include_router(chat_router)
    app.include_router(create_catalog_router(catalog, Path(os.getenv("PLAN_DATA_DIR", str(ROOT / "data")))))

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = perf_counter()
        response = await call_next(request)
        logger.info("method=%s path=%s status=%s duration_ms=%.1f", request.method,
                    request.url.path, response.status_code, (perf_counter() - started) * 1000)
        return response

    @app.get("/api/health")
    def health():
        try:
            store.healthy()
            source.list_plans()
        except Exception:
            logger.exception("Readiness check failed")
            raise HTTPException(503, "Storage or plan source is unavailable") from None
        return {"status": "ok", "data_mode": "demo", "storage": "sqlite"}

    @app.get("/api/plans")
    def plans():
        catalog = source.list_plans()
        return {"data_mode": "demo", "plans": catalog}

    @app.post("/api/comparisons", response_model=ComparisonResult, status_code=201)
    def create_comparison(payload: ComparisonRequest):
        try:
            if payload.data_source == "pdf":
                from backend.catalog.compare import compare_catalog
                result = compare_catalog(payload, catalog)
            else:
                result = compare(payload, source)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        store.save(result)
        return result

    @app.get("/api/comparisons/{comparison_id}", response_model=ComparisonResult)
    def get_comparison(comparison_id: UUID):
        result = store.get(str(comparison_id))
        if result is None:
            raise HTTPException(404, "Comparison not found")
        return result

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "frontend" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    return app


app = create_app()
