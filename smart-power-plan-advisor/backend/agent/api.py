"""Optional API surface; base app startup requires no LangGraph/OpenAI imports."""
import threading
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from backend.knowledge.config import Settings
from backend.knowledge.models import KnowledgeUnavailable


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


class Resume(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    interrupt_id: str = Field(min_length=1, max_length=200)


def create_router(settings=None, model_factory=None, provider_factory=None):
    settings = settings or Settings.from_env()
    router = APIRouter(prefix="/api/agent", tags=["Document agent"])
    runtime = None
    guard = threading.Lock()

    def get_runtime():
        nonlocal runtime
        if not settings.configured and model_factory is None:
            raise HTTPException(503, "Configure OpenAI and Pinecone keys to use the document agent.")
        try:
            with guard:
                if runtime is None:
                    from backend.agent.runtime import Runtime
                    runtime = Runtime(settings, model_factory, provider_factory)
            return runtime
        except ImportError:
            raise HTTPException(503, "Install requirements-rag.txt to use the document agent.") from None

    def execute(fn):
        try:
            return fn()
        except KnowledgeUnavailable:
            raise HTTPException(503, "Document agent needs an active indexed corpus. Check configuration and ingestion.") from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "Document agent is temporarily unavailable.") from None

    def token(authorization):
        return authorization[7:] if authorization.startswith("Bearer ") else ""

    @router.get("/status")
    def status():
        import importlib.util
        available = all(importlib.util.find_spec(name) is not None for name in ("langgraph", "openai", "pinecone", "tiktoken"))
        return {**settings.status(), "dependencies_available": available, "memory": "in_process", "restart_clears_history": True}

    @router.post("/threads", status_code=201)
    def create():
        return execute(lambda: get_runtime().create())

    @router.post("/threads/{thread_id}/messages")
    def message(thread_id: UUID, payload: Message, authorization: str = Header(default="")):
        return execute(lambda: get_runtime().run(str(thread_id), token(authorization), payload))

    @router.post("/threads/{thread_id}/resume")
    def resume(thread_id: UUID, payload: Resume, authorization: str = Header(default="")):
        return execute(lambda: get_runtime().run(str(thread_id), token(authorization), payload, resume=True))

    @router.delete("/threads/{thread_id}")
    def clear(thread_id: UUID, authorization: str = Header(default="")):
        return execute(lambda: get_runtime().delete(str(thread_id), token(authorization)))

    def close():
        if runtime:
            runtime.close()

    return router, close
