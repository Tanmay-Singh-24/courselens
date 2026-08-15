"""CourseLens — Streamlit UI.

Thin presentation layer: ingest lecture audio, slide PDFs (and, locally,
YouTube URLs), chat with actionable deep-linked citations, and explore the
Course Map. All logic lives in backend/.

Run from the project root:
    streamlit run frontend/app.py
"""
import logging
import os
import sys
import traceback
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

import groq                                          # noqa: E402
from backend.config import ENABLE_YOUTUBE, resolve_media_path  # noqa: E402
from backend.ingest.dispatch import ingest_file, ingest_youtube  # noqa: E402
from backend.store import has_documents, list_sources  # noqa: E402
from backend import telemetry                        # noqa: E402


def is_rate_limit(e):
    """True if an exception looks like a Groq free-tier rate limit."""
    return getattr(e, "status_code", None) == 429 or "rate_limit" in str(e).lower()


def friendly_error(e, subject=None):
    """Turn a provider exception into something a first-time visitor can act on.

    Raw tracebacks and status dumps ("Error code: 503 - … over capacity") are
    never shown: by the time one surfaces we've already retried with backoff, so
    the only useful message is what the user should do next. The full traceback
    still goes to the server log (Streamlit Cloud → Manage app), so a friendly UI
    doesn't mean flying blind.
    """
    logging.exception("ingest/answer failed%s", f" [{subject}]" if subject else "")
    what = f"**{subject}**: " if subject else ""
    status = getattr(e, "status_code", None)
    if is_rate_limit(e):
        return (f"{what}Groq's free-tier limit is reached — this live demo runs on a "
                "single free API key. Please try again in a minute.")
    if status in (408, 500, 502, 503, 529) or isinstance(
            e, (groq.APIConnectionError, groq.APITimeoutError)):
        return (f"{what}The model provider is busy right now. We retried a few times "
                "automatically — please try again in a minute.")
    if status in (401, 403):
        return f"{what}The server's API key was rejected. (Configuration issue, not your upload.)"
    # Unrecognized failure: name the exception type and the code location that
    # raised it. One line of provenance ("TypeError at pdf.py:147") makes a user
    # report actionable without dumping a traceback at them.
    where = ""
    tb = traceback.extract_tb(e.__traceback__)
    if tb:
        frame = tb[-1]
        where = f" at {os.path.basename(frame.filename)}:{frame.lineno}"
    return (f"{what}Something went wrong ({type(e).__name__}{where}). Please try again — "
            "if it persists, the file may be unsupported.")

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
# Files that failed ingestion this session. Without this, a failing file is
# retried on EVERY rerun (each chat message!) because it stays in the uploader
# widget — and transcription retries sleep 30-60s, freezing the UI each time.
if "failed" not in st.session_state:
    st.session_state.failed = set()


def render_sources(sources):
    """Render actionable citations: audio players seeked to the moment, YouTube
    deep links, or the cited figure shown inline."""
    if not sources:
        return
    with st.expander("Sources"):
        for s in sources:
            stype = s.get("source_type")
            # Media paths are stored relative to media_store/ (legacy rows may be
            # absolute) and the disk is ephemeral on cloud deploys — resolve, then
            # check the file still exists before rendering a player.
            if stype == "audio":
                path = resolve_media_path(s.get("audio_path"))
                if path and os.path.exists(path):
                    st.markdown(f"**▶ {s['label']}**")
                    st.audio(path, start_time=int(s.get("ts_start") or 0))
                else:
                    st.markdown(f"- {s['label']} *(audio unavailable — re-ingest to restore playback)*")
            elif stype == "youtube" and s.get("youtube_url"):
                t = int(s.get("ts_start") or 0)
                st.markdown(f"- [{s['label']}]({s['youtube_url']}&t={t}s)")
            elif stype == "pdf_figure":
                path = resolve_media_path(s.get("figure_image_path"))
                if path and os.path.exists(path):
                    st.markdown(f"**🖼 {s['label']}**")
                    st.image(path)
                else:
                    st.markdown(f"- {s['label']} *(figure unavailable — re-ingest to restore it)*")
            else:
                # slide text (and anything unrecognized): a plain page citation
                st.markdown(f"- 📄 {s['label']}")


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

    try:
        with st.spinner("Building concept map…"):
            nodes_data, edges_data, concept_sources = build_concept_map()
    except Exception as e:
        # Concept extraction is an LLM call — a provider blip must not traceback.
        st.warning(f"⚠️ {friendly_error(e, 'Course Map')}")
        return
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
        type=["mp3", "m4a", "wav", "flac", "aac", "ogg", "opus", "mp4", "pdf"],
        accept_multiple_files=True,
    )
    for up in uploaded or []:
        if up.name in st.session_state.ingested or up.name in st.session_state.failed:
            continue
        with st.spinner(f"Transcribing {up.name}… (this can take a minute)"):
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=os.path.splitext(up.name)[1]
            ) as tmp:
                tmp.write(up.getvalue())
                tmp_path = tmp.name
            try:
                warnings = []
                n = ingest_file(tmp_path, up.name, warnings)
                st.session_state.ingested.append(up.name)
                if n is None:
                    st.info(f"{up.name} is already in your library — skipped.")
                elif n == 0:
                    st.warning(f"Nothing extractable found in {up.name}.")
                else:
                    st.success(f"Added {up.name} ({n} chunks)")
                for w in warnings:      # partial success, e.g. figures skipped
                    st.info(f"ℹ️ {w}")
            except Exception as e:
                st.session_state.failed.add(up.name)
                st.warning(f"⚠️ {friendly_error(e, up.name)}")
            finally:
                os.unlink(tmp_path)

    if st.session_state.failed:
        st.warning("Failed to ingest: " + ", ".join(sorted(st.session_state.failed)))
        if st.button("Retry failed files"):
            st.session_state.failed.clear()
            st.rerun()

    if ENABLE_YOUTUBE:
        st.divider()
        yt_url = st.text_input("…or a YouTube lecture URL")
        if st.button("Add YouTube video") and yt_url:
            with st.spinner("Downloading + transcribing… (local only)"):
                try:
                    n = ingest_youtube(yt_url)
                    st.session_state.ingested.append(yt_url)
                    if n is None:
                        st.info("That video is already in your library — skipped.")
                    else:
                        st.success(f"Added video ({n} chunks)")
                except Exception as e:
                    st.warning(f"⚠️ {friendly_error(e, 'YouTube video')}")

    st.divider()
    # Read the library from the store, not session state — the vector store
    # persists across page refreshes and sessions, so returning users see what
    # their library actually contains.
    library = list_sources()
    if library:
        st.subheader("Library")
        for name in library:
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
# First-touch: the app ships with a demo course already indexed, so a visitor can
# ask a real question immediately instead of waiting on an upload. Starter
# questions make the capabilities obvious (timestamped audio, figure lookup,
# honest refusal) without them having to guess what to try.
if not st.session_state.messages:
    st.markdown("#### Try it now — a sample course is already loaded")
    st.caption(
        "Two CS lectures and two slide decks. Ask one of these, or upload your own "
        "material in the sidebar."
    )
    starters = [
        ("What is the time complexity of Dijkstra's algorithm?", "audio + timestamp"),
        ("Which sorting algorithm is slowest according to the chart?", "reads a figure"),
        ("How are hash table collisions handled?", "cross-lecture"),
        ("What is the capital of France?", "honest refusal"),
    ]
    cols = st.columns(2)
    for i, (q, tag) in enumerate(starters):
        if cols[i % 2].button(q, key=f"starter{i}", use_container_width=True):
            st.session_state.pending = q
            st.rerun()
        cols[i % 2].caption(f"↳ {tag}")

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            render_sources(m.get("sources"))
            render_verdicts(m.get("verdicts"))
            render_stats(m.get("stats"))


# ── INPUT + RESPONSE ──────────────────────────────────────────────────────────
# A starter button sets `pending`, which is consumed here so it flows through the
# exact same path as a typed question.
question = st.session_state.pop("pending", None) or st.chat_input("Ask about your course…")
if question:
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
                answer = f"⚠️ {friendly_error(e)}"
                sources, verdicts, stats = [], [], None
                st.warning(answer)

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "sources": sources,
         "verdicts": verdicts, "stats": stats}
    )
