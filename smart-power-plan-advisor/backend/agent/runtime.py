"""Single-process conversation lifecycle; external dependencies never enter graph state."""
import secrets
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.agent.graph import build_graph


@dataclass
class Session:
    token: str
    touched: float
    lock: object = field(default_factory=threading.Lock)
    turns: int = 0
    pending: str | None = None
    corpus: str | None = None
    turn_id: str = ""
    cache: dict = field(default_factory=dict)
    failed: bool = False


class Runtime:
    def __init__(self, settings, model_factory=None, provider_factory=None, clock=time.monotonic):
        self.settings, self.clock = settings, clock
        self.model_factory, self.provider_factory = model_factory, provider_factory
        self.saver = InMemorySaver()
        self.graph = build_graph(self.saver)
        self.sessions = {}
        self.guard = threading.Lock()

    def expire(self):
        for key, session in list(self.sessions.items()):
            if self.clock() - session.touched >= 1800 and session.lock.acquire(blocking=False):
                try:
                    self.saver.delete_thread(key)
                    del self.sessions[key]
                finally:
                    session.lock.release()

    def create(self):
        self.settings.manifest()
        with self.guard:
            self.expire()
            if len(self.sessions) >= 100:
                raise HTTPException(429, "Conversation capacity reached; try again later.")
            key, token = str(uuid4()), secrets.token_urlsafe(32)
            self.sessions[key] = Session(token, self.clock())
        return {"thread_id": key, "token": token, "expires_in_seconds": 1800}

    def acquire(self, key, token):
        with self.guard:
            self.expire()
            session = self.sessions.get(key)
            if not session or not secrets.compare_digest(session.token, token):
                raise HTTPException(404, "Conversation expired or unavailable. Start a new conversation.")
            if not session.lock.acquire(blocking=False):
                raise HTTPException(409, "A request is already running in this conversation.")
            return session

    def delete(self, key, token):
        session = self.acquire(key, token)
        try:
            with self.guard:
                self.saver.delete_thread(key)
                del self.sessions[key]
        finally:
            session.lock.release()
        return {"cleared": True}

    def run(self, key, token, payload, resume=False):
        session = self.acquire(key, token)
        model = provider = None
        fingerprint = (resume, payload.model_dump_json())
        try:
            request_id = str(payload.request_id)
            if request_id in session.cache:
                old, result = session.cache[request_id]
                if old != fingerprint:
                    raise HTTPException(409, "Request ID was already used for different input.")
                return result
            if session.failed:
                raise HTTPException(409, "This conversation stopped. Start a new conversation.")
            manifest = self.settings.manifest()
            if resume:
                if session.pending != payload.interrupt_id or not session.pending:
                    raise HTTPException(409, "Clarification is no longer pending.")
                if manifest["corpus_id"] != session.corpus:
                    session.failed = True
                    raise HTTPException(409, "Indexed documents changed. Start a new conversation.")
                value = Command(resume=payload.message)
            else:
                if session.pending:
                    raise HTTPException(409, "Answer the pending clarification or start a new conversation.")
                if session.turns >= 20:
                    raise HTTPException(409, "Conversation turn limit reached. Start a new conversation.")
                if payload.document_id and payload.document_id not in {d["id"] for d in manifest["documents"]}:
                    raise HTTPException(404, "Indexed document not found.")
                session.turns += 1
                session.turn_id = str(uuid4())
                session.corpus = manifest["corpus_id"]
                value = {"messages": [HumanMessage(content=payload.message)], "manifest": manifest,
                         "document_id": payload.document_id, "evidence": {}, "calls": 0, "tools": 0,
                         "searches": 0, "activity": [], "result": None, "stopped": False}
            if self.model_factory:
                model = self.model_factory(self.settings)
            else:
                from backend.agent.model import Model
                model = Model(self.settings)

            def retrieve(query, corpus, doc_id):
                nonlocal provider
                if provider is None:
                    if self.provider_factory:
                        provider = self.provider_factory(self.settings)
                    else:
                        from backend.knowledge.providers import Providers
                        provider = Providers(self.settings)
                    provider.connect()
                return provider.retrieve(query, corpus, doc_id)

            config = {"configurable": {"thread_id": key, "model": model, "retrieve": retrieve}, "recursion_limit": 30}
            try:
                output = self.graph.invoke(value, config)
            except Exception:
                session.failed = True
                raise HTTPException(502, "Document agent is temporarily unavailable. Start a new conversation and try again.") from None
            interruptions = output.get("__interrupt__", ())
            if interruptions:
                pause = interruptions[0]
                session.pending = pause.id
                result = {"status": "needs_input", "interrupt_id": pause.id, "question": pause.value["question"], "citations": []}
            else:
                session.pending = None
                result = output["result"]
                if result["status"] == "limit_reached":
                    session.failed = True
            result = {**result, "thread_id": key, "turn_id": session.turn_id, "activity": output.get("activity", [])}
            session.cache[request_id] = (fingerprint, result)
            return result
        finally:
            for dependency in (model, provider):
                if dependency:
                    with suppress(Exception):
                        dependency.close()
            session.touched = self.clock()
            session.lock.release()

    def close(self):
        with self.guard:
            for key in self.sessions:
                self.saver.delete_thread(key)
            self.sessions.clear()
