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
import time

from backend.config import (
    AUDIO_DIR,
    CHUNK_CHARS,
    SEGMENT_SECONDS,
    WHISPER_MAX_BYTES,
    WHISPER_MAX_RETRIES,
    WHISPER_MODEL,
    WHISPER_TIMEOUT_S,
    media_relpath,
)

_groq_client = None


def _client():
    """Lazily build the Groq client (kept out of module import so the pure
    helpers below are importable without the SDK or an API key)."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        # Reads GROQ_API_KEY from the environment. Long timeout: transcription
        # uploads are large and server processing scales with audio length.
        _groq_client = Groq(timeout=WHISPER_TIMEOUT_S, max_retries=WHISPER_MAX_RETRIES)
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


def _split(flac, workdir):
    """Split into SEGMENT_SECONDS windows and return [(path, offset_seconds)].

    Always segmenting (a short file just yields one segment) keeps every upload
    small and fast, and isolates failures to one window instead of the whole
    lecture — Groq's transcription endpoint was observed to 502 on a single
    15-minute request that succeeds fine as 10-minute pieces. Segments also stay
    far below WHISPER_MAX_BYTES (~10 min of 16 kHz mono FLAC ≈ 7 MB)."""
    pattern = os.path.join(workdir, "seg_%03d.flac")
    _run([
        _ffmpeg_exe(), "-y", "-i", flac,
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
        "-ar", "16000", "-ac", "1", "-c:a", "flac", pattern,
    ])
    parts = sorted(glob.glob(os.path.join(workdir, "seg_*.flac")))
    if not parts:
        raise RuntimeError("ffmpeg produced no audio segments.")
    oversize = [p for p in parts if os.path.getsize(p) > WHISPER_MAX_BYTES]
    if oversize:
        raise RuntimeError(
            f"{len(oversize)} audio segment(s) exceed the {WHISPER_MAX_BYTES // 2**20} MB "
            "upload cap — lower SEGMENT_SECONDS in backend/config.py."
        )
    # Fixed-window splits → the i-th part starts at i * SEGMENT_SECONDS.
    return [(p, i * SEGMENT_SECONDS) for i, p in enumerate(parts)]


def _seg(obj, key):
    """Read a field from a Whisper segment (dict or attribute style)."""
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def _transcribe_segment(path, offset, retries=3):
    """Transcribe one file; return segments shifted to GLOBAL timestamps.
    The SDK retries transient failures per request already; this outer loop adds
    longer-horizon retries with a pause (Groq's Whisper endpoint occasionally
    returns 502 under load) so one blip doesn't lose the whole lecture."""
    import groq
    with open(path, "rb") as f:
        payload = f.read()
    for attempt in range(retries):
        try:
            resp = _client().audio.transcriptions.create(
                file=(os.path.basename(path), payload),
                model=WHISPER_MODEL,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
            break
        except (groq.InternalServerError, groq.APIConnectionError) as e:
            if attempt == retries - 1:
                raise
            print(f"transcription retry {attempt + 1}/{retries - 1} after {type(e).__name__}")
            # Groq 502s arrive in waves lasting minutes (observed on real
            # lectures) — short pauses don't outlive them.
            time.sleep(30 * (attempt + 1))   # 30s, 60s
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
        pieces = _split(flac, workdir)
        segments = []
        for path, offset in pieces:
            segments.extend(_transcribe_segment(path, offset))
    return merge_segments_into_chunks(segments)


def _persist_audio(src):
    """Copy uploaded audio into media_store (keyed by content hash) so st.audio
    playback survives Streamlit reruns. Returns the stored path relative to
    media_store/ — that's what goes into chunk metadata, so citations keep
    working after the project moves machines."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    digest = hashlib.sha1()
    with open(src, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    ext = os.path.splitext(src)[1] or ".audio"
    dest = os.path.join(AUDIO_DIR, digest.hexdigest()[:16] + ext)
    if not os.path.exists(dest):
        shutil.copyfile(src, dest)
    return media_relpath(dest)


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
