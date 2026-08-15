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
import time
import base64
import hashlib

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import (
    CHUNK_CHARS,
    CHUNK_OVERLAP,
    ENABLE_FIGURE_CAPTIONS,
    FIGURE_CAPTION_ATTEMPTS,
    FIGURE_FAILURE_STREAK,
    FIGURES_DIR,
    FIGURE_TIME_BUDGET_S,
    MAX_FIGURES_PER_DOC,
    VISION_TIMEOUT_S,
    VISION_MAX_TOKENS,
    VISION_REASONING_EFFORT,
    MAX_FIGURE_DIM,
    MIN_FIGURE_PX,
    VISION_MODEL,
    media_relpath,
)
from backend.retry import call_with_retry

_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_CHARS, chunk_overlap=CHUNK_OVERLAP)
_groq_client = None


def _client():
    """Lazily build the Groq client (kept out of import so text-only paths and
    tests don't require the SDK/key)."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        # Bounded request, and max_retries=0 so call_with_retry is the only retry
        # layer — the SDK's own retries would multiply with ours and make a slow
        # provider look like a hang.
        _groq_client = Groq(timeout=VISION_TIMEOUT_S, max_retries=0)
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
        try:
            # Per-page guard: real-world PDFs contain the occasional page that
            # trips the extractor (odd encodings, damaged objects). Losing one
            # page is acceptable; losing the document is not.
            text = (doc[i].get_text() or "").strip()
        except Exception:
            continue
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


def _strip_think(text):
    """Remove a reasoning model's <think>…</think> block so the caption embedding
    reflects the figure's content, not the model's meta-reasoning."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _caption_image(b64):
    """Ask the Groq vision model for a retrieval-useful caption.

    Wrapped in the shared retry: the vision model is the busiest thing we call,
    and a capacity blip (503) mid-deck used to lose the whole ingestion — text
    chunks included — because only 429 was handled here.
    """
    def _once():
        resp = _client().chat.completions.create(
            model=VISION_MODEL,
            temperature=0,
            # Skip the reasoning pass: we discard it anyway, and it costs ~9x the
            # tokens of the caption itself.
            reasoning_effort=VISION_REASONING_EFFORT,
            max_tokens=VISION_MAX_TOKENS,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": CAPTION_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
        )
        return _strip_think(resp.choices[0].message.content)

    return call_with_retry(_once, attempts=FIGURE_CAPTION_ATTEMPTS)


def _extract_figure_chunks(doc, source_name, warnings=None):
    """Caption each real figure. Best-effort by design: a figure we can't caption
    is skipped, never fatal — the document's text is the bulk of its value and
    needs no vision model. After FIGURE_FAILURE_STREAK consecutive failures we
    stop calling the model at all, so a provider outage costs seconds, not the
    retry budget of every remaining figure."""
    chunks, seen = [], set()
    failures = streak = skipped_for_budget = 0
    provider_down = quota_hit = False
    # Whatever is captioned within the budget is kept; the rest is skipped, so
    # ingestion finishes in bounded time however slow the provider is.
    deadline = time.monotonic() + FIGURE_TIME_BUDGET_S

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
            if provider_down:              # circuit open — don't keep hammering
                failures += 1
                continue
            if len(chunks) >= MAX_FIGURES_PER_DOC or time.monotonic() > deadline:
                skipped_for_budget += 1
                continue
            try:
                # Image normalisation (CMYK/alpha conversion, downscaling) is in
                # here too: a single odd image must not cost the document either.
                path, b64 = _save_png(pix)
                caption = _caption_image(b64)
                streak = 0
            except Exception as exc:
                failures += 1
                streak += 1
                # Distinguish "out of quota" from "temporarily busy": one clears
                # at the daily reset, the other in a minute. Telling the user to
                # retry shortly when the budget is gone just wastes their time.
                if getattr(exc, "status_code", None) == 429:
                    quota_hit = True
                if streak >= FIGURE_FAILURE_STREAK:
                    provider_down = True
                continue
            # None/empty caption (model returned no content) → skip, don't crash
            if not caption or caption.upper().startswith("SKIP"):
                continue
            chunks.append({
                "text": caption,
                "metadata": {
                    "source_name": source_name,
                    "source_type": "pdf_figure",
                    "page": i + 1,
                    # relative to media_store/ so the citation survives moves
                    "figure_image_path": media_relpath(path),
                },
            })

    if warnings is not None:
        if failures:
            why = ("the free-tier daily image-description quota is used up"
                   if quota_hit else "the vision model is busy")
            when = "after the quota resets" if quota_hit else "in a few minutes"
            warnings.append(
                f"{failures} figure(s) couldn't be described ({why}) — all text from "
                f"this document is fully searchable; re-upload {when} to add the figures."
            )
        if skipped_for_budget:
            warnings.append(
                f"Described the first {MAX_FIGURES_PER_DOC} figures and skipped "
                f"{skipped_for_budget} more to keep ingestion quick — all text is indexed."
            )
    return chunks


def build_pdf_chunks(src_path, source_name, warnings=None):
    """PDF file → text chunks + figure-caption chunks ready for the store.

    `warnings` (optional list) collects non-fatal problems worth surfacing to the
    user, e.g. figures skipped because the vision model was unavailable.
    """
    with fitz.open(src_path) as doc:
        chunks = _extract_text_chunks(doc, source_name)
        if ENABLE_FIGURE_CAPTIONS:
            chunks += _extract_figure_chunks(doc, source_name, warnings)
        return chunks
