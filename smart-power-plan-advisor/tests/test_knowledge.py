import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import tiktoken
    from backend.knowledge.documents import build_corpus, child_texts, extract_page, source_path
    from backend.knowledge.graph import build_graph
    from backend.knowledge.providers import Providers, create_index, verify_index
except ImportError as error:
    raise unittest.SkipTest("Install requirements-rag-dev.txt for optional RAG tests") from error

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.knowledge.api import create_router
from backend.knowledge.config import CHUNK_POLICY, DIMENSIONS, EMBEDDING_MODEL, Settings
from backend.knowledge.ingest import publish
from backend.knowledge.models import GeneratedAnswer, KnowledgeUnavailable

DOC_ID = "a" * 24
TEXT = "Contract Term 12 Months. Monthly Bill Credit: $125.00 Per billing cycle > 999 kWh. TDU charges passed through as billed."


def manifest():
    return {"schema_version": 1, "index_name": "power-plan-documents", "namespace": "power-plans-corpus",
            "corpus_id": "corpus", "embedding_model": EMBEDDING_MODEL, "dimensions": DIMENSIONS,
            "chunk_policy": CHUNK_POLICY, "chunks": 1,
            "documents": [{"id": DOC_ID, "filename": "test.pdf", "sha256": "hash", "pages": [1]}]}


def match():
    return {"id": "child", "score": 0.8, "metadata": {
        "document_id": DOC_ID, "document_hash": "hash", "corpus_id": "corpus", "filename": "test.pdf",
        "parent_id": "parent", "parent_text": TEXT, "page": 1}}


class FakeProviders:
    def __init__(self):
        self.matches = [match()]
        self.generate_calls = 0
        self.retrieval = None
        self.closed = False
        self.generated = GeneratedAnswer(answer="The contract term is 12 months.", abstained=False,
                                         evidence=[{"source_id": "S1", "quote": "Contract Term 12 Months."}])

    def connect(self):
        pass

    def retrieve(self, question, active, document_id):
        self.retrieval = (question, active["namespace"], document_id)
        return self.matches

    def generate(self, question, context):
        self.generate_calls += 1
        self.context = context
        return self.generated

    def close(self):
        self.closed = True


class GraphTests(unittest.TestCase):
    def run_graph(self, providers):
        return build_graph(providers, manifest()).invoke({"question": "Contract term?", "document_id": DOC_ID})["result"]

    def test_parent_expansion_deduplication_and_citation(self):
        providers = FakeProviders()
        providers.matches.append(copy.deepcopy(providers.matches[0]))
        answer = self.run_graph(providers)
        self.assertFalse(answer.abstained)
        self.assertEqual(len(providers.context), 1)
        self.assertEqual(providers.context[0]["text"], TEXT)
        self.assertEqual(answer.citations[0].url, f"/api/knowledge/documents/{DOC_ID}#page=1")
        self.assertEqual(providers.retrieval[2], DOC_ID)

    def test_missing_low_score_or_wrong_version_evidence_skips_llm(self):
        for change in ("empty", "low", "version", "document", "hash", "page"):
            with self.subTest(change=change):
                providers = FakeProviders()
                if change == "empty":
                    providers.matches = []
                elif change == "low":
                    providers.matches[0]["score"] = 0.1
                else:
                    key = {"version": "corpus_id", "document": "document_id", "hash": "document_hash", "page": "page"}[change]
                    providers.matches[0]["metadata"][key] = "wrong"
                self.assertTrue(self.run_graph(providers).abstained)
                self.assertEqual(providers.generate_calls, 0)

    def test_unknown_or_fabricated_citations_abstain(self):
        for evidence in ([{"source_id": "S9", "quote": "Contract Term 12 Months."}],
                         [{"source_id": "S1", "quote": "The delivery fee is five dollars."}], []):
            providers = FakeProviders()
            providers.generated = GeneratedAnswer(answer="Unsupported answer", abstained=False, evidence=evidence)
            self.assertTrue(self.run_graph(providers).abstained)

    def test_model_refusal_and_explicit_abstention(self):
        for generated in (None, GeneratedAnswer(answer="TDU rates are not specified.", abstained=True, evidence=[])):
            providers = FakeProviders()
            providers.generated = generated
            result = self.run_graph(providers)
            self.assertTrue(result.abstained)
            self.assertEqual(result.citations, [])

    def test_abstention_facts_need_valid_citations_too(self):
        providers = FakeProviders()
        providers.generated = GeneratedAnswer(answer="Cannot answer, but invented fees are $500.", abstained=True,
                                               evidence=[{"source_id": "S99", "quote": "Contract Term 12 Months."}])
        result = self.run_graph(providers)
        self.assertTrue(result.abstained)
        self.assertNotIn("$500", result.answer)
        providers.generated = GeneratedAnswer(answer="I cannot calculate a full bill; charges are passed through.", abstained=True,
                                               evidence=[{"source_id": "S1", "quote": "TDU charges passed through as billed."}])
        result = self.run_graph(providers)
        self.assertTrue(result.abstained)
        self.assertEqual(len(result.citations), 1)


class CorpusTests(unittest.TestCase):
    def test_table_cells_preserve_wrapped_answers_without_question_interleaving(self):
        table = SimpleNamespace(bbox=(0, 0, 100, 100), extract=lambda: [
            ["Do I have a termination fee\nwhen leaving?", "Yes. A termination fee of $20 multiplied by the number of\nmonths remaining on the term of your contract will apply."]
        ])
        page = MagicMock()
        page.find_tables.return_value = [table]
        page.filter.return_value.extract_text.return_value = "Header outside table"
        text = extract_page(page)
        self.assertIn("Do I have a termination fee when leaving? | Yes.", text)
        self.assertIn("number of months remaining", text)
        self.assertIn("Header outside table", text)

    def test_chunks_preserve_text_boundaries_and_token_budget(self):
        text = "\n".join(f"Clause {i}: Bill credit > 999 kWh; energy 12.7645Â¢. " for i in range(100))
        encoding = tiktoken.get_encoding("cl100k_base")
        chunks = child_texts(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertIn(chunk, text)
            self.assertNotIn("\ufffd", chunk)
            self.assertLessEqual(len(encoding.encode(chunk)), 450)
        for line in text.splitlines():
            self.assertTrue(any(line.strip() in chunk for chunk in chunks))

    def test_duplicate_pages_stable_ids_and_revision_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.pdf").write_bytes(b"pdf-v1")
            settings = Settings(data_dir=root)
            with patch("backend.knowledge.documents.pdfplumber.open") as opened:
                page = SimpleNamespace(extract_text=lambda: TEXT, find_tables=lambda: [])
                opened.return_value.__enter__.return_value.pages = [page, page]
                active, records = build_corpus(settings)
                again, again_records = build_corpus(settings)
                self.assertEqual(active, again)
                self.assertEqual(records, again_records)
                self.assertEqual(active["documents"][0]["pages"], [1])
                self.assertTrue(all(r["metadata"]["page"] == 1 for r in records))
                (root / "one.pdf").write_bytes(b"pdf-v2")
                revised, _ = build_corpus(settings)
                self.assertNotEqual(active["namespace"], revised["namespace"])

    def test_blank_pages_preserve_citations_and_all_blank_documents_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.pdf").write_bytes(b"pdf")
            blank = SimpleNamespace(extract_text=lambda: "", find_tables=lambda: [], objects={})
            text = SimpleNamespace(extract_text=lambda: TEXT, find_tables=lambda: [])
            with patch("backend.knowledge.documents.pdfplumber.open") as opened:
                opened.return_value.__enter__.return_value.pages = [blank, text, blank]
                active, records = build_corpus(Settings(data_dir=root))
                self.assertEqual(active["documents"][0]["pages"], [2])
                self.assertEqual(active["documents"][0]["skipped_blank_pages"], [1, 3])
                self.assertTrue(all(record["metadata"]["page"] == 2 for record in records))
                opened.return_value.__enter__.return_value.pages = [blank]
                with self.assertRaisesRegex(ValueError, "no usable pages"):
                    build_corpus(Settings(data_dir=root))
                scanned = SimpleNamespace(extract_text=lambda: "", find_tables=lambda: [], objects={"image": [{}]})
                opened.return_value.__enter__.return_value.pages = [scanned]
                with self.assertRaisesRegex(ValueError, "review required"):
                    build_corpus(Settings(data_dir=root))

    def test_scanned_and_oversized_pages_fail_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.pdf").write_bytes(b"pdf")
            for text in ("", "word " * 2000):
                with patch("backend.knowledge.documents.pdfplumber.open") as opened:
                    opened.return_value.__enter__.return_value.pages = [SimpleNamespace(extract_text=lambda: text, find_tables=lambda: [])]
                    with self.assertRaisesRegex(ValueError, "review required"):
                        build_corpus(Settings(data_dir=root))

    def test_failed_upsert_does_not_replace_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(manifest_path=Path(directory) / "manifest.json")
            settings.manifest_path.write_text("previous")
            providers = MagicMock()
            providers.upsert.side_effect = RuntimeError("network failure")
            with self.assertRaises(RuntimeError):
                publish(settings, manifest(), [], providers)
            self.assertEqual(settings.manifest_path.read_text(), "previous")
            providers.upsert.side_effect = None
            publish(settings, manifest(), [], providers)
            self.assertEqual(settings.manifest(), manifest())

    def test_source_cannot_escape_data_or_serve_changed_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(data_dir=root, manifest_path=root / "manifest.json")
            data = manifest()
            data["documents"][0]["filename"] = "../outside.pdf"
            settings.manifest_path.write_text(json.dumps(data))
            with self.assertRaises(FileNotFoundError):
                source_path(settings, DOC_ID)
            data["documents"][0]["filename"] = "test.pdf"
            settings.manifest_path.write_text(json.dumps(data))
            (root / "test.pdf").write_bytes(b"changed")
            with self.assertRaises(FileNotFoundError):
                source_path(settings, DOC_ID)


class ProviderTests(unittest.TestCase):
    def test_index_compatibility(self):
        for dimension, metric, ready in ((1536, "cosine", True), (3072, "dotproduct", True), (3072, "cosine", False)):
            with self.assertRaises(KnowledgeUnavailable):
                verify_index(SimpleNamespace(dimension=dimension, metric=metric, status={"ready": ready}))

    @patch("backend.knowledge.providers.Pinecone")
    @patch("backend.knowledge.providers.OpenAI")
    def test_embedding_and_vector_query_contract(self, openai, pinecone):
        settings = Settings(openai_key="fake", pinecone_key="fake")
        providers = Providers(settings)
        providers.index = MagicMock()
        openai.return_value.embeddings.create.return_value.data = [SimpleNamespace(index=0, embedding=[0.0] * DIMENSIONS)]
        providers.index.query.return_value.matches = []
        providers.retrieve("question", manifest(), DOC_ID)
        args = providers.index.query.call_args.kwargs
        self.assertEqual(args["namespace"], "power-plans-corpus")
        self.assertEqual(args["filter"]["document_id"], {"$eq": DOC_ID})
        self.assertEqual(args["filter"]["corpus_id"], {"$eq": "corpus"})
        self.assertEqual(args["_request_timeout"], 30)
        self.assertEqual(openai.return_value.embeddings.create.call_args.kwargs["dimensions"], 3072)
        providers.close()
        openai.return_value.close.assert_called_once()
        providers.index.close.assert_called_once()

    @patch("backend.knowledge.providers.Pinecone")
    def test_index_creation_is_explicit_and_compatible(self, pinecone):
        pinecone.return_value.has_index.return_value = False
        create_index(Settings(pinecone_key="fake"))
        args = pinecone.return_value.create_index.call_args.kwargs
        self.assertEqual(args["dimension"], 3072)
        self.assertEqual(args["metric"], "cosine")
        self.assertEqual(args["deletion_protection"], "enabled")


class KnowledgeApiTests(unittest.TestCase):
    def test_validation_missing_config_and_secret_free_status(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(manifest_path=Path(directory) / "manifest.json")
            app = FastAPI()
            app.include_router(create_router(settings))
            with TestClient(app) as client:
                self.assertFalse(client.get("/api/knowledge/status").json()["configured"])
                self.assertEqual(client.post("/api/knowledge/ask", json={"question": "term?"}).status_code, 503)
                for payload in ({"question": " "}, {"question": "x" * 2001}, {"question": "term?", "extra": 1}):
                    self.assertEqual(client.post("/api/knowledge/ask", json=payload).status_code, 422)

    def test_grounded_answer_and_sanitized_provider_error(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(openai_key="fake-secret", pinecone_key="fake-secret", manifest_path=Path(directory) / "manifest.json")
            settings.manifest_path.write_text(json.dumps(manifest()))
            providers = FakeProviders()
            app = FastAPI()
            app.include_router(create_router(settings, lambda settings: providers))
            with TestClient(app) as client:
                result = client.post("/api/knowledge/ask", json={"question": "Contract term?", "document_id": DOC_ID})
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.json()["abstained"])
                self.assertTrue(providers.closed)
                self.assertNotIn("fake-secret", client.get("/api/knowledge/status").text)
                missing = client.post("/api/knowledge/ask", json={"question": "term?", "document_id": "b" * 24})
                self.assertEqual(missing.status_code, 404)
                providers.retrieve = MagicMock(side_effect=RuntimeError("fake-secret"))
                result = client.post("/api/knowledge/ask", json={"question": "term?"})
                self.assertEqual(result.status_code, 502)
                self.assertNotIn("fake-secret", result.text)


if __name__ == "__main__":
    unittest.main()
