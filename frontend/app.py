"""CourseLens — Streamlit UI (V1).

Thin presentation layer: ingest lecture audio (and, locally, YouTube URLs) and
chat with actionable, deep-linked citations. All logic lives in backend/.

Run from the project root:
    streamlit run frontend/app.py
"""
import os
import sys
import uuid
import tempfile

import streamlit as st
from dotenv import load_dotenv

# Project root on the import path so `from backend... import ...` works from
# wherever streamlit is launched.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

# Resolve the Groq key before importing the backend (it builds the LLM/Groq
# clients at import time). Prefer Streamlit Cloud secrets; fall back to a .env.
load_dotenv(os.path.join(PROJECT_DIR, ".env"))
try:
    # Bridge every string secret into the environment: GROQ_API_KEY, and e.g.
    # ENABLE_YOUTUBE=0 to disable YouTube ingestion on hosted deploys.
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ[_k] = _v
except Exception:
    pass
if not os.environ.get("GROQ_API_KEY"):
    st.error(
        "GROQ_API_KEY is not set. On Streamlit Cloud add it under "
        "**Settings → Secrets**; for local dev put it in a `.env` file."
    )
    st.stop()

from backend.config import ENABLE_YOUTUBE            # noqa: E402
from backend.ingest.dispatch import ingest_file, ingest_youtube  # noqa: E402
from backend.store import has_documents             # noqa: E402
from backend import telemetry                        # noqa: E402

st.set_page_config(page_title="CourseLens", page_icon="🎓")
st.title("🎓 CourseLens")
st.caption(
    "Ingest your course — lectures, slides, and figures — and ask questions with "
    "answers that link back to the exact moment or figure."
)

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "ingested" not in st.session_state:
    st.session_state.ingested = []


def render_sources(sources):
    """Render actionable citations: audio players seeked to the moment, YouTube
    deep links, or the cited figure shown inline."""
    if not sources:
        return
    with st.expander("Sources"):
        for s in sources:
            stype = s.get("source_type")
            # Media paths live on ephemeral disk and can outlive a restart in the
            # stored metadata — always check the file still exists before rendering.
            if stype == "audio" and s.get("audio_path") and os.path.exists(s["audio_path"]):
                st.markdown(f"**▶ {s['label']}**")
                st.audio(s["audio_path"], start_time=int(s.get("ts_start") or 0))
            elif stype == "youtube" and s.get("youtube_url"):
                t = int(s.get("ts_start") or 0)
                st.markdown(f"- [{s['label']}]({s['youtube_url']}&t={t}s)")
            elif stype == "pdf_figure" and s.get("figure_image_path") \
                    and os.path.exists(s["figure_image_path"]):
                st.markdown(f"**🖼 {s['label']}**")
                st.image(s["figure_image_path"])
            else:
                st.markdown(f"- {s['label']} *(media unavailable — re-ingest to restore playback)*")


def render_verdicts(verdicts):
    """Show the corrective-RAG grader's relevance judgement(s) for this turn."""
    if not verdicts:
        return
    with st.expander("Retrieval check (corrective RAG)"):
        for v in verdicts:
            mark = "✅ relevant" if v.get("relevant") else "❌ not relevant"
            st.markdown(f"- Attempt {v.get('attempt')}: {mark} — {v.get('reason', '')}")


def render_stats(stats):
    """Small per-query telemetry line: latency, tokens, retrieval attempts."""
    if not stats:
        return
    st.caption(
        f"⚙️ {stats['latency_s']:.1f}s · {stats['total_tokens']} tokens · "
        f"{stats['attempts']} retrieval attempt(s)"
    )


_PALETTE = ["#4C78A8", "#54A24B", "#E45756", "#B279A2", "#F58518", "#72B7B2", "#EECA3B"]


def render_course_map():
    """Concept graph over the ingested library. Nodes are concepts (colored by
    source); edges link concepts from the same source. Clicking / selecting a
    concept shows where it appears (free local retrieval — no LLM)."""
    st.subheader("🗺️ Course Map")
    st.caption("Key concepts across your course — related concepts (same source) are linked.")
    if not has_documents():
        st.info("Add course material first — the map is built from what you've ingested.")
        return

    from streamlit_agraph import agraph, Node, Edge, Config
    from backend.concept_map import build_concept_map
    from backend.store import similarity_search

    with st.spinner("Building concept map…"):
        nodes_data, edges_data, concept_sources = build_concept_map()
    if not nodes_data:
        st.info("Couldn't extract concepts from the current library yet.")
        return

    srcs = sorted({s for n in nodes_data for s in n["sources"]})
    color = {s: _PALETTE[i % len(_PALETTE)] for i, s in enumerate(srcs)}
    nodes = [Node(id=n["id"], label=n["label"], size=18,
                  color=color.get(n["sources"][0], "#888888")) for n in nodes_data]
    edges = [Edge(source=a, target=b) for a, b in edges_data]
    cfg = Config(width=700, height=500, directed=False, physics=True,
                 nodeHighlightBehavior=True, highlightColor="#F7A600")
    clicked = agraph(nodes=nodes, edges=edges, config=cfg)

    st.caption("Sources: " + " · ".join(srcs))

    ids = [n["id"] for n in nodes_data]
    concept = clicked if clicked in ids else st.selectbox("Explore a concept", ids)
    if concept:
        st.markdown(f"**{concept}** — appears in: {', '.join(concept_sources.get(concept, []))}")
        st.markdown("_Where it shows up:_")
        for d in similarity_search(concept, k=3):
            m = d.metadata
            st.markdown(f"- *{m.get('source_name', '?')}*: {d.page_content[:160].strip()}…")


# ── SIDEBAR: ingest + library ────────────────────────────────────────────────
with st.sidebar:
    view = st.radio("View", ["💬 Chat", "🗺️ Course Map"], horizontal=True)
    st.header("Your course")

    uploaded = st.file_uploader(
        "Add lecture audio or slides (PDF)",
        type=["mp3", "m4a", "wav", "flac", "mp4", "pdf"],
        accept_multiple_files=True,
    )
    for up in uploaded or []:
        if up.name in st.session_state.ingested:
            continue
        with st.spinner(f"Transcribing {up.name}… (this can take a minute)"):
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=os.path.splitext(up.name)[1]
            ) as tmp:
                tmp.write(up.getvalue())
                tmp_path = tmp.name
            try:
                n = ingest_file(tmp_path, up.name)
                st.session_state.ingested.append(up.name)
                st.success(f"Added {up.name} ({n} chunks)")
            except Exception as e:
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    st.warning(f"⚠️ {up.name}: Groq's free daily token limit is "
                               "reached — try again after it resets.")
                else:
                    st.error(f"Failed on {up.name}: {e}")
            finally:
                os.unlink(tmp_path)

    if ENABLE_YOUTUBE:
        st.divider()
        yt_url = st.text_input("…or a YouTube lecture URL")
        if st.button("Add YouTube video") and yt_url:
            with st.spinner("Downloading + transcribing… (local only)"):
                try:
                    n = ingest_youtube(yt_url)
                    st.session_state.ingested.append(yt_url)
                    st.success(f"Added video ({n} chunks)")
                except Exception as e:
                    st.error(f"YouTube ingest failed: {e}")

    st.divider()
    if st.session_state.ingested:
        st.subheader("Library")
        for name in st.session_state.ingested:
            st.markdown(f"- {name}")
    else:
        st.info(
            "Add a lecture (audio file or YouTube URL) to begin, then ask "
            "questions in the chat."
        )

    if st.button("Clear chat"):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()


# ── COURSE MAP view short-circuits the chat below ─────────────────────────────
if view == "🗺️ Course Map":
    render_course_map()
    st.stop()


# ── CHAT TRANSCRIPT ───────────────────────────────────────────────────────────
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            render_sources(m.get("sources"))
            render_verdicts(m.get("verdicts"))
            render_stats(m.get("stats"))


# ── INPUT + RESPONSE ──────────────────────────────────────────────────────────
if question := st.chat_input("Ask about your course…"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        if not has_documents():
            answer, sources, verdicts, stats = (
                "Your library is empty. Add a lecture in the sidebar to get "
                "started, then ask away.",
                [], [], None,
            )
            st.markdown(answer)
        else:
            from backend.graph import get_response
            try:
                with st.spinner("Searching your course…"):
                    result = get_response(question, thread_id=st.session_state.thread_id)
                answer, sources, verdicts = result["answer"], result["sources"], result["verdicts"]
                stats = {"latency_s": result["latency_s"],
                         "total_tokens": result["total_tokens"],
                         "attempts": result["attempts"]}
                st.markdown(answer)
                render_sources(sources)
                render_verdicts(verdicts)
                render_stats(stats)
                telemetry.log_query(question, result["latency_s"], result["total_tokens"],
                                    result["attempts"], len(sources))
            except Exception as e:
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    answer = ("⚠️ Groq's free-tier daily token limit has been reached — "
                              "please try again later. (This live demo runs on a single "
                              "free API key.)")
                else:
                    answer = f"⚠️ Something went wrong answering that: {str(e)[:200]}"
                sources, verdicts, stats = [], [], None
                st.warning(answer)

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "sources": sources,
         "verdicts": verdicts, "stats": stats}
    )
