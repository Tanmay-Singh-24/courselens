"""CourseLens — ingestion dispatch.

Plain file-type routing (NOT an agent — just extension matching) that sends each
input to the right ingestor, then stores the resulting chunks.
"""
import os
import hashlib

from backend.store import add_chunks, doc_hash_exists
from backend.ingest.audio import build_audio_chunks
from backend.ingest.pdf import build_pdf_chunks

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg", ".opus", ".mp4"}


def _file_hash(path):
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_file(path, filename):
    """Route an uploaded file by extension and store its chunks.
    Returns the chunk count, or None if this exact content (same bytes) is
    already in the library — the caller can tell a duplicate apart from a file
    that genuinely produced no chunks."""
    ext = os.path.splitext(filename)[1].lower()
    source_name = os.path.splitext(os.path.basename(filename))[0]
    h = _file_hash(path)
    if doc_hash_exists(h):
        return None                    # already ingested — don't duplicate chunks
    if ext in AUDIO_EXTS:
        chunks = build_audio_chunks(path, source_name)
    elif ext == ".pdf":
        chunks = build_pdf_chunks(path, source_name)
    else:
        raise NotImplementedError(f"'{ext}' isn't a supported file type.")
    for c in chunks:
        c["metadata"]["doc_hash"] = h
    return add_chunks(chunks)


def ingest_youtube(url):
    """Ingest a YouTube URL's audio; idempotent per URL. Returns the chunk
    count, or None if the URL was already ingested."""
    h = "yt:" + url
    if doc_hash_exists(h):
        return None
    from backend.ingest.youtube import build_youtube_chunks
    chunks = build_youtube_chunks(url)
    for c in chunks:
        c["metadata"]["doc_hash"] = h
    return add_chunks(chunks)
