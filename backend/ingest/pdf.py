"""CourseLens — PDF ingestion (V2).

Two chunk streams from one PDF, both landing in the same collection:
  • text    — per-page text split into ~CHUNK_CHARS chunks (source_type="pdf_text")
  • figures — embedded raster images captioned by a Groq vision model so the
              picture becomes searchable text (source_type="pdf_figure"); the real
              image is saved to disk and shown inline when the answer cites it.

Junk images (logos, rules, icons) are filtered by size. Vector-drawn figures are
NOT extracted — PyMuPDF only yields raster images (a documented limitation).
"""
import os
import io
import re
import base64
import hashlib

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import (
    CHUNK_CHARS,
    CHUNK_OVERLAP,
    FIGURES_DIR,
    MAX_FIGURE_DIM,
    MIN_FIGURE_PX,
    VISION_MODEL,
)

_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_CHARS, chunk_overlap=CHUNK_OVERLAP)
_groq_client = None


def _client():
    """Lazily build the Groq client (kept out of import so text-only paths and
    tests don't require the SDK/key)."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq()
    return _groq_client


CAPTION_PROMPT = (
    "You are describing a figure from course slides so it can be found later by text "
    "search. In 2-4 sentences, state what the figure shows: its type (chart, diagram, "
    "table, photo), any title/axis labels or headings, the key entities and their "
    "relationships, and notable values or trends. Do not describe visual style. If it "
    "is a logo or purely decorative image, reply with exactly: SKIP"
)


# ── TEXT ─────────────────────────────────────────────────────────────────────
def _extract_text_chunks(doc, source_name):
    chunks = []
    for i in range(len(doc)):
        text = doc[i].get_text().strip()
        if not text:
            continue
        for piece in _splitter.split_text(text):
            chunks.append({
                "text": piece,
                "metadata": {
                    "source_name": source_name,
                    "source_type": "pdf_text",
                    "page": i + 1,
                },
            })
    return chunks


# ── FIGURES ──────────────────────────────────────────────────────────────────
def _save_png(pix):
    """Normalize a pixmap to RGB PNG, downscale if large, save (hash-named), and
    return (path, base64). Keeps the base64 payload under Groq's 4 MB cap."""
    if pix.colorspace and pix.colorspace.n >= 4:      # CMYK → RGB
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if pix.alpha:                                     # drop alpha for clean PNG
        pix = fitz.Pixmap(pix, 0)
    png = pix.tobytes("png")

    from PIL import Image
    img = Image.open(io.BytesIO(png))
    if max(img.size) > MAX_FIGURE_DIM:
        img.thumbnail((MAX_FIGURE_DIM, MAX_FIGURE_DIM))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()

    digest = hashlib.sha1(png).hexdigest()[:16]
    os.makedirs(FIGURES_DIR, exist_ok=True)
    path = os.path.join(FIGURES_DIR, f"{digest}.png")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(png)
    return path, base64.b64encode(png).decode()


def _caption_image(b64):
    """Ask the Groq vision model for a retrieval-useful caption."""
    resp = _client().chat.completions.create(
        model=VISION_MODEL,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": CAPTION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
    )
    content = resp.choices[0].message.content
    # qwen3.6 is a reasoning model — strip its <think>…</think> block so the caption
    # embedding reflects the figure's content, not the model's meta-reasoning.
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()


def _extract_figure_chunks(doc, source_name):
    chunks, seen = [], set()
    for i in range(len(doc)):
        for img in doc[i].get_images(full=True):
            xref = img[0]
            if xref in seen:               # same image reused across pages
                continue
            seen.add(xref)
            try:
                pix = fitz.Pixmap(doc, xref)
            except Exception:
                continue
            if pix.width < MIN_FIGURE_PX or pix.height < MIN_FIGURE_PX:
                continue                   # decorative / junk
            path, b64 = _save_png(pix)
            caption = _caption_image(b64)
            if caption.upper().startswith("SKIP"):
                continue
            chunks.append({
                "text": caption,
                "metadata": {
                    "source_name": source_name,
                    "source_type": "pdf_figure",
                    "page": i + 1,
                    "figure_image_path": path,
                },
            })
    return chunks


def build_pdf_chunks(src_path, source_name):
    """PDF file → text chunks + figure-caption chunks ready for the store."""
    with fitz.open(src_path) as doc:
        return _extract_text_chunks(doc, source_name) + _extract_figure_chunks(doc, source_name)
