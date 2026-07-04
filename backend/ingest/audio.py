"""CourseLens — audio ingestion.

Pipeline: convert to 16 kHz mono FLAC → split if over Groq's size cap →
transcribe each piece with Groq Whisper (segment timestamps) → merge segments
into ~CHUNK_CHARS chunks that carry GLOBAL start/end timestamps.

The timestamp bookkeeping is the whole point: it's what lets citations deep-link
to the exact moment. We never re-split transcript text with a character splitter
— that would destroy the segment↔timestamp alignment.
"""
import os
import glob
import shutil
import hashlib
import subprocess
import tempfile

from backend.config import (
    AUDIO_DIR,
    CHUNK_CHARS,
    SEGMENT_SECONDS,
    WHISPER_MAX_BYTES,
    WHISPER_MODEL,
)

_groq_client = None


def _client():
    """Lazily build the Groq client (kept out of module import so the pure
    helpers below are importable without the SDK or an API key)."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq()   # reads GROQ_API_KEY from the environment
    return _groq_client


def _ffmpeg_exe():
    """Resolve an ffmpeg binary — prefer a system install, else the pip-bundled
    one from imageio-ffmpeg (so the app runs without a manual ffmpeg install)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError(
            "ffmpeg not found. Install it (`brew install ffmpeg`) or "
            "`pip install imageio-ffmpeg`."
        ) from e


def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _to_flac(src, workdir):
    """Convert any audio to 16 kHz mono FLAC (Groq-recommended, shrinks size)."""
    out = os.path.join(workdir, "audio.flac")
    _run([_ffmpeg_exe(), "-y", "-i", src, "-ar", "16000", "-ac", "1", "-c:a", "flac", out])
    return out


def _split_if_needed(flac, workdir):
    """Return [(path, offset_seconds)]. Split into SEGMENT_SECONDS windows only
    when the file exceeds the size cap; otherwise a single piece at offset 0."""
    if os.path.getsize(flac) <= WHISPER_MAX_BYTES:
        return [(flac, 0.0)]
    pattern = os.path.join(workdir, "seg_%03d.flac")
    _run([
        _ffmpeg_exe(), "-y", "-i", flac,
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
        "-ar", "16000", "-ac", "1", "-c:a", "flac", pattern,
    ])
    parts = sorted(glob.glob(os.path.join(workdir, "seg_*.flac")))
    # Fixed-window splits → the i-th part starts at i * SEGMENT_SECONDS.
    return [(p, i * SEGMENT_SECONDS) for i, p in enumerate(parts)]


def _seg(obj, key):
    """Read a field from a Whisper segment (dict or attribute style)."""
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def _transcribe_segment(path, offset):
    """Transcribe one file; return segments shifted to GLOBAL timestamps."""
    with open(path, "rb") as f:
        resp = _client().audio.transcriptions.create(
            file=(os.path.basename(path), f.read()),
            model=WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    segments = getattr(resp, "segments", None) or []
    return [
        {
            "start": float(_seg(s, "start")) + offset,
            "end": float(_seg(s, "end")) + offset,
            "text": _seg(s, "text"),
        }
        for s in segments
    ]


def merge_segments_into_chunks(segments, max_chars=CHUNK_CHARS):
    """Merge Whisper segments into ~max_chars chunks, preserving global
    start/end timestamps. Pure function — unit-tested offline."""
    chunks = []
    buf, cur_len, start, end = [], 0, None, None
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        if start is None:
            start = seg["start"]
        if buf and cur_len + len(text) + 1 > max_chars:
            chunks.append({"text": " ".join(buf).strip(), "ts_start": start, "ts_end": end})
            buf, cur_len, start = [], 0, seg["start"]
        buf.append(text)
        cur_len += len(text) + 1
        end = seg["end"]
    if buf:
        chunks.append({"text": " ".join(buf).strip(), "ts_start": start, "ts_end": end})
    return chunks


def transcribe_audio(audio_path):
    """Full audio file → timestamped transcript chunks (no metadata/storage)."""
    with tempfile.TemporaryDirectory() as workdir:
        flac = _to_flac(audio_path, workdir)
        pieces = _split_if_needed(flac, workdir)
        segments = []
        for path, offset in pieces:
            segments.extend(_transcribe_segment(path, offset))
    return merge_segments_into_chunks(segments)


def _persist_audio(src):
    """Copy uploaded audio into media_store (keyed by content hash) so st.audio
    playback survives Streamlit reruns. Returns the stored path."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    with open(src, "rb") as f:
        digest = hashlib.sha1(f.read()).hexdigest()[:16]
    ext = os.path.splitext(src)[1] or ".audio"
    dest = os.path.join(AUDIO_DIR, digest + ext)
    if not os.path.exists(dest):
        shutil.copyfile(src, dest)
    return dest


def build_audio_chunks(src_path, source_name):
    """Uploaded audio file → chunk dicts ready for the store."""
    stored = _persist_audio(src_path)
    return [
        {
            "text": c["text"],
            "metadata": {
                "source_name": source_name,
                "source_type": "audio",
                "ts_start": c["ts_start"],
                "ts_end": c["ts_end"],
                "audio_path": stored,
            },
        }
        for c in transcribe_audio(src_path)
    ]
