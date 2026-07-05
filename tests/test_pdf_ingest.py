"""PDF ingestion — think-stripping and the full offline pipeline (vision stubbed)."""
import io

import fitz
from PIL import Image

import backend.ingest.pdf as pdfmod
from backend.config import MIN_FIGURE_PX


def test_strip_think_removes_reasoning_block():
    raw = "<think>\nmeta reasoning here\n</think>\n\nA bar chart of runtimes."
    assert pdfmod._strip_think(raw) == "A bar chart of runtimes."


def test_strip_think_no_block_is_noop():
    assert pdfmod._strip_think("plain caption") == "plain caption"


def _png_bytes(w, h, color="white"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_build_pdf_chunks_offline(tmp_path, monkeypatch):
    """Text extracted per page; big image kept + captioned; tiny logo filtered."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 560, 200), "QuickSort is O(n log n) on average.")
    page.insert_image(fitz.Rect(60, 220, 460, 520), stream=_png_bytes(600, 400))   # real figure
    page.insert_image(fitz.Rect(500, 40, 540, 80),
                      stream=_png_bytes(MIN_FIGURE_PX - 100, MIN_FIGURE_PX - 100, "black"))  # logo
    pdf_path = str(tmp_path / "deck.pdf")
    doc.save(pdf_path)
    doc.close()

    monkeypatch.setattr(pdfmod, "_caption_image", lambda b64: "A large white test figure.")
    monkeypatch.setattr(pdfmod, "FIGURES_DIR", str(tmp_path / "figures"))

    chunks = pdfmod.build_pdf_chunks(pdf_path, "deck")
    texts = [c for c in chunks if c["metadata"]["source_type"] == "pdf_text"]
    figs = [c for c in chunks if c["metadata"]["source_type"] == "pdf_figure"]
    assert texts and "QuickSort" in texts[0]["text"]
    assert len(figs) == 1                       # logo filtered by size
    assert figs[0]["metadata"]["page"] == 1


def test_skip_reply_drops_figure(tmp_path, monkeypatch):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(60, 60, 460, 460), stream=_png_bytes(600, 400))
    pdf_path = str(tmp_path / "logo_only.pdf")
    doc.save(pdf_path)
    doc.close()

    monkeypatch.setattr(pdfmod, "_caption_image", lambda b64: "SKIP")
    monkeypatch.setattr(pdfmod, "FIGURES_DIR", str(tmp_path / "figures"))

    figs = [c for c in pdfmod.build_pdf_chunks(pdf_path, "x")
            if c["metadata"]["source_type"] == "pdf_figure"]
    assert figs == []
