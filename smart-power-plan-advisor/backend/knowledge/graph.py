from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.knowledge.models import Answer
from backend.knowledge.evidence import abstain, select_context, validate_answer


class State(TypedDict, total=False):
    question: str
    document_id: str | None
    matches: list[dict]
    context: list[dict]
    generated: object
    result: Answer


def build_graph(providers, manifest):
    def retrieve(state):
        return {"matches": providers.retrieve(state["question"], manifest, state.get("document_id"))}

    def context(state):
        return {"context": select_context(state["matches"], manifest, state.get("document_id"))}

    def generate(state):
        return {"generated": providers.generate(state["question"], state["context"])}

    def validate(state):
        return {"result": validate_answer(state["generated"], state["context"])}

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
