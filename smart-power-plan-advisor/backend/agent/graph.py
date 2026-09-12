"""ReAct fundamentals: reason, conditional routing, action, observation, repeat."""
import hashlib
import json
from typing import Annotated, TypedDict

import tiktoken
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.knowledge.evidence import abstain, select_context, validate_answer


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=2000)
    document_id: str | None = None


class Clarify(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=500)


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    manifest: dict
    document_id: str | None
    evidence: dict
    calls: int
    tools: int
    searches: int
    activity: list[str]
    result: dict | None
    stopped: bool


def build_graph(checkpointer):
    encoding = tiktoken.get_encoding("cl100k_base")

    def too_large(state):
        content = json.dumps([m.model_dump() for m in state["messages"]], default=str)
        content += json.dumps(state["evidence"])
        # Reserve space for tool schemas and instructions under the 12k input ceiling.
        return len(encoding.encode(content, disallowed_special=())) > 10000

    def reason(state, config):
        if state["calls"] >= 5 or state["tools"] >= 8 or too_large(state):
            return {"stopped": True}
        model = config["configurable"]["model"]
        message = model.decide(state["messages"], state.get("document_id"), require_search=state["searches"] == 0)
        return {"messages": [message], "calls": state["calls"] + 1}

    def route(state):
        if state.get("stopped"):
            return "limit"
        calls = state["messages"][-1].tool_calls
        if not calls:
            return "finalize"
        if len(calls) == 1 and calls[0]["name"] == "ask_user":
            try:
                Clarify.model_validate(calls[0]["args"])
                return "clarify"
            except ValidationError:
                pass
        return "action"

    def action(state, config):
        calls = state["messages"][-1].tool_calls
        observations, evidence = [], dict(state["evidence"])
        searches = state["searches"]
        activity = list(state["activity"])
        for call in calls:
            output = {"error": "Invalid tool or arguments. Call one allowed tool at a time."}
            if len(calls) == 1:
                try:
                    if call["name"] == "list_indexed_documents" and call["args"] == {}:
                        output = {"documents": [{k: d[k] for k in ("id", "filename", "pages")} for d in state["manifest"]["documents"]]}
                        activity.append("Listed indexed documents")
                    elif call["name"] == "search_document_evidence":
                        args = Search.model_validate(call["args"])
                        scope = state.get("document_id")
                        if scope and args.document_id and scope != args.document_id:
                            raise ValueError("Selected document scope cannot be overridden")
                        doc_id = scope or args.document_id
                        if doc_id and doc_id not in {d["id"] for d in state["manifest"]["documents"]}:
                            raise ValueError("Unknown indexed document")
                        if searches >= 3:
                            output = {"error": "Search budget exhausted. Finish with available evidence."}
                        else:
                            searches += 1
                            matches = config["configurable"]["retrieve"](args.query, state["manifest"], doc_id)
                            selected = select_context(matches, state["manifest"], doc_id)
                            for source in selected:
                                doc = next(d for d in state["manifest"]["documents"] if d["id"] == source["document_id"])
                                identity = f"{state['manifest']['corpus_id']}:{doc['sha256']}:{source['document_id']}:{source['page']}"
                                source["source_id"] = "S" + hashlib.sha256(identity.encode()).hexdigest()[:16]
                                evidence[source["source_id"]] = source
                            output = {"sources": selected}
                            activity.append(f"Searched documents: {len(selected)} supporting page(s)")
                except (ValidationError, ValueError):
                    output = {"error": "Invalid tool arguments or document scope. Use an indexed document ID and a nonempty query."}
            observations.append(ToolMessage(content=json.dumps(output), tool_call_id=call["id"], name=call["name"]))
        return {"messages": observations, "tools": state["tools"] + len(calls), "searches": searches,
                "evidence": evidence, "activity": activity}

    def clarify(state):
        call = state["messages"][-1].tool_calls[0]
        question = Clarify.model_validate(call["args"]).question
        answer = interrupt({"question": question})
        return {"messages": [ToolMessage(content=json.dumps({"user_clarification": answer}),
                    tool_call_id=call["id"], name="ask_user")],
                "tools": state["tools"] + 1, "activity": state["activity"] + ["Received clarification"]}

    def finalize(state, config):
        if too_large(state):
            return limit(state)
        if not state["evidence"]:
            answer = abstain("I can answer indexed document questions with supporting pages. Please specify the document and question; I cannot calculate bills or rank offers.")
        else:
            generated = config["configurable"]["model"].finalize(state["messages"], list(state["evidence"].values()))
            answer = validate_answer(generated, list(state["evidence"].values()))
        return {"result": {"status": "insufficient_evidence" if answer.abstained else "answered",
                           **answer.model_dump()}, "messages": [AIMessage(content=answer.answer)]}

    def limit(state):
        answer = "This conversation reached its processing limit. Start a new conversation with a more specific document question."
        # Discard unfinished tool messages at the runtime turn boundary, not inside a tool exchange.
        return {"result": {"status": "limit_reached", "answer": answer, "citations": []}}

    graph = StateGraph(State)
    for name, fn in [("reason", reason), ("action", action), ("clarify", clarify), ("finalize", finalize), ("limit", limit)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "reason")
    graph.add_conditional_edges("reason", route)
    graph.add_edge("action", "reason")
    graph.add_edge("clarify", "reason")
    graph.add_edge("finalize", END)
    graph.add_edge("limit", END)
    return graph.compile(checkpointer=checkpointer)
