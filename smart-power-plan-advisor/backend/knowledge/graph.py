from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.knowledge.models import Answer, Citation


class State(TypedDict, total=False):
    question: str
    document_id: str | None
    matches: list[dict]
    context: list[dict]
    generated: object
    result: Answer


def abstain(message="I could not find sufficient supporting evidence in the indexed plan documents."):
    return Answer(answer=message, abstained=True, citations=[])


def build_graph(providers, manifest):
    documents = {doc["id"]: doc for doc in manifest["documents"]}

    def retrieve(state):
        return {"matches": providers.retrieve(state["question"], manifest, state.get("document_id"))}

    def context(state):
        selected, seen = [], set()
        for match in sorted(state["matches"], key=lambda item: item.get("score", 0), reverse=True):
            metadata = match.get("metadata") or {}
            doc = documents.get(metadata.get("document_id"))
            if (not doc or match.get("score", 0) < 0.25
                    or metadata.get("corpus_id") != manifest["corpus_id"]
                    or metadata.get("document_hash") != doc["sha256"]
                    or metadata.get("page") not in doc["pages"]
                    or metadata.get("filename") != doc["filename"]
                    or (state.get("document_id") and metadata.get("document_id") != state["document_id"])):
                continue
            parent_id = metadata.get("parent_id")
            text = metadata.get("parent_text")
            if not parent_id or parent_id in seen or not isinstance(text, str) or not text.strip() or len(text) > 15000:
                continue
            seen.add(parent_id)
            selected.append({"source_id": f"S{len(selected) + 1}", "document_id": doc["id"],
                             "filename": doc["filename"], "page": int(metadata["page"]), "text": text})
            if len(selected) == 4:
                break
        return {"context": selected}

    def generate(state):
        return {"generated": providers.generate(state["question"], state["context"])}

    def validate(state):
        value = state["generated"]
        if value is None:
            return {"result": abstain("The model did not return a usable grounded answer. Try a more specific document question.")}
        sources = {source["source_id"]: source for source in state["context"]}
        if not value.evidence:
            return {"result": abstain()}
        citations = []
        seen = set()
        for evidence in value.evidence:
            source = sources.get(evidence.source_id)
            quote = " ".join(evidence.quote.split())
            if not source or len(quote) < 20 or quote not in " ".join(source["text"].split()):
                return {"result": abstain("The answer could not be linked to exact supporting document excerpts.")}
            if (evidence.source_id, quote) in seen:
                continue
            seen.add((evidence.source_id, quote))
            citations.append(Citation(
                source_id=source["source_id"], document_id=source["document_id"],
                filename=source["filename"], page=source["page"], excerpt=quote,
                url=f"/api/knowledge/documents/{source['document_id']}#page={source['page']}",
            ))
        return {"result": Answer(answer=value.answer, abstained=value.abstained, citations=citations)}

    graph = StateGraph(State)
    graph.add_node("retrieve", retrieve)
    graph.add_node("context", context)
    graph.add_node("generate", generate)
    graph.add_node("validate", validate)
    graph.add_node("abstain", lambda state: {"result": abstain()})
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "context")
    graph.add_conditional_edges("context", lambda state: "generate" if state["context"] else "abstain")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)
    graph.add_edge("abstain", END)
    return graph.compile()
