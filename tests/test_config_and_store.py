"""Small shared utilities."""
from backend.config import seconds_to_timestamp
from backend.store import _clean_metadata


def test_timestamp_formatting():
    assert seconds_to_timestamp(0) == "0:00"
    assert seconds_to_timestamp(92) == "1:32"
    assert seconds_to_timestamp(3872) == "1:04:32"
    assert seconds_to_timestamp(None) == "0:00"


def test_clean_metadata_drops_none_keeps_falsy():
    cleaned = _clean_metadata({"a": 1, "b": None, "c": 0, "d": ""})
    assert cleaned == {"a": 1, "c": 0, "d": ""}   # Chroma rejects None; 0/"" are valid
