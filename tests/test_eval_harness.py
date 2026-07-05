"""Eval-harness scoring logic — the metrics must be right or the numbers lie."""
import backend.evals.run_evals as E


# ── retrieval hit scoring ────────────────────────────────────────────────────
AUDIO_GOLD = {"expected_source_name": "lec", "expected_source_type": "audio",
              "expected_ts_range": [38, 57]}


def test_audio_hit_on_overlap():
    metas = [{"source_name": "lec", "source_type": "audio", "ts_start": 40, "ts_end": 55}]
    assert E._retrieval_hit(metas, AUDIO_GOLD)


def test_audio_hit_within_tolerance():
    # ±60s tolerance: a chunk starting 50s after the range still counts.
    metas = [{"source_name": "lec", "source_type": "audio", "ts_start": 100, "ts_end": 110}]
    assert E._retrieval_hit(metas, AUDIO_GOLD)


def test_audio_miss_far_away():
    metas = [{"source_name": "lec", "source_type": "audio", "ts_start": 300, "ts_end": 310}]
    assert not E._retrieval_hit(metas, AUDIO_GOLD)


def test_wrong_source_misses():
    metas = [{"source_name": "other", "source_type": "audio", "ts_start": 40, "ts_end": 55}]
    assert not E._retrieval_hit(metas, AUDIO_GOLD)


PAGE_GOLD = {"expected_source_name": "sl", "expected_source_type": "pdf_text",
             "expected_page": 1}


def test_page_hit_with_tolerance():
    assert E._retrieval_hit([{"source_name": "sl", "source_type": "pdf_text", "page": 2}], PAGE_GOLD)


def test_wrong_stream_misses():
    # A figure chunk must not satisfy a pdf_text expectation.
    assert not E._retrieval_hit([{"source_name": "sl", "source_type": "pdf_figure", "page": 1}], PAGE_GOLD)


# ── answer scoring ───────────────────────────────────────────────────────────
def test_keyword_hit_any_match_case_insensitive():
    assert E._keyword_hit("Runs in O(E log V) time", ["log v"])
    assert not E._keyword_hit("nothing relevant", ["prim"])


def test_refusal_detection():
    assert E._is_refusal("I couldn't find anything in your materials that answers that.")
    assert not E._is_refusal("The answer is 42.")


def test_groundedness_parse_is_conservative():
    assert E._parse_groundedness('{"grounded": true, "reason": "ok"}') is True
    assert E._parse_groundedness("garbage") is False   # unparseable → NOT grounded


# ── aggregation ──────────────────────────────────────────────────────────────
ROWS = [
    {"id": "A1", "modality": "audio", "hit": True, "kw": True, "grounded": True},
    {"id": "C1", "modality": "pdf_text", "hit": True, "kw": False, "grounded": True},
    {"id": "C4", "modality": "pdf_figure", "hit": False, "kw": True, "grounded": False},
    {"id": "OOC1", "refusal_case": True, "refusal": True},
]


def test_summarize_overall_and_per_modality():
    s = E._summarize(ROWS)
    assert s["n"] == 3
    assert round(s["hit_rate"]) == 67
    assert s["refusal_acc"] == 100.0
    assert set(s["per_modality"]) == {"audio", "pdf_text", "pdf_figure"}


def test_markdown_report_contains_ablation():
    s = E._summarize(ROWS)
    md = E._markdown({"grader ON": s, "grader OFF": s})
    assert "Retrieval hit-rate@5" in md
    assert "Ablation" in md and "Per-modality" in md
