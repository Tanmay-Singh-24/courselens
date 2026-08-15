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


def test_text_survives_total_captioning_outage(tmp_path, monkeypatch):
    """A vision-model outage must not cost the document's text — the bulk of its
    value needs no vision model at all. Regression test for a 503 that killed a
    whole PDF ingest in production."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 560, 200), "QuickSort is O(n log n) on average.")
    for _ in range(4):                       # several figures, all uncaptionable
        page.insert_image(fitz.Rect(60, 220, 460, 520), stream=_png_bytes(600, 400))
    pdf_path = str(tmp_path / "outage.pdf")
    doc.save(pdf_path)
    doc.close()

    calls = []

    def busy(_b64):
        calls.append(1)
        raise RuntimeError("provider over capacity")

    monkeypatch.setattr(pdfmod, "_caption_image", busy)
    monkeypatch.setattr(pdfmod, "FIGURES_DIR", str(tmp_path / "figures"))

    warnings = []
    chunks = pdfmod.build_pdf_chunks(pdf_path, "outage", warnings)
    texts = [c for c in chunks if c["metadata"]["source_type"] == "pdf_text"]

    assert texts and "QuickSort" in texts[0]["text"]     # text ingested anyway
    assert warnings and "couldn't be described" in warnings[0]
    # Circuit breaker: stops calling after a streak, doesn't try every figure.
    assert len(calls) <= pdfmod.FIGURE_FAILURE_STREAK


def test_figure_captions_can_be_disabled(tmp_path, monkeypatch):
    """The ENABLE_FIGURE_CAPTIONS escape hatch skips the vision model entirely."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 560, 200), "Text body.")
    page.insert_image(fitz.Rect(60, 220, 460, 520), stream=_png_bytes(600, 400))
    pdf_path = str(tmp_path / "nofigs.pdf")
    doc.save(pdf_path)
    doc.close()

    def boom(_b64):
        raise AssertionError("vision model must not be called when disabled")

    monkeypatch.setattr(pdfmod, "_caption_image", boom)
    monkeypatch.setattr(pdfmod, "ENABLE_FIGURE_CAPTIONS", False)

    chunks = pdfmod.build_pdf_chunks(pdf_path, "nofigs")
    assert all(c["metadata"]["source_type"] == "pdf_text" for c in chunks)
    assert chunks


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
