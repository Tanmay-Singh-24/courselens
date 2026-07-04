# CourseLens — Eval Results

> This file is **auto-generated** — it's overwritten each time you run
> `python -m backend.evals.run_evals`. The table below is the last *complete* result;
> regenerate for the current gold set (needs a Groq key + tokens).

Last complete run (grader ON, initial 14-question set + off-corpus):

| Metric | grader ON | grader OFF |
|---|---|---|
| Retrieval hit-rate@5 | **100%** | 100% |
| Groundedness (LLM-judge) | **100%** | 100% |
| Off-corpus refusal accuracy | **100%** | **0%** |

**Headline / ablation:** the corrective-RAG grader takes off-corpus refusal accuracy
from **0% → 100%** — without it, questions the course can't answer get answered anyway.

The gold set has since expanded to **26 questions** (23 corpus: 16 audio / 4 slide-text
/ 3 figure, + 3 off-corpus). Regenerate the full table with:

```bash
rm backend/evals/.cache.json          # if the corpus changed
python -m backend.evals.run_evals --ingest
```
