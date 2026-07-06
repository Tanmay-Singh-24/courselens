# CourseLens — Eval Results

| Metric | grader ON | grader OFF |
|---|---|---|
| Retrieval hit-rate@5 | 100% | 100% |
| Answer keyword match | 100% | 100% |
| Groundedness (LLM-judge) | 100% | 100% |
| Refusal accuracy (off-corpus) | 100% | 100% |
| Corpus questions (n) | 23 | 23 |

### Per-modality hit-rate@5

| Modality | grader ON | grader OFF |
|---|---|---|
| audio | 100% (n=16) | 100% (n=16) |
| pdf_figure | 100% (n=3) | 100% (n=3) |
| pdf_text | 100% (n=4) | 100% (n=4) |

### Ablation — corrective-RAG grader
- Groundedness: **100% → 100%** (+0 pts) with the grader on.
- Off-corpus refusal accuracy: **100% → 100%**.
