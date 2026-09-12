from contextlib import suppress

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.knowledge.config import Settings
from backend.knowledge.models import Answer, KnowledgeUnavailable, Question


def create_router(settings=None, provider_factory=None):
    settings = settings or Settings.from_env()
    router = APIRouter(prefix="/api/knowledge", tags=["Plan documents"])

    @router.get("/status")
    def status():
        return settings.status()

    @router.post("/ask", response_model=Answer)
    def ask(payload: Question):
        providers = None
        try:
            if not settings.configured and provider_factory is None:
                raise KnowledgeUnavailable("Document Q&A needs configured OpenAI and Pinecone keys. The demo calculator remains available.")
            manifest = settings.manifest()
            if payload.document_id and not any(doc["id"] == payload.document_id for doc in manifest["documents"]):
                raise HTTPException(404, "Indexed document not found")
            from backend.knowledge.graph import build_graph
            if provider_factory:
                providers = provider_factory(settings)
            else:
                from backend.knowledge.providers import Providers
                providers = Providers(settings)
            providers.connect()
            return build_graph(providers, manifest).invoke(payload.model_dump(), {"recursion_limit": 8})["result"]
        except KnowledgeUnavailable as error:
            raise HTTPException(503, str(error)) from None
        except ImportError:
            raise HTTPException(503, "Install the optional RAG dependencies to use document Q&A.") from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "Document Q&A is temporarily unavailable. Check provider configuration or try again shortly.") from None
        finally:
            if providers:
                with suppress(Exception):
                    providers.close()

    @router.get("/documents/{document_id}")
    def document(document_id: str):
        try:
            from backend.knowledge.documents import source_path
            path = source_path(settings, document_id)
            return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")
        except (KnowledgeUnavailable, FileNotFoundError):
            raise HTTPException(404, "Indexed source document is unavailable or has changed; reingest it.") from None
        except ImportError:
            raise HTTPException(503, "Install the optional RAG dependencies.") from None

    return router
