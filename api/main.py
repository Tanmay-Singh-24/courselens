"""CourseLens — HTTP API and web frontend.

One process: JSON endpoints under /api, ingested media under /media, and the static
frontend in web/ at /. The RAG pipeline itself lives in backend/ and is unchanged;
this file only translates between HTTP and those functions.

Run:  uvicorn api.main:app --port 8000
"""
import os
import tempfile
import uuid
from collections import defaultdict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.concept_map import build_concept_map, relate_concepts
from backend.config import BUILD, ENABLE_YOUTUBE, MEDIA_DIR, PROJECT_DIR, resolve_media_path
from backend.errors import friendly_message
from backend.graph import _label, get_response
from backend.ingest.dispatch import AUDIO_EXTS, ingest_file, ingest_youtube
from backend.store import embeddings, has_documents, similarity_search, vectorstore

WEB_DIR = os.path.join(PROJECT_DIR, "web")
UPLOAD_EXTS = AUDIO_EXTS | {".pdf"}

app = FastAPI(title="CourseLens", version=BUILD)


class AskRequest(BaseModel):
    question: str
    thread_id: str | None = None


class YoutubeRequest(BaseModel):
    url: str


# ── helpers ──────────────────────────────────────────────────────────────────
def media_url(stored):
    """Browser URL for a stored media path, or None if the file is gone. Metadata may
    hold a relative path (current) or another machine's absolute path (legacy)."""
    path = resolve_media_path(stored)
    if not path or not os.path.isfile(path):
        return None
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(MEDIA_DIR))
    if rel.startswith(".."):
        return None
    return "/media/" + rel.replace(os.sep, "/")


def source_json(s):
    """One citation, shaped for the frontend: what it is and how to open it."""
    return {
        "label": s.get("label"),
        "source_name": s.get("source_name"),
        "source_type": s.get("source_type"),
        "ts_start": s.get("ts_start"),
        "page": s.get("page"),
        "youtube_url": s.get("youtube_url"),
        "media_url": media_url(s.get("audio_path") or s.get("figure_image_path")),
    }


# ── library ──────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "build": BUILD, "has_documents": has_documents(),
            "youtube": ENABLE_YOUTUBE}


@app.get("/api/library")
def library():
    data = vectorstore.get(include=["metadatas"])
    by = defaultdict(lambda: {"types": set(), "chunks": 0})
    for m in data.get("metadatas", []):
        if m and m.get("source_name"):
            entry = by[m["source_name"]]
            entry["chunks"] += 1
            entry["types"].add(m.get("source_type"))
    return {"sources": [
        {"name": name, "chunks": e["chunks"], "types": sorted(t for t in e["types"] if t)}
        for name, e in sorted(by.items())
    ]}


# ── ask ──────────────────────────────────────────────────────────────────────
@app.post("/api/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Ask a question first.")
    thread_id = req.thread_id or str(uuid.uuid4())
    if not has_documents():
        return {"answer": "Your library is empty. Add a lecture or slide deck first.",
                "sources": [], "verdicts": [], "attempts": 0, "latency_s": 0,
                "total_tokens": 0, "thread_id": thread_id}
    try:
        r = get_response(question, thread_id=thread_id)
    except Exception as e:
        raise HTTPException(503, friendly_message(e))
    return {
        "answer": r["answer"],
        "sources": [source_json(s) for s in r["sources"]],
        "verdicts": r["verdicts"],
        "attempts": r["attempts"],
        "latency_s": round(r["latency_s"], 2),
        "total_tokens": r["total_tokens"],
        "thread_id": thread_id,
    }


# ── ingestion ────────────────────────────────────────────────────────────────
@app.post("/api/ingest")
def ingest(file: UploadFile = File(...)):
    name = file.filename or "upload"
    ext = os.path.splitext(name)[1].lower()
    if ext not in UPLOAD_EXTS:
        raise HTTPException(415, f"{name}: unsupported file type. Use audio or a PDF.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name
    warnings = []
    try:
        n = ingest_file(tmp_path, name, warnings)
    except Exception as e:
        raise HTTPException(502, friendly_message(e, name))
    finally:
        os.unlink(tmp_path)
    return {"name": name, "chunks": n or 0, "duplicate": n is None, "warnings": warnings}


@app.post("/api/ingest/youtube")
def ingest_yt(req: YoutubeRequest):
    if not ENABLE_YOUTUBE:
        raise HTTPException(400, "YouTube import is turned off on this server.")
    try:
        n = ingest_youtube(req.url.strip())
    except Exception as e:
        raise HTTPException(502, friendly_message(e, "YouTube video"))
    return {"name": req.url, "chunks": n or 0, "duplicate": n is None, "warnings": []}


# ── course map ───────────────────────────────────────────────────────────────
_related_memo = {}
# A bridge claims "these two lectures connect here" and is drawn boldest, so it must
# clear a higher bar than a same-source link. Measured on the demo library: cross-
# source pairs below ~0.38 were noise (BubbleSort/Stacks, Hash Tables/In-Place
# Sorting); above it they were real (Priority queue/Queues, BSTs/Kruskal's).
BRIDGE_MIN = 0.38


def _related(labels):
    """Similarity links between concept labels. Uses the local embedding model, so it
    costs no API tokens; memoised because the label set rarely changes."""
    key = tuple(labels)
    if key not in _related_memo:
        _related_memo.clear()
        vectors = embeddings.embed_documents(list(labels)) if labels else []
        _related_memo[key] = relate_concepts(list(labels), vectors)
    return _related_memo[key]


@app.get("/api/course-map")
def course_map():
    if not has_documents():
        return {"nodes": [], "links": [], "sources": []}
    try:
        nodes, edges, cmap = build_concept_map()
    except Exception as e:
        raise HTTPException(503, friendly_message(e, "Course Map"))

    links = [{"source": a, "target": b, "kind": "shared", "weight": 1.0} for a, b in edges]
    for a, b, sim in _related(sorted(n["id"] for n in nodes)):
        cross = not (set(cmap[a]) & set(cmap[b]))
        if cross and sim < BRIDGE_MIN:
            continue
        links.append({"source": a, "target": b, "kind": "bridge" if cross else "related",
                      "weight": sim})
    sources = sorted({s for n in nodes for s in n["sources"]})
    return {"nodes": [{"id": n["id"], "sources": n["sources"]} for n in nodes],
            "links": links, "sources": sources}


@app.get("/api/concept")
def concept(name: str):
    """Where a concept shows up: nearest passages by local retrieval (no LLM call)."""
    passages = []
    for d in similarity_search(name, k=4):
        m = d.metadata
        passages.append({**source_json({**m, "label": _label(m)}),
                         "text": d.page_content[:320].strip()})
    return {"name": name, "passages": passages}


# ── media + frontend ─────────────────────────────────────────────────────────
@app.get("/media/{path:path}")
def media(path: str):
    root = os.path.realpath(MEDIA_DIR)
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise HTTPException(404, "Not found")
    return FileResponse(full)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
