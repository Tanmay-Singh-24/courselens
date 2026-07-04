"""CourseLens — retrieval graph (V3, corrective RAG).

Flow:  rewrite → retrieve → GRADE → (generate | reformulate+retry | refuse)

The grader is the honest "agentic" layer: after retrieval, an LLM judges whether
the retrieved context actually answers the question. If yes → generate. If no →
reformulate the query and retry (capped). If still no → refuse instead of
hallucinating. The grader is toggleable (ENABLE_GRADER) so V4 can measure its
effect; with it off, this reduces to the V1 linear pass.

Retrieval emits structured `sources` (labels + timestamps/paths/figure images) for
actionable citations; the grader emits `verdicts` the UI can surface.
"""
import json
import re
import time
from typing import Annotated, TypedDict

from langchain_groq import ChatGroq
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver

from backend.config import (
    ENABLE_GRADER,
    MAX_RETRIEVAL_ATTEMPTS,
    TEXT_MODEL,
    TOP_K,
    seconds_to_timestamp,
)
from backend.store import list_sources, similarity_search

# temperature=0: grounded, repeatable answers (and repeatable grading), not creativity.
llm = ChatGroq(model=TEXT_MODEL, temperature=0)

SYSTEM_PROMPT = (
    "You are CourseLens, a study assistant that answers questions grounded in the "
    "student's own course materials (lecture transcripts, slides, and figures). "
    "Answer using ONLY the provided context. If the answer isn't in the context, say "
    "so honestly instead of guessing. Cite each fact with the source label shown in "
    "the context, e.g. [Lecture 8 @ 14:32] or [slides — Figure (p.3)]."
)

# Reformulates only — never answers — so it can't pollute the search query.
REWRITE_PROMPT = (
    "Given the conversation so far and the latest user question, rewrite the question "
    "as a standalone search query that makes sense without the prior messages. Resolve "
    "references like 'it' or 'that' to the actual subject. If it's already standalone, "
    "return it unchanged. Output ONLY the query."
)

# Strict, anti-sycophancy: topically-adjacent-but-non-answering context is NOT relevant.
GRADER_PROMPT = (
    "You are a strict relevance grader for a retrieval system. Decide whether the "
    "retrieved context contains information that DIRECTLY answers the user's question. "
    "Be strict: context that is merely about a related topic, or mentions the subject "
    "without answering the question, is NOT relevant. Respond with ONLY a JSON object: "
    '{"relevant": true or false, "reason": "<one short sentence>"}'
)

# Used when the first search misses — try different words that might appear verbatim.
RETRY_PROMPT = (
    "The previous search did not find information that answers the question. Rewrite "
    "the search query using different words, synonyms, and more specific terms likely "
    "to appear verbatim in lecture transcripts or slides. Output ONLY the new query."
)


class State(TypedDict):
    messages: Annotated[list, add_messages]   # conversation (memory)
    question: str                             # the latest user question (for grading)
    search_query: str                         # current query for retrieval
    context: str                              # retrieved chunks for this turn
    sources: list                             # structured citations for the UI
    attempts: int                             # retrieval attempts so far
    grade: dict                               # latest grader verdict
    verdicts: list                            # every grader verdict this turn (for UI)


def _label(meta):
    """Human-readable citation label for a chunk's source."""
    name = meta.get("source_name", "Source")
    stype = meta.get("source_type")
    if stype in ("audio", "youtube"):
        return f"{name} @ {seconds_to_timestamp(meta.get('ts_start', 0))}"
    if stype == "pdf_figure":
        return f"{name} — Figure (p.{meta.get('page', '?')})"
    if "page" in meta:
        return f"{name} p.{meta['page']}"
    return name


def _parse_grade(raw):
    """Parse the grader's JSON. Fail OPEN (treat as relevant) on any parse error, so
    a flaky grader never blocks a legitimate answer."""
    try:
        obj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return {"relevant": bool(obj["relevant"]), "reason": str(obj.get("reason", ""))[:200]}
    except Exception:
        return {"relevant": True, "reason": "grader parse failed; defaulted to answering"}


# ── NODES ─────────────────────────────────────────────────────────────────────
def rewrite_query(state: State) -> dict:
    """Turn a possibly context-dependent question into a standalone search query.
    On the first turn there's nothing to resolve, so we skip the LLM call."""
    history = state["messages"]
    question = history[-1].content
    if len(history) == 1:
        search_query = question
    else:
        search_query = llm.invoke([SystemMessage(content=REWRITE_PROMPT)] + history).content.strip()
    return {"search_query": search_query, "question": question, "attempts": 1, "verdicts": []}


def retrieve(state: State) -> dict:
    """Fetch the top-K chunks and build both the LLM context and the UI sources."""
    docs = similarity_search(state["search_query"], k=TOP_K)
    blocks, sources, seen = [], [], set()
    for d in docs:
        m = d.metadata
        blocks.append(f"[{_label(m)}]\n{d.page_content}")
        key = (m.get("source_name"), m.get("ts_start"), m.get("page"))
        if key not in seen:
            seen.add(key)
            sources.append({
                "label": _label(m),
                "source_type": m.get("source_type"),
                "source_name": m.get("source_name"),
                "ts_start": m.get("ts_start"),
                "audio_path": m.get("audio_path"),
                "youtube_url": m.get("youtube_url"),
                "page": m.get("page"),
                "figure_image_path": m.get("figure_image_path"),
            })
    return {"context": "\n\n---\n\n".join(blocks), "sources": sources}


def grade(state: State) -> dict:
    """Judge whether the retrieved context actually answers the question."""
    context = state["context"]
    if not context.strip():
        verdict = {"relevant": False, "reason": "no context retrieved"}
    else:
        raw = llm.invoke([
            SystemMessage(content=GRADER_PROMPT),
            HumanMessage(content=f"Question: {state['question']}\n\nRetrieved context:\n{context}"),
        ]).content
        verdict = _parse_grade(raw)
    return {"grade": verdict, "verdicts": state.get("verdicts", []) + [{"attempt": state["attempts"], **verdict}]}


def rewrite_retry(state: State) -> dict:
    """Reformulate the query with different words and bump the attempt counter."""
    new_query = llm.invoke([
        SystemMessage(content=RETRY_PROMPT),
        HumanMessage(content=f"Original question: {state['question']}\n"
                             f"Previous query that failed: {state['search_query']}\nNew query:"),
    ]).content.strip()
    return {"search_query": new_query, "attempts": state["attempts"] + 1}


def generate(state: State) -> dict:
    """Answer from the retrieved context plus the conversation history."""
    system = f"{SYSTEM_PROMPT}\n\nContext from the course materials:\n{state['context']}"
    return {"messages": [llm.invoke([SystemMessage(content=system)] + state["messages"])]}


def no_answer(state: State) -> dict:
    """Refuse honestly, and tell the user what the library actually covers."""
    names = list_sources()
    listing = ", ".join(names) if names else "nothing yet"
    text = ("I couldn't find anything in your materials that answers that. "
            f"Your library currently covers: {listing}.")
    return {"messages": [AIMessage(content=text)], "sources": []}


def _route_after_grade(state: State) -> str:
    """relevant → answer; else retry until the attempt cap; then refuse."""
    if state["grade"]["relevant"]:
        return "generate"
    if state["attempts"] < MAX_RETRIEVAL_ATTEMPTS:
        return "rewrite_retry"
    return "no_answer"


# ── BUILD + COMPILE ─────────────────────────────────────────────────────────
def build_graph(enable_grader=ENABLE_GRADER):
    """Compile the graph. With the grader off, it's the V1 linear pass — this lets
    the V4 eval harness compare grader-on vs grader-off on identical inputs."""
    b = StateGraph(State)
    b.add_node("rewrite_query", rewrite_query)
    b.add_node("retrieve", retrieve)
    b.add_node("generate", generate)
    b.add_edge(START, "rewrite_query")
    b.add_edge("rewrite_query", "retrieve")
    b.add_edge("generate", END)

    if enable_grader:
        b.add_node("grade", grade)
        b.add_node("rewrite_retry", rewrite_retry)
        b.add_node("no_answer", no_answer)
        b.add_edge("retrieve", "grade")
        b.add_conditional_edges("grade", _route_after_grade,
                                {"generate": "generate",
                                 "rewrite_retry": "rewrite_retry",
                                 "no_answer": "no_answer"})
        b.add_edge("rewrite_retry", "retrieve")
        b.add_edge("no_answer", END)
    else:
        b.add_edge("retrieve", "generate")

    return b.compile(checkpointer=InMemorySaver())


graph = build_graph()


def _cited_sources(answer, sources):
    """Keep only sources the answer actually cites — retrieval returns the top-K
    nearest chunks with no relevance floor, so unrelated sources can ride along;
    we don't want to display those as citations. Match on the citation label or the
    source name appearing in the answer. Fall back to all sources if the model
    didn't cite recognizably (better some context than none)."""
    cited = [
        s for s in sources
        if (s.get("label") and s["label"] in answer)
        or (s.get("source_name") and s["source_name"] in answer)
    ]
    return cited or sources


def get_response(question, thread_id, graph_override=None):
    """Answer a question, remembering everything under this thread_id. Also measures
    wall-clock latency and total token usage across every LLM call in the turn
    (rewrite + grade + retries + generate).
    Returns {'answer', 'sources', 'verdicts', 'attempts', 'context', 'latency_s',
    'total_tokens'}."""
    g = graph_override or graph
    config = {"configurable": {"thread_id": thread_id}}
    t0 = time.perf_counter()
    with get_usage_metadata_callback() as cb:
        result = g.invoke({"messages": [HumanMessage(content=question)]}, config)
    latency = time.perf_counter() - t0
    total_tokens = sum(u.get("total_tokens", 0) for u in cb.usage_metadata.values())
    answer = result["messages"][-1].content
    return {
        "answer": answer,
        "sources": _cited_sources(answer, result.get("sources", [])),
        "verdicts": result.get("verdicts", []),
        "attempts": result.get("attempts", 1),
        "context": result.get("context", ""),
        "latency_s": latency,
        "total_tokens": total_tokens,
    }
