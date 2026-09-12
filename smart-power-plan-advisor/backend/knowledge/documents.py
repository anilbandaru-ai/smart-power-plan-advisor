"""Page-preserving extraction and deterministic parent/child chunking."""

import hashlib
import json
from pathlib import Path

import pdfplumber
import tiktoken

from backend.knowledge.config import CHUNK_POLICY, DIMENSIONS, EMBEDDING_MODEL, Settings
from backend.knowledge.models import DocumentReviewRequired


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def extract_page(page) -> str:
    tables = page.find_tables()
    if not tables:
        return (page.extract_text() or "").strip()

    def contains(outer, inner):
        return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]

    # An EFL may have a full-page table containing a smaller price-example table.
    # Reading both would duplicate content; keep the outer table's cell text.
    outer_tables = [table for table in tables if not any(
        other is not table and other.bbox != table.bbox and contains(other.bbox, table.bbox)
        for other in tables
    )]

    def outside_tables(obj):
        if obj.get("object_type") != "char":
            return True
        center_x = (obj["x0"] + obj["x1"]) / 2
        center_y = (obj["top"] + obj["bottom"]) / 2
        return not any(t.bbox[0] <= center_x <= t.bbox[2] and t.bbox[1] <= center_y <= t.bbox[3] for t in outer_tables)

    parts = [(page.filter(outside_tables).extract_text() or "").strip()]
    for table in sorted(outer_tables, key=lambda t: (t.bbox[1], t.bbox[0])):
        for row in table.extract():
            cells = [" ".join(cell.split()) for cell in row if cell and cell.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(part for part in parts if part)


def child_texts(text: str, size=450, overlap=60) -> list[str]:
    if size <= overlap or overlap < 0:
        raise ValueError("Chunk size must exceed nonnegative overlap")
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text, disallowed_special=())
    _, offsets = encoding.decode_with_offsets(tokens)
    offsets.append(len(text))
    chunks, start = [], 0
    while start < len(tokens):
        end = min(start + size, len(tokens))
        # Prefer a complete line in the latter half of a chunk.
        if end < len(tokens):
            boundary = text.rfind("\n", offsets[start + size // 2], offsets[end])
            if boundary > offsets[start]:
                while end > start and offsets[end] > boundary + 1:
                    end -= 1
        value = text[offsets[start]:offsets[end]].strip()
        if value:
            chunks.append(value)
        if end == len(tokens):
            break
        start = max(start + 1, end - overlap)
    return chunks


def build_corpus(settings: Settings):
    encoding = tiktoken.get_encoding("cl100k_base")
    documents, records = [], []
    root = settings.data_dir.resolve()
    for path in sorted(root.rglob("*.pdf")):
        if not path.resolve().is_relative_to(root):
            raise ValueError("PDF path escapes data directory")
        relative = path.relative_to(root).as_posix()
        content_hash = digest(path.read_bytes())
        document_id = digest(relative.encode())[:24]
        seen, pages = set(), []
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                text = "\n".join(line.rstrip() for line in extract_page(page).splitlines()).strip()
                count = len(encoding.encode(text, disallowed_special=()))
                if count < 20 or count > 1800:
                    raise DocumentReviewRequired(f"{relative}, page {number}: text is empty/scanned, too short, or exceeds 1800 tokens; review required")
                page_hash = digest(text.encode())
                if page_hash in seen:
                    continue
                seen.add(page_hash)
                pages.append(number)
                parent_id = f"{document_id}-{content_hash[:16]}-p{number}"
                for i, child in enumerate(child_texts(text)):
                    records.append({"id": f"{parent_id}-c{i}", "metadata": {
                        "document_id": document_id, "filename": relative,
                        "document_hash": content_hash, "page": number, "parent_id": parent_id,
                        "parent_text": text, "text": child, "chunk_policy": CHUNK_POLICY,
                    }})
        documents.append({"id": document_id, "filename": relative, "sha256": content_hash, "pages": pages})
    if not records:
        raise ValueError("No text PDFs found under data/")
    version_input = {"documents": documents, "embedding": EMBEDDING_MODEL,
                     "dimensions": DIMENSIONS, "chunk_policy": CHUNK_POLICY}
    corpus_id = digest(json.dumps(version_input, sort_keys=True).encode())[:24]
    for record in records:
        record["metadata"]["corpus_id"] = corpus_id
        if len(json.dumps(record["metadata"], ensure_ascii=False).encode()) > 35000:
            raise ValueError("Page metadata exceeds safe record size; review required")
    manifest = {"schema_version": 1, "index_name": settings.index_name,
                "namespace": f"{settings.namespace_prefix}-{corpus_id}", "corpus_id": corpus_id,
                "embedding_model": EMBEDDING_MODEL, "dimensions": DIMENSIONS,
                "chunk_policy": CHUNK_POLICY, "documents": documents, "chunks": len(records)}
    return manifest, records


def source_path(settings: Settings, document_id: str) -> Path:
    doc = next((d for d in settings.manifest()["documents"] if d["id"] == document_id), None)
    if doc is None:
        raise FileNotFoundError
    path = (settings.data_dir / doc["filename"]).resolve()
    if not path.is_relative_to(settings.data_dir.resolve()) or path.suffix.lower() != ".pdf":
        raise FileNotFoundError
    if not path.is_file() or digest(path.read_bytes()) != doc["sha256"]:
        raise FileNotFoundError
    return path
