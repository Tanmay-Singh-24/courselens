"""Small shared utilities."""
import os

from backend.config import MEDIA_DIR, media_relpath, resolve_media_path, seconds_to_timestamp
from backend.store import _clean_metadata


def test_timestamp_formatting():
    assert seconds_to_timestamp(0) == "0:00"
    assert seconds_to_timestamp(92) == "1:32"
    assert seconds_to_timestamp(3872) == "1:04:32"
    assert seconds_to_timestamp(None) == "0:00"


def test_clean_metadata_drops_none_keeps_falsy():
    cleaned = _clean_metadata({"a": 1, "b": None, "c": 0, "d": ""})
    assert cleaned == {"a": 1, "c": 0, "d": ""}   # Chroma rejects None; 0/"" are valid


# ── media-path portability ───────────────────────────────────────────────────
def test_media_relpath_roundtrips_through_resolve():
    stored = media_relpath(os.path.join(MEDIA_DIR, "audio", "abc.mp3"))
    assert stored == os.path.join("audio", "abc.mp3")          # no machine prefix
    assert resolve_media_path(stored) == os.path.join(MEDIA_DIR, "audio", "abc.mp3")


def test_resolve_media_path_reroots_legacy_absolute_paths():
    # Metadata written on another machine holds that machine's absolute path;
    # it must resolve to THIS machine's media_store.
    legacy = "/Users/someone-else/code/CourseLens/media_store/figures/f.png"
    assert resolve_media_path(legacy) == os.path.join(MEDIA_DIR, "figures", "f.png")


def test_resolve_media_path_empty_is_none():
    assert resolve_media_path(None) is None
    assert resolve_media_path("") is None
