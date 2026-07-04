# CourseLens — Build Plan

> **Audience:** the coding agent (Opus 4.8) that will implement this project across future sessions.
> **Status:** planning complete, zero code written. This document is the single source of truth for what to build, in what order, and what "done" means at each stage.
> **Companion doc:** `PROJECT_OVERVIEW.md` (plain-language explanation — read it first for the *why*; this file is the *how*).

---

## 1. What CourseLens is

CourseLens is a multimodal RAG study tool: a student ingests an entire course — lecture recordings (audio/video), slide PDFs with figures, and readings — into one searchable knowledge base, then asks questions and gets grounded answers where **every citation is actionable**:

- A transcript citation like **[Lecture 8 @ 14:32]** deep-links to the exact second (YouTube `&t=` URL, or an audio player seeked to that moment).
- A figure citation renders the **actual image** inline in the chat.
- A corrective-RAG grader refuses to answer from irrelevant context instead of hallucinating.
- An eval harness produces a real retrieval-accuracy number for the README/resume.

It is the successor to PaperMind (`~/VSCode/papermind`) — same core RAG skeleton (LangGraph `rewrite → retrieve → generate`, ChromaDB, HF embeddings, Groq LLM, Streamlit) — but a **standalone repo with its own name**. Reuse patterns and hard-won deployment lessons, not the repo itself.

### Non-negotiable framing rules (learned in planning)

1. **Never call the ingest-side file-type dispatch an "agent."** It is plain code (`if suffix == ".pdf"`). The genuinely agentic component is the **query-side grader loop** (corrective RAG). All docs, comments, and README language must reflect this honestly — the user will be grilled on this claim in interviews.
2. **Verify Groq model IDs before writing any code that references them** (step 0 below). Model names drift; do not trust the IDs written in planning docs, including this one.
3. **Each version must be independently shippable and demoable.** Do not start V(n+1) before V(n) runs end-to-end.
4. **Audio file upload is the reliable primary path; YouTube URL ingestion is a local-only bonus** (yt-dlp is blocked from datacenter IPs on Streamlit Cloud; a failed headline feature in a hosted demo is worse than no feature).

---

## 2. Repo setup

- Create a fresh repo directory (this folder, `~/VSCode/course-companion/`, may be renamed to `~/VSCode/courselens/` at scaffold time — user's call; keep both .md files).
- Python 3.10+ venv, pinned `requirements.txt` (pin every direct dep to the tested version, same discipline as PaperMind).
- `.gitignore` from day one: `.env`, `.streamlit/secrets.toml`, `chroma_store/`, `media_store/`, `venv/`, `__pycache__/`, `.DS_Store`.
- Secrets pattern copied from PaperMind's deployment fix: frontend resolves `GROQ_API_KEY` from `st.secrets` → `.env` fallback **before importing the backend** (the backend builds its LLM client at import time); guard `st.secrets` access in try/except (raises `StreamlitSecretNotFoundError` when no secrets file exists); `st.error` + `st.stop()` with a readable message if the key is missing. Ship `.env.example` and `.streamlit/secrets.toml.example`.

### Proposed layout

```
courselens/
├── backend/
│   ├── __init__.py
│   ├── config.py          # model IDs, chunk sizes, paths, TOP_K — one place
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── dispatch.py    # plain-code file-type detection → right ingestor
│   │   ├── pdf.py         # text chunks + figure extraction/captioning (V2)
│   │   ├── audio.py       # chunking, Groq Whisper, timestamped transcript chunks (V1)
│   │   └── youtube.py     # yt-dlp → audio.py pipeline (local-only bonus)
│   ├── store.py           # Chroma collection, embeddings, metadata schema helpers
│   ├── graph.py           # LangGraph: rewrite → retrieve → grade → generate/retry
│   └── evals/
│       ├── gold.jsonl     # hand-labeled eval set (V4)
│       └── run_evals.py   # hit-rate@k + groundedness, prints markdown table
├── frontend/
│   └── app.py             # Streamlit: uploads, chat, actionable citations
├── media_store/           # extracted figure images + uploaded audio (gitignored)
├── sample_course/         # tiny demo corpus (1 short lecture audio + 1 slide PDF)
├── .streamlit/secrets.toml.example
├── .env.example
├── requirements.txt
├── PROJECT_OVERVIEW.md
├── BUILD_PLAN.md
└── README.md
```

---

## 3. The metadata schema (cross-cutting — design once, used everywhere)

Every chunk stored in Chroma carries metadata that powers citations, deep links, figure rendering, and evals. **Chroma metadata values must be scalar (str/int/float/bool) — omit keys rather than storing `None`.**

| Key | Type | Present on | Purpose |
|---|---|---|---|
| `source_name` | str | all | display name, e.g. `"Lecture 8"` or `"slides_week3.pdf"` |
| `source_type` | str | all | `"pdf_text"` \| `"pdf_figure"` \| `"audio"` \| `"youtube"` |
| `ts_start` / `ts_end` | float (seconds) | audio/youtube | timestamp range of the chunk |
| `youtube_url` | str | youtube | base URL for `&t=` deep links |
| `audio_path` | str | audio | local path for `st.audio(..., start_time=...)` playback |
| `page` | int | pdf_text/pdf_figure | page number for citations |
| `figure_image_path` | str | pdf_figure | extracted image on disk → rendered inline in answers |

The `generate` node receives chunks *with* their metadata so the frontend can build actionable citations. Decide the transport format early (e.g., structured citation list alongside the answer text, not regex-parsing the LLM output).

---

## 4. Step 0 — verification pass (do this before any feature code)

1. **Groq model IDs, from Groq's live docs** (`console.groq.com/docs/models`): current production IDs for (a) Whisper transcription (planning assumption: `whisper-large-v3`), (b) a vision-capable model for figure captioning (planning assumption: a Llama-4 variant — **verify, do not trust**), (c) the text LLM for generation/grading (PaperMind used `llama-3.3-70b-versatile`).
2. **Groq audio constraints:** confirm the current file-size cap (~25 MB free tier at planning time) and whether `response_format="verbose_json"` returns segment-level timestamps (the whole V1 feature depends on this).
3. **Groq vision constraints:** confirm max image size for base64 payloads and per-request image limits.
4. **`streamlit-agraph` vs `pyvis`** click-callback support (only matters at V6; skip until then).

Record findings in `backend/config.py` comments with the verification date.

---

## 5. Build order

### V1 — Audio → timestamped, deep-linked RAG (the core demo)

**Goal:** upload a lecture audio file → transcribed with timestamps → chat with clickable citations.

Tasks:
1. **Audio preprocessing** (`ingest/audio.py`): accept mp3/m4a/wav; if over the Groq size cap, split into ~10-minute segments with ffmpeg (downsample to 16 kHz mono FLAC first — Groq's recommended format, dramatically shrinks size). Track each segment's start offset.
2. **Transcription:** Groq Whisper with `verbose_json`; collect segments `(start, end, text)`; add the chunk's segment offset so timestamps are global to the original file.
3. **Transcript chunking:** merge Whisper segments into ~1000-char chunks (respect segment boundaries; carry `ts_start` of first and `ts_end` of last merged segment). Do NOT re-split with a character splitter — that destroys timestamp alignment.
4. **Store** with full metadata schema; copy the uploaded audio into `media_store/` so playback works across reruns.
5. **Graph:** port PaperMind's `rewrite → retrieve → generate` (checkpointer, thread_id, temp=0). Generation prompt must instruct citing sources by name + timestamp.
6. **Frontend:** upload widget for audio; citations rendered as buttons/links — YouTube sources get `{url}&t={int(ts_start)}s` links; uploaded audio gets `st.audio(path, start_time=int(ts_start))` under an expander.
7. **YouTube path** (`ingest/youtube.py`): `yt-dlp` extract-audio → feed the same pipeline; store `youtube_url`. Feature-flag it (`ENABLE_YOUTUBE`, default on locally) and label it "local demo" in the UI.

**Done when:** a real lecture (60–90 min, i.e., over the size cap) ingests without error; asking a question yields a correct answer whose citation opens the video/audio at the right moment (±15s).

### V2 — PDF text + figures

**Goal:** slide decks and readings ingest fully; answers can cite and *display* figures.

Tasks:
1. **Text path** (`ingest/pdf.py`): PyMuPDF text extraction per page → chunk (~1000/100 overlap) with `page` metadata.
2. **Figure path:** extract embedded raster images per page; **filter junk** — skip images under ~150×150 px or extreme aspect ratios (logos, rules, icons); save keepers to `media_store/figures/`.
3. **Captioning:** send each kept image (base64) to the Groq vision model with a prompt tuned for *retrieval usefulness*: describe what the figure shows, axis labels, key entities and relationships — not aesthetics. Store caption as the chunk text, `source_type="pdf_figure"`, with `figure_image_path` + `page`.
4. **Frontend:** when a cited chunk is a figure, `st.image(figure_image_path, caption=...)` inline in the answer.
5. Document the known limitation: vector-drawn figures don't extract as raster images; state it in README rather than over-engineering around it.

**Done when:** a slide PDF with charts ingests; "what does the figure about X show?" retrieves the caption chunk and renders the actual image in the chat.

### V3 — Corrective-RAG grader (the honest agentic layer)

**Goal:** the system stops answering from irrelevant context.

Tasks:
1. **Grader node** in `graph.py`: after retrieval, an LLM call judges "does this context contain information that answers the question?" — use structured output (JSON `{relevant: bool, reason: str}` or a forced yes/no token) so parsing is deterministic. Grade the retrieved set as a whole (cheaper, sufficient) — per-chunk grading is an optional refinement.
2. **Conditional edges:** relevant → `generate`; not relevant → `rewrite_retry` (one reformulation attempt with a different phrasing strategy) → retrieve → grade again; still not relevant → `no_answer` node that says plainly what wasn't found, listing what *is* in the library. **Hard cap: 2 retrieval attempts** (cost + latency; infinite loops are the classic LangGraph bug).
3. Track `attempts` in graph state; surface grader verdicts in an expander in the UI (great for demos and debugging).
4. Keep the grader prompt strict about *sycophancy*: irrelevant-but-topically-adjacent context must be rejected.

**Done when:** an off-corpus question ("what's the capital of France?") triggers the no-answer path instead of a hallucinated answer, and an on-corpus question still answers in ≤2 attempts.

### V4 — Eval harness (the resume number)

**Goal:** a script that prints defensible accuracy metrics.

Tasks:
1. **Gold set** (`evals/gold.jsonl`): ~25 hand-labeled entries across all modalities: `{question, expected_source_name, expected_source_type, expected_ts_range | expected_page, answer_keywords}`. Build it from the sample course; the user labels; agent assists.
2. **Retrieval metric:** hit-rate@5 — expected source appears in top-5 retrieved chunks (timestamp hit = overlap with `expected_ts_range` ± 60s tolerance; page hit = exact page or ±1). Report overall and per-modality.
3. **Groundedness metric:** LLM-as-judge with a strict rubric — "is every claim in this answer supported by the provided context? yes/no + which claim fails." Report % grounded. (Acknowledge in README this judge is itself an LLM — imperfect but standard practice.)
4. **Harness mechanics:** cache retrieval/generation results per question on disk so re-runs are cheap and rate-limit-friendly; output a markdown table (overall + per-modality) that gets pasted into the README.
5. If corrective RAG is togglable, run the harness with the grader on vs. off — that ablation ("grader improved groundedness from X% to Y%") is the single best interview stat in the project.

**Done when:** `python -m backend.evals.run_evals` prints the table; README carries real numbers.

### V5 — Polish + deploy

1. **Instrumentation:** per-query wall-clock latency + token usage (Groq returns usage on responses), shown in a small expander; log to a local CSV for the "production mindset" story.
2. **Sample course** committed (one short CC-licensed lecture clip + one slide deck, few MB total) + first-run hint in the sidebar so a cold visitor immediately has something to try.
3. **Deploy to Streamlit Community Cloud** using the PaperMind playbook (secrets in dashboard, ephemeral-disk caveats — `media_store/` and `chroma_store/` reset on restart; that's acceptable, document it). Disable the YouTube path in hosted mode via the feature flag.
4. **README** in PaperMind's style: problem → demo GIF → architecture diagram → eval table → honest limitations section → setup → deploy.

### V6 (stretch) — Course Map

Concept-graph visualization (the Obsidian-style map the user wants): one extra LLM pass at ingest extracts key concepts per chunk; nodes = top-N concepts (cap ~40 — avoid the hairball), edges = embedding-similarity or co-occurrence above a threshold; render with `streamlit-agraph` (supports click callbacks) — clicking a node runs a retrieval for that concept and shows where it appears across the course. Build **only after V5 ships**; prototype the click-callback constraint first since it's the known technical risk.

---

## 6. Cross-cutting engineering notes

- **Rate limits:** free-tier Groq will throttle bulk ingestion (a 50-figure deck = 50 vision calls). Batch politely, back off on 429s, and cache aggressively (hash file → skip re-ingestion of already-ingested content).
- **Determinism:** temp=0 everywhere; evals are still not perfectly deterministic — note it, don't fight it.
- **One Chroma collection** with `source_type` metadata (not per-modality collections) so retrieval is naturally cross-modal; add metadata filtering only if evals show cross-modal noise.
- **PaperMind carryover bugs to not repeat:** `InMemorySaver` loses conversation state on process restart (fine for demo, note it); the shared-collection/no-per-user-isolation caveat — document it again.
- **No secrets in git, ever.** Verify with `git status` before every commit that `.env`, `secrets.toml`, `chroma_store/`, `media_store/` are untracked.
- **Style:** match PaperMind's code style — section-banner comments, purposeful docstrings, thin frontend / logic in backend.

## 7. What NOT to do

- Don't claim "multi-agent" anywhere the grader loop doesn't justify it.
- Don't hardcode model IDs from this document without re-verifying against Groq's docs.
- Don't build V6 (or any UI polish) before V4's numbers exist — the eval table is worth more than any visual.
- Don't make YouTube ingestion the demo's front door.
- Don't re-split Whisper segments with a character splitter (destroys timestamps).
- Don't store `None` in Chroma metadata (it rejects it) — omit the key.
