"""Corrective-RAG graph logic — grader parsing, routing, citation filtering, labels."""
import backend.graph as G


# ── grader verdict parsing ───────────────────────────────────────────────────
def test_parse_grade_clean_json():
    v = G._parse_grade('{"relevant": true, "reason": "answers directly"}')
    assert v["relevant"] is True


def test_parse_grade_json_embedded_in_prose():
    v = G._parse_grade('Sure! {"relevant": false, "reason": "off topic"} hth')
    assert v["relevant"] is False


def test_parse_grade_garbage_fails_open():
    # A broken grader must degrade to answering, never to a false refusal.
    v = G._parse_grade("not json at all")
    assert v["relevant"] is True
    assert "parse failed" in v["reason"]


# ── routing after the grade ──────────────────────────────────────────────────
def route(relevant, attempts):
    return G._route_after_grade({"grade": {"relevant": relevant}, "attempts": attempts})


def test_relevant_goes_to_generate():
    assert route(True, 1) == "generate"


def test_miss_below_cap_retries():
    assert route(False, 1) == "rewrite_retry"


def test_miss_at_cap_refuses():
    assert route(False, G.MAX_RETRIEVAL_ATTEMPTS) == "no_answer"


# ── graph shape toggle (grader on/off ablation depends on this) ──────────────
def test_grader_toggle_reshapes_graph():
    on = set(G.build_graph(True).get_graph().nodes)
    off = set(G.build_graph(False).get_graph().nodes)
    assert {"grade", "rewrite_retry", "no_answer"} <= on
    assert not ({"grade", "rewrite_retry", "no_answer"} & off)


# ── citation filtering (only display sources the answer cites) ───────────────
SOURCES = [
    {"label": "zoo @ 0:00", "source_name": "zoo"},
    {"label": "LangGraph talk @ 4:44", "source_name": "LangGraph talk"},
]


def test_cited_sources_keeps_only_cited():
    kept = G._cited_sources("According to [zoo @ 0:00], it is an elephant.", SOURCES)
    assert [s["source_name"] for s in kept] == ["zoo"]


def test_cited_sources_falls_back_when_none_match():
    assert G._cited_sources("no recognizable citations", SOURCES) == SOURCES


# ── citation labels ──────────────────────────────────────────────────────────
def test_labels_per_modality():
    assert G._label({"source_name": "Lec", "source_type": "audio", "ts_start": 872}) == "Lec @ 14:32"
    assert G._label({"source_name": "S", "source_type": "pdf_figure", "page": 3}) == "S — Figure (p.3)"
    assert G._label({"source_name": "S", "source_type": "pdf_text", "page": 2}) == "S p.2"
    assert G._label({}) == "Source"
