"""Transcript chunking — the timestamp bookkeeping that powers deep-linked citations."""
from backend.ingest.audio import merge_segments_into_chunks


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_single_chunk_keeps_full_span():
    chunks = merge_segments_into_chunks([seg(0, 5, "hello"), seg(5, 9, "world")], max_chars=100)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "hello world"
    assert chunks[0]["ts_start"] == 0 and chunks[0]["ts_end"] == 9


def test_splits_on_char_budget_and_preserves_timestamps():
    # Each 60-char segment overflows the 100-char budget when paired → one chunk per segment.
    segments = [seg(0, 10, "a" * 60), seg(10, 20, "b" * 60), seg(20, 30, "c" * 60)]
    chunks = merge_segments_into_chunks(segments, max_chars=100)
    assert [(c["ts_start"], c["ts_end"]) for c in chunks] == [(0, 10), (10, 20), (20, 30)]


def test_two_small_segments_share_a_chunk_then_split():
    segments = [seg(0, 5, "x" * 40), seg(5, 9, "y" * 40), seg(9, 14, "z" * 40)]
    chunks = merge_segments_into_chunks(segments, max_chars=100)
    # 40+1+40=81 fits; adding the third (122) overflows → [x+y], [z]
    assert len(chunks) == 2
    assert chunks[0]["ts_start"] == 0 and chunks[0]["ts_end"] == 9
    assert chunks[1]["ts_start"] == 9 and chunks[1]["ts_end"] == 14


def test_skips_empty_segments():
    chunks = merge_segments_into_chunks([seg(0, 1, "  "), seg(1, 2, "real")], max_chars=100)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "real"
    assert chunks[0]["ts_start"] == 1  # empty segment must not anchor the timestamp


def test_empty_input():
    assert merge_segments_into_chunks([], max_chars=100) == []
