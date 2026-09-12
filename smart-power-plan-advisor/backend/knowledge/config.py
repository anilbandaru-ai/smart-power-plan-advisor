import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from backend.knowledge.models import KnowledgeUnavailable

ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_MODEL = "text-embedding-3-large"
DIMENSIONS = 3072
CHUNK_POLICY = "table-page-parent-1800-child-450-overlap-60-v2"


@dataclass(frozen=True)
class Settings:
    openai_key: str = field(default="", repr=False)
    pinecone_key: str = field(default="", repr=False)
    index_name: str = "power-plan-documents"
    namespace_prefix: str = "power-plans"
    model: str = "gpt-4.1-mini"
    cloud: str = "aws"
    region: str = "us-east-1"
    manifest_path: Path = ROOT / ".data" / "knowledge.json"
    data_dir: Path = ROOT / "data"

    @classmethod
    def from_env(cls):
        return cls(
            openai_key=os.getenv("OPENAI_API_KEY", "").strip(),
            pinecone_key=os.getenv("PINECONE_API_KEY", "").strip(),
            index_name=os.getenv("PINECONE_INDEX", "power-plan-documents").strip(),
            namespace_prefix=os.getenv("PINECONE_NAMESPACE", "power-plans").strip(),
            model=os.getenv("OPENAI_RAG_MODEL", "gpt-4.1-mini").strip(),
            cloud=os.getenv("PINECONE_CLOUD", "aws"),
            region=os.getenv("PINECONE_REGION", "us-east-1"),
            manifest_path=Path(os.getenv("RAG_MANIFEST_PATH") or ROOT / ".data" / "knowledge.json"),
        )

    @property
    def configured(self):
        return bool(self.openai_key and self.pinecone_key and self.index_name and self.namespace_prefix)

    def manifest(self):
        try:
            data = json.loads(self.manifest_path.read_text())
            if (data["schema_version"] != 1 or data["embedding_model"] != EMBEDDING_MODEL
                    or data["dimensions"] != DIMENSIONS or data["chunk_policy"] != CHUNK_POLICY
                    or data["index_name"] != self.index_name
                    or data["namespace"] != f"{self.namespace_prefix}-{data['corpus_id']}"
                    or not data["documents"]):
                raise ValueError("Incompatible manifest")
            return data
        except (OSError, ValueError, KeyError, TypeError):
            raise KnowledgeUnavailable("Plan documents are not indexed for this configuration. Run ingestion first.") from None

    def status(self):
        try:
            manifest = self.manifest()
            documents = [{key: doc[key] for key in ("id", "filename", "pages")}
                         for doc in manifest["documents"]]
            indexed = True
        except (KnowledgeUnavailable, KeyError, TypeError):
            documents, indexed = [], False
        return {"configured": self.configured, "indexed": indexed,
                "documents": documents, "embedding_model": EMBEDDING_MODEL,
                "dimensions": DIMENSIONS, "model": self.model,
                "live_readiness_checked": False}
