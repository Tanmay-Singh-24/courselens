"""CourseLens — central configuration.

All tunables (model IDs, chunk sizes, paths, limits) live here so the rest of the
codebase imports from one place.

Groq model IDs verified against https://console.groq.com/docs/models and
/docs/vision on 2026-07-04. Re-verify before relying on them — Groq renames and
retires models (e.g. llama-4-scout, our original vision pick, was deprecated
2026-06-17; we now use qwen/qwen3.6-27b for image input).
"""
import os

from dotenv import load_dotenv

# ── PATHS ──────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
CHROMA_DIR = os.path.join(PROJECT_DIR, "chroma_store")
MEDIA_DIR = os.path.join(PROJECT_DIR, "media_store")
AUDIO_DIR = os.path.join(MEDIA_DIR, "audio")
FIGURES_DIR = os.path.join(MEDIA_DIR, "figures")

# Load a local .env so CLI entry points (the eval harness, scripts, tests) pick up
# GROQ_API_KEY too — not just the Streamlit app. Harmless when absent (e.g. on
# Streamlit Cloud, where the frontend injects secrets); load_dotenv does not
# override variables already present in the environment.
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# ── MODELS ─────────────────────────────────────────────────────────────────
WHISPER_MODEL = "whisper-large-v3"          # audio transcription
TEXT_MODEL = "llama-3.3-70b-versatile"      # rewrite + generate
VISION_MODEL = "qwen/qwen3.6-27b"           # figure captioning (image input)
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"       # local sentence embeddings

# ── RETRIEVAL / CHUNKING ───────────────────────────────────────────────────
COLLECTION_NAME = "courselens"
CHUNK_CHARS = 1000            # target transcript chunk size (characters)
CHUNK_OVERLAP = 100          # overlap for PDF text splitting
TOP_K = 5                     # chunks retrieved per query

# ── PDF FIGURES ────────────────────────────────────────────────────────────
# Skip tiny/decorative raster images (logos, rules, icons); caption only real
# figures. Groq caps base64 images at 4 MB — we downscale before sending.
MIN_FIGURE_PX = 150          # minimum width AND height to be treated as a figure
MAX_FIGURE_DIM = 1600        # downscale longest side to this before captioning

# ── AUDIO PIPELINE ─────────────────────────────────────────────────────────
# Groq's transcription endpoint caps upload size (free tier ~25 MB). We convert
# to 16 kHz mono FLAC (Groq-recommended, shrinks files a lot) and split anything
# still over the cap into fixed time windows.
WHISPER_MAX_BYTES = 24 * 1024 * 1024   # 24 MB, safety margin under the 25 MB cap
SEGMENT_SECONDS = 600                    # 10-minute split windows

# ── FEATURE FLAGS ──────────────────────────────────────────────────────────
# yt-dlp is blocked from datacenter IPs, so YouTube ingestion is a local-only
# bonus — disable it in hosted deploys via ENABLE_YOUTUBE=0.
ENABLE_YOUTUBE = os.environ.get("ENABLE_YOUTUBE", "1") == "1"

# Corrective-RAG grader (V3). Toggleable so the V4 eval harness can measure
# grader-on vs grader-off (the ablation that quantifies its value).
ENABLE_GRADER = os.environ.get("ENABLE_GRADER", "1") == "1"
MAX_RETRIEVAL_ATTEMPTS = 2   # grade → reformulate → retry cap (avoid loops + cost)


def seconds_to_timestamp(seconds):
    """Format seconds as M:SS (or H:MM:SS past an hour) for display + citations."""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
