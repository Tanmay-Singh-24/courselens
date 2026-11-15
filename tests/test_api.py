"""HTTP API — routing, input validation and the media path guard.

Offline: every backend call that could reach Groq or depend on the local library
(the RAG graph, ingestion, the concept map, the vector store) is replaced with a
stub, so these tests check the HTTP layer alone.
"""
import os

import pytest
from fastapi.testclient import TestClient

import api.main as M


@pytest.fixture
def client(monkeypatch, tmp_path):
    media = tmp_path / "media_store"
    (media / "audio").mkdir(parents=True)
    (media / "audio" / "lec.mp3").write_bytes(b"ID3")
    (tmp_path / "secret.env").write_text("GROQ_API_KEY=nope")
    monkeypatch.setattr(M, "MEDIA_DIR", str(media))
    monkeypatch.setattr(M, "resolve_media_path",
                        lambda p: None if not p else os.path.join(str(media), p))
    monkeypatch.setattr(M, "has_documents", lambda: True)
    return TestClient(M.app)


def test_health_reports_build(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["build"] == M.BUILD


def test_frontend_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "CourseLens" in r.text


def test_media_serves_files_inside_media_store(client):
    assert client.get("/media/audio/lec.mp3").status_code == 200


@pytest.mark.parametrize("path", ["../secret.env", "audio/../../secret.env", "audio/missing.mp3"])
def test_media_blocks_traversal_and_missing(client, path):
    assert client.get(f"/media/{path}").status_code == 404


def test_media_url_only_for_existing_files(client):
    assert M.media_url("audio/lec.mp3") == "/media/audio/lec.mp3"
    assert M.media_url("audio/gone.mp3") is None
    assert M.media_url(None) is None


def test_ask_rejects_blank_question(client):
    assert client.post("/api/ask", json={"question": "   "}).status_code == 400


def test_ask_shapes_sources_for_the_browser(client, monkeypatch):
    def fake(question, thread_id):
        return {"answer": "O(E log V)", "verdicts": [{"relevant": True, "reason": "ok"}],
                "attempts": 1, "latency_s": 1.234, "total_tokens": 99,
                "sources": [{"label": "lec @ 1:07", "source_name": "lec",
                             "source_type": "audio", "ts_start": 67,
                             "audio_path": "audio/lec.mp3"}]}
    monkeypatch.setattr(M, "get_response", fake)
    body = client.post("/api/ask", json={"question": "dijkstra?", "thread_id": "t1"}).json()
    assert body["thread_id"] == "t1"
    assert body["latency_s"] == 1.23
    src = body["sources"][0]
    assert src["media_url"] == "/media/audio/lec.mp3"
    assert src["ts_start"] == 67
    assert "audio_path" not in src          # no server paths leak to the browser


def test_ask_turns_provider_errors_into_a_503_sentence(client, monkeypatch):
    class Busy(Exception):
        status_code = 503

    def boom(question, thread_id):
        raise Busy("upstream")
    monkeypatch.setattr(M, "get_response", boom)
    r = client.post("/api/ask", json={"question": "hi"})
    assert r.status_code == 503
    assert "busy" in r.json()["detail"]


def test_ingest_rejects_unsupported_type(client):
    r = client.post("/api/ingest", files={"file": ("notes.docx", b"x")})
    assert r.status_code == 415


def test_course_map_marks_cross_source_links_as_bridges(client, monkeypatch):
    nodes = [{"id": "Queues", "sources": ["ds"]}, {"id": "Priority queue", "sources": ["graphs"]},
             {"id": "Stacks", "sources": ["ds"]}, {"id": "BubbleSort", "sources": ["sorting"]}]
    cmap = {n["id"]: n["sources"] for n in nodes}
    monkeypatch.setattr(M, "build_concept_map", lambda: (nodes, [["Queues", "Stacks"]], cmap))
    monkeypatch.setattr(M, "_related", lambda labels: [
        ("Priority queue", "Queues", 0.71),   # cross-source, strong -> bridge
        ("Queues", "Stacks", 0.5),            # same source -> related
        ("BubbleSort", "Stacks", 0.31),       # cross-source, weak -> dropped
    ])
    body = client.get("/api/course-map").json()
    kinds = {(lk["source"], lk["target"]): lk["kind"] for lk in body["links"]}
    assert kinds[("Priority queue", "Queues")] == "bridge"
    assert kinds[("Queues", "Stacks")] in ("shared", "related")
    assert ("BubbleSort", "Stacks") not in kinds
    assert body["sources"] == ["ds", "graphs", "sorting"]


def test_course_map_empty_library(client, monkeypatch):
    monkeypatch.setattr(M, "has_documents", lambda: False)
    assert client.get("/api/course-map").json() == {"nodes": [], "links": [], "sources": []}


def test_frontend_files_revalidate_after_redeploys(client):
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
