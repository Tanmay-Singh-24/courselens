# CourseLens — Development Log

A running record of what was built, what broke, and how it was resolved — updated
**after each version**. Companion to [`BUILD_PLAN.md`](BUILD_PLAN.md) (the plan)
and [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) (the plain-language explanation).

Newest version on top.

---

## V6.1 — Code review, hardening & CI  ·  2026-07-04  ·  ✅

Full-codebase review pass; every finding fixed the same day.

### Findings & fixes
| Severity | Finding | Fix |
|---|---|---|
| **High** | `render_sources` called `st.audio`/`st.image` on media paths stored in Chroma metadata without checking the file exists — on Streamlit Cloud, `media_store/` can be wiped (restart) while metadata survives, crashing the whole chat render. | Guard with `os.path.exists`; show *"media unavailable — re-ingest to restore playback"* instead. |
| **Medium** | One 429 while captioning figure #3 of a big deck threw away the entire PDF ingestion (text chunks included). | `_caption_image` now retries with exponential backoff (2s/4s) before giving up. |
| **Medium** | No test suite — all validations lived as ad-hoc session scripts. | **`tests/` pytest suite: 36 offline tests** (chunking, grader parse/route, citation filter, labels, eval scoring, aggregation, concept map, PDF pipeline with vision stubbed, config/store utils). Runs in ~12s, zero API calls. |
| **Low** | `run_evals._ingest_test_corpus` derived the repo root via `G.__file__.rsplit("backend", 1)` — fragile. | Use `config.PROJECT_DIR`. |
| **Low** | Think-strip regex was inline (untestable); 1 ruff `F541` lint. | Extracted `_strip_think()`; ruff auto-fix; repo now lints clean under `ruff.toml` (E/F/W). |
| **Noted** | YouTube dedup keys on the raw URL — `youtu.be/x` vs `watch?v=x` would double-ingest. | Documented; canonicalizing needs a metadata fetch pre-download — deferred. |

### CI added
- **GitHub Actions** (`.github/workflows/ci.yml`): lint → compile → pytest on every
  push/PR; pip + HuggingFace-model caching; dummy `GROQ_API_KEY` (tests are offline).
- **`Jenkinsfile`** with the same stages for a Jenkins server.
- README: CI badge + "Tests & CI" section; future-work updated (CI done → Docker CD next).

### Test-writing note
One initially-failing test was a wrong *expectation* (60-char segments with a
100-char budget correctly yield one chunk per segment, not two) — the code was right;
the test was fixed and a second case added for the merge-then-split path.

---

## V6 — Course Map (concept graph)  ·  2026-07-04  ·  ✅ built & logic-validated

**Goal:** an interactive concept graph over the ingested library — the Obsidian-style
"map" — so a student sees how the course hangs together and can jump to where a
concept appears.

### Steps performed
1. **`backend/concept_map.py`** — one LLM pass **per source** extracts key concepts
   (cached by content hash); `assemble_graph` (pure) builds nodes (concepts, capped
   to 40) and edges (concepts co-occurring in a source). Returns nodes/edges/concept→sources.
2. **Frontend** — a sidebar **view switch** (💬 Chat / 🗺️ Course Map) renders the graph
   with `streamlit-agraph`; nodes are colored by source. Clicking (or selecting) a
   concept shows where it appears via **free local retrieval** (no LLM).

### Problems encountered & resolutions
| Problem | Resolution |
|---|---|
| `st.chat_input` can't live inside `st.tabs`/containers (Streamlit restriction). | Used a **sidebar radio + `st.stop()`** to switch views instead of tabs — chat_input stays in the main body. |
| Concept extraction per *chunk* would be token-heavy (and the user is token-constrained). | Extract once **per source**, cache by content hash → a handful of calls per library, free to reopen. |
| Exploring a concept shouldn't cost tokens. | The "where it appears" action uses `similarity_search` (local embeddings) — **zero LLM calls**. |
| Hairball risk with many concepts. | Cap to the 40 most cross-source concepts. |
| Click-callback reliability (flagged in planning as the known risk). | `agraph()` returns the clicked node; a **selectbox fallback** makes exploration work even if clicks don't. |

### Verified (without a Groq key)
- `streamlit-agraph==0.0.45` installs + imports ✅
- `py_compile` all changed modules ✅
- `_parse_concepts` (clean / embedded / garbage) and `assemble_graph`
  (nodes, edges, cross-source linking, 40-node cap) ✅

### Outstanding / carried forward
- Concept extraction + graph rendering need a Groq key + Streamlit runtime to see
  live (concepts cached to `media_store/concept_cache.json`, gitignored).
- **Project is feature-complete (V1–V6).** Remaining is the user's: deploy + a full
  eval run when the daily token limit resets.

---

## V5.1 — Eval gold-set expansion  ·  2026-07-04  ·  ✅

Doubled the labeled eval to make the numbers more credible — a perfect score on 14
questions is weaker evidence than a documented ~90%+ on a larger, harder set, and the
figure capability (the differentiator) was only n=1. Generated a second known-answer
lecture (**Data Structures**, 48s, sectioned for exact timestamps) and a **two-figure**
slide deck (memory bar chart p.1 + access-time table p.2). Gold set **16 → 26**
(23 corpus: 16 audio / 4 text / **3 figure** — figure questions tripled — + 3 off-corpus);
wired both files into the harness `--ingest`.

**Note for the next run:** the corpus grew, so clear the cache (`rm
backend/evals/.cache.json`) for a clean measurement, and expect hit-rate to move off a
suspiciously-perfect 100% — that's the point; a documented miss with analysis reads as
more rigorous than a perfect score. Needs a Groq key + tokens.

---

## V5 — Instrumentation + deploy prep  ·  2026-07-04  ·  ✅ built & validated

**Goal:** per-query observability (latency + token usage) and make the repo
deployable on Streamlit Community Cloud.

### Steps performed
1. **Token + latency capture** — `get_response` wraps `graph.invoke` in
   `get_usage_metadata_callback()` (langchain-core 1.4.0) to sum tokens across
   *every* LLM call in the turn (rewrite + grade + retries + generate), and times
   wall-clock latency. Returns `latency_s` + `total_tokens`.
2. **Telemetry log** (`backend/telemetry.py`) — appends one row per query
   (ts, question, latency, tokens, attempts, #sources) to `query_log.csv`
   (gitignored, best-effort).
3. **UI** — a small `⚙️ latency · tokens · attempts` caption under each answer.
4. **Deploy prep** — generalized the frontend secrets bridge to copy *all* string
   secrets into the env (so `ENABLE_YOUTUBE=0` can be set in the cloud dashboard to
   hide YouTube); README **Deploy** section (entry point, secrets, ephemeral-disk
   caveat, slow first build); confirmed no `packages.txt` needed (ffmpeg is bundled).

### Problems encountered & resolutions
| Problem | Resolution |
|---|---|
| Token usage lives on individual LLM responses, but a turn makes several calls (grade, retry, generate). | `get_usage_metadata_callback()` aggregates usage across all nested calls via config-propagated callbacks — one number per turn. |
| YouTube must be off on Streamlit Cloud (yt-dlp blocked from cloud IPs), but only `GROQ_API_KEY` was bridged from secrets. | Bridge every string secret to the env, so `ENABLE_YOUTUBE=0` in the dashboard disables the feature. |

### Verified (without a Groq key)
- `py_compile` all changed modules ✅
- telemetry imports; `get_response` wired for `latency_s` + `total_tokens` via the
  usage callback (confirmed by source inspection) ✅

### Outstanding / carried forward
- Actual latency/token numbers appear at runtime (need a Groq key) — visible in the
  UI caption and `query_log.csv`.
- Deploy is the user's action (push + connect on share.streamlit.io).
- Next (optional): **V6** Course Map concept graph (stretch).

---

## V4 — Eval harness (real numbers)  ·  2026-07-04  ·  ✅ built & logic-validated

**Goal:** turn the known test corpus into defensible metrics — retrieval hit-rate,
groundedness, refusal accuracy — plus the grader on/off ablation.

### Steps performed
1. **Gold set** (`backend/evals/gold.jsonl`) — 16 entries: 14 corpus questions
   across `audio` / `pdf_text` / `pdf_figure` (with expected source + timestamp/page
   + answer keywords) and 2 off-corpus "expect refusal" entries.
2. **Harness** (`backend/evals/run_evals.py`):
   - retrieval hit-rate@5 (deterministic; ts overlap ±60s / page ±1),
   - answer keyword match (cheap correctness),
   - groundedness via LLM-as-judge (strict JSON rubric),
   - refusal accuracy on off-corpus questions,
   - **grader ON vs OFF ablation** via `build_graph(enable_grader)`,
   - disk cache keyed by (mode, tag, question); markdown report → `results.md`.
3. **`get_response` now returns `context`** so groundedness is judged against the
   context actually used.
4. **`--ingest`** convenience flag to load the test corpus before evaluating.

### Problems encountered & resolutions
| Problem | Resolution |
|---|---|
| Retrieval metric vs. graph's retried query could diverge. | Measure hit-rate on the **raw query's** top-5 (deterministic, grader-independent); judge groundedness against the graph's **actually-used** context. Both well-defined; documented. |
| The groundedness judge is itself an LLM (can misjudge / misformat). | Strict JSON rubric; **conservative parse** (unparseable → not grounded); refusals count as grounded; README flags it as imperfect-but-standard. |
| Rate limits make repeated eval runs slow/expensive. | Cache every answer + judge verdict to `.cache.json`; `--no-cache` to force fresh. |
| Small gold set (n=14) → numbers are directional, not statistically tight. | Documented as a limitation; gold set is easy to expand toward the ~25 in BUILD_PLAN. |
| **Harness crashed at import** — `GroqError: api_key must be set`. Only the Streamlit frontend loaded `.env`; CLI entry points didn't, so `ChatGroq()` had no key at import. | Moved `load_dotenv(.env)` into `config.py` (imported first by everything), so every entry point gets the key. Verified: harness imports with no shell env var. |

### Verified (without a Groq key)
- `py_compile`; gold schema integrity ✅
- `_retrieval_hit` (audio overlap, page ±1, pdf stream match) ✅
- `_keyword_hit` / `_is_refusal` / `_parse_groundedness` ✅
- `_summarize` + `_markdown` render overall/per-modality/ablation ✅

### First real run — results & the bugs it caught (this is the point of evals)
First end-to-end run on the user's Groq key live-validated V1 transcription + V2
vision captioning. Headline numbers (grader ON, n=14): retrieval hit-rate@5 **93%**
(audio 100%, pdf_text 100%, pdf_figure 0%), groundedness **100%**, and
**refusal accuracy 0% → 100%** with the grader — the ablation win that justifies the
whole corrective-RAG layer. The run immediately exposed two real bugs:

| Bug | Symptom | Fix |
|---|---|---|
| **Reasoning-model think tokens in captions.** qwen3.6 emits `<think>…</think>`; we stored the whole output, so the figure caption was buried under meta-reasoning and its embedding didn't match the query. | C4 (figure) retrieval miss. | Strip `<think>…</think>` in `_caption_image` before storing. |
| **Non-idempotent ingestion.** Re-ingesting duplicated chunks (each slide chunk appeared 3×), wasting the top-5 retrieval slots. | Duplicates crowded the figure chunk out of the top-5. | Dedupe by file-content hash (`doc_hash`) in `dispatch`; also deleted a shadowing duplicate `ingest_youtube` that would have disabled the dedup. |

Also reworded gold **B2** (ambiguous "them" → self-contained) — the grader-ON keyword
dip was an eval artifact (pronoun with no conversation context in the harness), not a
regression. Reset `chroma_store` + cache for a clean re-run.

### Post-fix re-run — clean numbers, and a rate-limit robustness fix
Re-run after the fixes: **C4 (figure) flipped ✗ → ✓** — grader ON scored **100%**
across retrieval hit-rate, keyword, groundedness, and refusal (n=14 + 2 off-corpus).
Confirms the `<think>`-strip + dedup fixes. The grader-OFF pass then hit the **free-tier
daily token cap (100k TPD)** and threw `groq.RateLimitError`, which **crashed the whole
harness** and lost partial results. Fixed: the harness now catches the rate limit,
stops the pass gracefully, keeps cached progress, writes whatever completed, and flags
partial results (so a later re-run resumes cheaply). Also truncated the groundedness
judge's context to trim token use.

### Outstanding / carried forward
- Grader-ON numbers are in the README. The clean grader-OFF column needs the daily
  token limit to reset; `python -m backend.evals.run_evals` resumes from cache.
- Expand gold set toward ~25 for tighter numbers.
- Next: **V5** (instrumentation, sample course, deploy).

---

## V3.1 — Citation display fix  ·  2026-07-04  ·  ✅ fixed

**Problem (found on first real run):** asking *"which animal is this"* correctly
answered "elephant" from the zoo clip, but the **Sources** panel also listed three
unrelated *"LangChain vs LangGraph"* links. Root cause: retrieval returns the top-5
nearest chunks with **no relevance floor**, so unrelated sources fill the empty
slots, and the UI displayed **all retrieved** chunks rather than the ones the answer
**cited**.

**Fix:** `_cited_sources(answer, sources)` keeps only sources whose label or name
appears in the generated answer, falling back to all if the model didn't cite
recognizably. Applied in `get_response`. Verified offline (keeps only the cited
source; falls back when none match). The grader was working correctly — it grades
the *set* (which contained the answer), so this was purely a display bug.

---

## V3 — Corrective-RAG grader (the agentic loop)  ·  2026-07-04  ·  ✅ built & validated

**Goal:** after retrieval, judge whether the context actually answers the question;
if not, reformulate and retry (capped), else refuse honestly. This is the piece
that makes the "agentic" claim真 — one agent that loops and second-guesses itself.

### Steps performed
1. **Graph rewritten** (`graph.py`) to `rewrite → retrieve → grade → {generate |
   rewrite_retry→retrieve | no_answer}` with LangGraph conditional edges.
2. **Grader node** — strict JSON relevance verdict (`{relevant, reason}`), with an
   anti-sycophancy prompt (topically-adjacent ≠ relevant).
3. **Retry + refuse** — one reformulation with different wording; `no_answer` node
   refuses and lists what the library *does* cover (added `store.list_sources`).
4. **Toggle** — `build_graph(enable_grader)`; grader-off = the V1 linear pass, so
   V4 can ablate. Flag `ENABLE_GRADER`, cap `MAX_RETRIEVAL_ATTEMPTS=2`.
5. **UI** — `get_response` now returns `verdicts`/`attempts`; the app shows a
   "Retrieval check" expander with each attempt's verdict.

### Problems encountered & resolutions
| Problem | Resolution |
|---|---|
| A flaky/malformed grader response could **block a valid answer**. | `_parse_grade` **fails open** (treats as relevant) on any parse error — a broken grader degrades to V1 behavior, never to a false refusal. |
| Conditional loops in LangGraph can **run forever** (classic bug). | Hard cap `MAX_RETRIEVAL_ATTEMPTS=2`; the counter is set in `rewrite_query` and bumped in `rewrite_retry`; routing sends to `no_answer` at the cap. |
| Grader **sycophancy** — accepting on-topic-but-non-answering context. | Strict grader prompt explicitly rejects related-topic/mention-only context. |
| Needed to **quantify** the grader's value for V4. | Made it toggleable; the ablation (grader on vs off, same inputs) is the headline V4 stat. |
| Empty context still cost an LLM grading call. | Short-circuit: empty context → `relevant=False` without calling the model. |

### Verified (without a Groq key)
- `py_compile` all changed modules ✅
- `_parse_grade`: clean JSON, JSON embedded in prose, and garbage (→ fail-open) ✅
- `_route_after_grade`: relevant→generate, miss@attempt1→retry, miss@cap→no_answer ✅
- `build_graph(True/False)` compiles; toggle adds/removes grade+retry+no_answer nodes ✅

### Outstanding / carried forward
- **Real grading quality** needs the Groq key — validate locally that the
  off-corpus question ("capital of France") now hits the refuse path.
- Next: **V4 eval harness** — hit-rate@5 + groundedness, and the grader on/off ablation.

---

## V2 — PDF text + figures (vision captions)  ·  2026-07-04  ·  ✅ built & validated

**Goal:** ingest slide/reading PDFs — split page text into chunks *and* extract
embedded figures, caption them with a vision model so they're searchable, and
show the real figure inline when an answer cites it.

### Steps performed
1. **Step 0 verification** (vision model) — checked `console.groq.com/docs/vision`.
2. **Added `ingest/pdf.py`** — `build_pdf_chunks`: per-page text via PyMuPDF →
   RecursiveCharacterTextSplitter (`pdf_text`, with `page`); embedded raster images
   → size-filter → downscale/normalize to PNG → Groq vision caption (`pdf_figure`,
   with `page` + `figure_image_path`). Vector figures are not extracted (documented).
3. **Wired routing** — `dispatch.py` sends `.pdf` to the PDF ingestor.
4. **Citations** — `graph.py` labels figures as "… — Figure (p.N)" and passes
   `figure_image_path` through to the UI; `app.py` renders the figure inline via
   `st.image`, and the uploader now accepts PDFs.
5. **Config** — added `VISION_MODEL`, `FIGURES_DIR`, `MIN_FIGURE_PX`,
   `MAX_FIGURE_DIM`, `CHUNK_OVERLAP`.
6. **Test dataset** — generated `slides/sorting_algorithms_slides.pdf` (2 pages of
   text + an embedded bar chart + a tiny logo) and gold questions (Source C).

### Problems encountered & resolutions
| Problem | Resolution |
|---|---|
| **Planned vision model was deprecated.** `meta-llama/llama-4-scout-17b-16e-instruct` (BUILD_PLAN's pick) was retired **2026-06-17**. | Switched to **`qwen/qwen3.6-27b`** (current image-capable model per Groq vision docs). Exactly the "verify before trusting the doc" rule paying off. |
| Groq base64 image cap is **4 MB**; slide figures can be high-res. | Downscale longest side to `MAX_FIGURE_DIM` (1600px) with Pillow before encoding. |
| Pixmaps can be **CMYK or have alpha** → PNG encoding issues. | Normalize to RGB and drop alpha before `tobytes("png")`. |
| Logos/rules/icons would waste vision calls and pollute retrieval. | Filter images below `MIN_FIGURE_PX` (150px) on either side; also honor a `SKIP` reply from the caption prompt. |
| Same logo repeated on every page → duplicate captions. | Dedupe by image `xref` across pages. |

### Verified (without a Groq key)
- `py_compile` all changed modules ✅
- `pdf` module imports; `VISION_MODEL = qwen/qwen3.6-27b` ✅
- **Offline PDF pipeline test** (vision call stubbed) on the generated slides PDF:
  2 text chunks (pages 1–2), exactly **1 figure kept** (chart), **tiny logo
  filtered**, figure PNG saved to `media_store/figures/` ✅

### Outstanding / carried forward
- **Real figure captioning** needs the Groq key (vision call) — validate locally.
  Watch base64 size on dense, high-res scans.
- Pinned pymupdf==1.28.0 (Pillow transitive, 12.3.0).
- Next: **V3 corrective-RAG grader** (the honest agentic loop).

---

## V1 — Audio → timestamped, deep-linked RAG  ·  2026-07-04  ·  ✅ built & validated

**Goal:** upload lecture audio (or a YouTube URL) → transcribe with timestamps →
chat with clickable citations that seek to the exact moment.

### Steps performed
1. **Step 0 verification** — confirmed against `console.groq.com/docs/models`:
   `whisper-large-v3` (transcription) and `llama-3.3-70b-versatile` (text) are current.
2. **Repo scaffolded** at `~/VSCode/CourseLens/`: `backend/` (config, store, graph,
   `ingest/`), `frontend/app.py`, `.streamlit/`, `media_store/`, plus requirements,
   gitignore, and secrets templates (reusing PaperMind's secrets-bridge pattern).
3. **Metadata schema** implemented up front (source_name/type, ts_start/end,
   audio_path, youtube_url) so citations + evals share one contract.
4. **Audio pipeline** (`ingest/audio.py`): FLAC convert → size-cap split →
   Groq Whisper (`verbose_json`) → segment-preserving chunk merge with GLOBAL timestamps.
5. **YouTube path** (`ingest/youtube.py`): yt-dlp → same pipeline (feature-flagged).
6. **Graph** (`graph.py`): PaperMind's rewrite → retrieve → generate, now emitting
   structured `sources` for actionable citations.
7. **Frontend** (`app.py`): audio/YouTube ingest + chat + Sources panel (audio player
   seeked to timestamp / YouTube `&t=` deep links).
8. **Test dataset** curated (`test_dataset/`): a synthetic known-answer lecture with
   exact per-topic timestamps + a real YouTube clip + gold questions.

### Problems encountered & resolutions
| Problem | Resolution |
|---|---|
| **ffmpeg not installed** on the machine (needed for convert/split). | Depend on `imageio-ffmpeg` (pip-bundled ffmpeg binary) with a fallback to system ffmpeg. Runs with no manual install, locally and on Streamlit Cloud. |
| Wanted per-segment durations via **ffprobe** (also absent). | Dropped ffprobe entirely — use fixed-window split offsets (`i * SEGMENT_SECONDS`). Accurate enough for citations. |
| **pip install read-timeouts** from files.pythonhosted.org (large torch wheel; flaky sandbox network). | Retried with `--timeout 300 --retries 6`; resumed from cache and completed. `pip check` clean. |
| **Groq key validation failed** (connection error) from the sandbox. | Sandbox network blocks Groq specifically (pip/Groq blocked, YouTube reachable). Real transcription must be validated by the user locally. |
| **`timeout` command missing** on macOS (used to bound a download). | Used yt-dlp's own `socket_timeout` option instead. |
| **Security incident:** user dropped `apikey.txt` containing REAL Anthropic + OpenAI keys (neither is a Groq key). | Did not print values; moved to gitignored `.env`; deleted the plaintext file; advised rotating both keys. CourseLens needs a Groq `gsk_` key. |

### Verified (without a Groq key)
- `py_compile` all 7 modules ✅
- Offline unit test of `merge_segments_into_chunks` (timestamps preserved, empty
  segments skipped, char budget respected) ✅
- Full `pip install` + `pip check` coherent ✅
- Bundled ffmpeg 7.1 works; real convert + split on synthetic audio → correct
  0/5/10s offsets ✅
- All backend imports incl. embeddings + Chroma ✅

### Outstanding / carried forward
- **End-to-end transcription + answer** needs the user's Groq key — not runnable in
  the sandbox. First thing to confirm when the user runs locally.
- Frozen dep versions: groq 0.37.1, yt-dlp 2026.6.9, imageio-ffmpeg 0.6.0.
- No `git init` yet (user hasn't asked).

---

<!-- Template for future entries:
## V{n} — {title}  ·  {date}  ·  {status}
**Goal:**
### Steps performed
### Problems encountered & resolutions
### Verified
### Outstanding / carried forward
-->
