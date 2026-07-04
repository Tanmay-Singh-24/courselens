# 🎓 CourseLens

**Chat with your whole course.** Ingest lecture recordings, slide PDFs, and their
figures into one searchable knowledge base, then ask questions and get grounded
answers where **every citation is actionable** — click a source and the audio
jumps to the exact moment, or the referenced figure appears inline.

CourseLens is a multimodal, *agentic* RAG study tool built with LangGraph. It's
the successor to [PaperMind](../papermind) — same RAG backbone, expanded to cross
modalities and to cite its sources by timestamp.

**Highlights**
- 🎧 **Multimodal ingest** — audio, YouTube, and slide PDFs (incl. figures) in one knowledge base
- 🔗 **Actionable citations** — click to seek audio/video to the exact second, or view the cited figure inline
- 🧠 **Corrective-RAG grader** — refuses to answer from irrelevant context (**0% → 100%** refusal accuracy vs. no grader)
- 📊 **Measured, not vibes** — an eval harness with retrieval hit-rate, groundedness, and a grader ablation
- 🗺️ **Course Map** — an interactive concept graph over your whole course
- ⚙️ **Instrumented** — per-query latency + token usage

> **Status: V6 (feature-complete)** — audio + PDF (text & figures) ingestion, a
> **corrective-RAG grader** (retry-then-refuse), an **eval harness** (hit-rate,
> groundedness, grader ablation), **per-query instrumentation** (latency + tokens),
> deploy-ready, and a **Course Map** — an interactive concept graph over your library. See
> [`BUILD_PLAN.md`](BUILD_PLAN.md) for the roadmap, [`DEVLOG.md`](DEVLOG.md) for the
> build history, and [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) for a plain-language
> explanation.

---

## Architecture

```mermaid
flowchart TD
    subgraph Ingest["Ingest — multimodal → text"]
        A["Audio / YouTube"] -->|Whisper + timestamps| T1["Transcript chunks"]
        P["PDF"] --> T2["Page-text chunks"]
        P -->|figures → vision caption| T3["Figure-caption chunks"]
    end
    T1 --> E["HF embeddings"]
    T2 --> E
    T3 --> E
    E --> V[("ChromaDB")]

    subgraph Answer["Answer — agentic RAG (LangGraph)"]
        Q["Question"] --> RW["rewrite"] --> RT["retrieve top-5"] --> GR{"grade:<br/>relevant?"}
        GR -->|yes| GE["generate cited answer"]
        GR -->|no · retry| RW2["reformulate"] --> RT
        GR -->|no · give up| NF["refuse + list library"]
    end
    V --> RT
    GE --> UI["Actionable citations:<br/>audio seek · YouTube deep-link · inline figure"]
```

Two things are worth calling out honestly:

- **Ingest routing is plain code, not an "agent"** — it's file-extension matching.
- **The genuinely agentic layer is the corrective-RAG grader** (V3): after retrieval
  it judges relevance and, if the context doesn't answer the question, reformulates
  and retries (capped) — then refuses rather than hallucinating. Every LLM call in a
  turn (rewrite + grade + retries + generate) is metered for latency and tokens.

## Screenshots

_Drop captures into `docs/` (same file names) and they render here._

| Chat — deep-linked citations | Course Map |
|---|---|
| ![Cited answer with audio seeked to the moment](docs/chat.png) | ![Concept graph over the course](docs/course-map.png) |

Worth capturing: a cited answer with the **Sources** audio player, an answer that
renders a slide **figure inline**, the **Course Map**, and the **eval table**.

## Tech stack

- **LangGraph** — orchestrates rewrite → retrieve → generate as a stateful graph
- **Groq Whisper** (`whisper-large-v3`) — audio transcription with timestamps
- **Groq** (`llama-3.3-70b-versatile`) — rewriting, generation, grading, eval judge
- **Groq vision** (`qwen/qwen3.6-27b`) — figure captioning so images are searchable
- **PyMuPDF** — PDF text + embedded-figure extraction
- **ChromaDB** + **HuggingFace embeddings** (`all-MiniLM-L6-v2`) — vector store
- **imageio-ffmpeg** — bundled ffmpeg for audio conversion/splitting (no system install)
- **yt-dlp** — YouTube audio extraction (local-only bonus)
- **Streamlit** + **streamlit-agraph** — chat UI with actionable citations, and the Course Map concept graph

## Setup & run

**Prerequisites:** Python 3.10+, a free [Groq API key](https://console.groq.com).

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then edit .env and set GROQ_API_KEY
streamlit run frontend/app.py
```

Add a lecture (audio file or, locally, a YouTube URL) in the sidebar, wait for it
to transcribe, then ask questions. Answers cite their sources; expand **Sources**
to play the audio from the exact cited moment.

> ffmpeg is bundled via `imageio-ffmpeg`, so no separate install is needed. A
> 60–90 minute lecture is transcoded to FLAC and split automatically before
> transcription.

## Evaluation

CourseLens ships with an eval harness that turns the labeled test corpus into real
numbers — it doesn't just *work*, it's *measured*.

```bash
# ingest the test corpus, then evaluate (grader on vs off)
python -m backend.evals.run_evals --ingest
```

It reports, over a hand-labeled gold set ([`backend/evals/gold.jsonl`](backend/evals/gold.jsonl)):

- **Retrieval hit-rate@5** — is the correct source in the top-5 (timestamp ±60s / page ±1)?
- **Answer keyword match** — cheap correctness check
- **Groundedness** — LLM-as-judge: is every claim supported by the retrieved context?
- **Refusal accuracy** — do off-corpus questions get declined, not hallucinated?
- **Ablation** — the corrective-RAG grader **on vs off** on identical inputs

Results are written to `backend/evals/results.md`. The gold set covers **23 corpus
questions** (16 audio, 4 slide-text, 3 figure) plus **3 off-corpus** refusal checks.

**Ablation — what the corrective-RAG grader buys (the headline):** with the grader
**off**, off-corpus questions ("capital of France?") get answered from irrelevant
context — refusal accuracy **0%**. With it **on**, **100%**. That **0% → 100%** is the
grader earning its place, and it's robust regardless of set size.

On the initial 14-question set, retrieval hit-rate@5 and groundedness were both
**100%**. Regenerate on the full expanded corpus with
`python -m backend.evals.run_evals --ingest` — treat the numbers as directional.

## Instrumentation

Every query displays its **latency, total token usage, and retrieval-attempt count**
in the UI, and appends a row to `query_log.csv` — cheap observability for tuning
and cost tracking.

## Deploy (Streamlit Community Cloud)

Runs on the free tier. The disk is **ephemeral** — `chroma_store/` and `media_store/`
reset on every restart, so users start with an empty library and re-ingest (fine for
a demo; worth noting to reviewers).

1. Push to GitHub.
2. Go to **[share.streamlit.io](https://share.streamlit.io)** → **Create app** → deploy from your repo.
3. **Main file path:** `frontend/app.py`.
4. **Advanced settings → Secrets** — paste:
   ```toml
   GROQ_API_KEY = "gsk_your_key_here"
   ENABLE_YOUTUBE = "0"   # yt-dlp is blocked from cloud IPs — hide the feature
   ```
5. Deploy. First build is slow — it installs PyTorch (via sentence-transformers), so allow several minutes.

ffmpeg is bundled through `imageio-ffmpeg`, so no `packages.txt` is needed. The
`test_dataset/` folder has a small lecture + slide deck to try immediately.

## Roadmap

| Version | Adds |
|---|---|
| **V1** ✅ | Audio → timestamped, deep-linked RAG |
| **V2** ✅ | PDF text + figures (vision captions, figures shown inline) |
| **V3** ✅ | Corrective-RAG grader (the honest agentic loop) |
| **V4** ✅ | Eval harness — hit-rate, groundedness, grader ablation |
| **V5** ✅ | Per-query instrumentation (latency + tokens) + deploy-ready |
| **V6** ✅ | Course Map — interactive concept graph over the library |
