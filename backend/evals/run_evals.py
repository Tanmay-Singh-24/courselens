"""CourseLens — V4 evaluation harness.

Turns the known test corpus into real numbers. On a hand-labeled gold set it
measures three things and runs the grader ON-vs-OFF ablation:

  • retrieval hit-rate@5  — deterministic: is the correct source in the top-5
                            retrieved chunks? (timestamp overlap ±60s / page ±1)
  • answer keyword match  — cheap correctness sanity check
  • groundedness          — LLM-as-judge: is every claim supported by the context?
                            (imperfect — the judge is itself an LLM — but standard)

Off-corpus questions check the refusal path (does the grader decline instead of
hallucinating?).

PREREQS
  1. Ingest the test corpus first so the collection is populated:
         python -m backend.evals.run_evals --ingest
     (or upload test_dataset/audio/*.mp3 and test_dataset/slides/*.pdf in the app)
  2. Set GROQ_API_KEY (.env).

RUN
     python -m backend.evals.run_evals            # both modes, cached
     python -m backend.evals.run_evals --grader on
     python -m backend.evals.run_evals --no-cache

Results are printed and written to backend/evals/results.md (paste into README).
"""
import argparse
import hashlib
import json
import os
from collections import defaultdict

import groq
from langchain_core.messages import HumanMessage, SystemMessage

from backend import graph as G
from backend.config import TOP_K
from backend.store import similarity_search

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, "gold.jsonl")
CACHE = os.path.join(HERE, ".cache.json")
RESULTS = os.path.join(HERE, "results.md")

JUDGE_PROMPT = (
    "You are a strict groundedness judge. Given CONTEXT and an ANSWER, decide whether "
    "EVERY factual claim in the answer is supported by the context. If any claim is "
    "unsupported, it is NOT grounded. A refusal ('I couldn't find...') counts as "
    "grounded. Respond with ONLY a JSON object: "
    '{"grounded": true or false, "reason": "<one short sentence>"}'
)


# ── PURE HELPERS (unit-tested offline) ───────────────────────────────────────
def _retrieval_hit(metas, gold):
    """Is the expected source present in the retrieved chunk metadatas, with the
    timestamp/page landing where we expect?"""
    name = gold["expected_source_name"]
    stype = gold["expected_source_type"]
    for m in metas:
        if m.get("source_name") != name:
            continue
        if stype in ("audio", "youtube"):
            ts = m.get("ts_start")
            te = m.get("ts_end", ts)
            if ts is None:
                continue
            if te is None:
                te = ts
            lo, hi = gold["expected_ts_range"]
            if ts <= hi + 60 and te >= lo - 60:   # overlap within ±60s tolerance
                return True
        else:  # pdf_text / pdf_figure — require the right stream and near page
            if m.get("source_type") != stype:
                continue
            pg = m.get("page")
            if pg is not None and abs(pg - gold["expected_page"]) <= 1:
                return True
    return False


def _keyword_hit(answer, keywords):
    """True if ANY expected keyword appears in the answer (case-insensitive)."""
    a = answer.lower()
    return any(k.lower() in a for k in (keywords or []))


def _is_refusal(answer):
    return "couldn't find anything in your materials" in answer.lower()


def _parse_groundedness(raw):
    """Parse the judge's JSON. Conservative: unparseable → not grounded."""
    try:
        import re
        obj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return bool(obj["grounded"])
    except Exception:
        return False


def _pct(xs):
    xs = list(xs)
    return 100.0 * sum(1 for x in xs if x) / len(xs) if xs else 0.0


def _summarize(rows):
    """Aggregate row dicts into overall + per-modality metrics."""
    corpus = [r for r in rows if not r.get("refusal_case")]
    refusals = [r for r in rows if r.get("refusal_case")]
    by_mod = defaultdict(list)
    for r in corpus:
        by_mod[r["modality"]].append(r)
    out = {
        "n": len(corpus),
        "hit_rate": _pct(r["hit"] for r in corpus),
        "keyword": _pct(r["kw"] for r in corpus),
        "grounded": _pct(r["grounded"] for r in corpus),
        "refusal_acc": _pct(r["refusal"] for r in refusals) if refusals else None,
        "per_modality": {
            mod: {
                "n": len(rs),
                "hit_rate": _pct(r["hit"] for r in rs),
                "keyword": _pct(r["kw"] for r in rs),
                "grounded": _pct(r["grounded"] for r in rs),
            }
            for mod, rs in sorted(by_mod.items())
        },
    }
    return out


def _markdown(summaries):
    """summaries: {mode_label: summary_dict}. Build a comparison markdown report."""
    lines = ["# CourseLens — Eval Results", ""]
    lines.append("| Metric | " + " | ".join(summaries) + " |")
    lines.append("|---|" + "---|" * len(summaries))

    def row(label, key, fmt="{:.0f}%"):
        cells = []
        for s in summaries.values():
            v = s.get(key)
            cells.append("—" if v is None else fmt.format(v))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    row("Retrieval hit-rate@5", "hit_rate")
    row("Answer keyword match", "keyword")
    row("Groundedness (LLM-judge)", "grounded")
    row("Refusal accuracy (off-corpus)", "refusal_acc")
    lines.append(f"| Corpus questions (n) | " +
                 " | ".join(str(s["n"]) for s in summaries.values()) + " |")

    # Per-modality (use the first mode's breakdown for the modality list).
    lines += ["", "### Per-modality hit-rate@5", "",
              "| Modality | " + " | ".join(summaries) + " |",
              "|---|" + "---|" * len(summaries)]
    mods = sorted({m for s in summaries.values() for m in s["per_modality"]})
    for mod in mods:
        cells = []
        for s in summaries.values():
            pm = s["per_modality"].get(mod)
            cells.append("—" if not pm else f"{pm['hit_rate']:.0f}% (n={pm['n']})")
        lines.append(f"| {mod} | " + " | ".join(cells) + " |")

    # Ablation callout.
    if "grader ON" in summaries and "grader OFF" in summaries:
        on, off = summaries["grader ON"], summaries["grader OFF"]
        lines += ["", "### Ablation — corrective-RAG grader",
                  f"- Groundedness: **{off['grounded']:.0f}% → {on['grounded']:.0f}%** "
                  f"({on['grounded']-off['grounded']:+.0f} pts) with the grader on.",
                  f"- Off-corpus refusal accuracy: "
                  f"**{(off['refusal_acc'] or 0):.0f}% → {(on['refusal_acc'] or 0):.0f}%**."]
    lines.append("")
    return "\n".join(lines)


# ── CACHE ────────────────────────────────────────────────────────────────────
def _load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE))
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    json.dump(cache, open(CACHE, "w"))


def _ck(mode, tag, question):
    return hashlib.sha1(f"{mode}|{tag}|{question}".encode()).hexdigest()[:16]


# ── RUN ──────────────────────────────────────────────────────────────────────
def _load_gold():
    with open(GOLD) as f:
        return [json.loads(line) for line in f if line.strip()]


def _judge_groundedness(answer, context):
    raw = G.llm.invoke([
        SystemMessage(content=JUDGE_PROMPT),
        HumanMessage(content=f"CONTEXT:\n{context[:2000]}\n\nANSWER:\n{answer}"),
    ]).content
    return _parse_groundedness(raw)


def run(grader_on, cache, use_cache=True):
    """Evaluate one mode. Returns (summary, interrupted). A Groq rate limit stops
    the pass gracefully with partial results rather than crashing — cached progress
    is saved, so a later re-run resumes cheaply."""
    mode = "on" if grader_on else "off"
    g = G.build_graph(grader_on)
    rows = []
    interrupted = False
    for gold in _load_gold():
        q = gold["question"]
        print(f"  {gold['id']:5s} ", end="", flush=True)   # live progress
        try:
            # Answer via the graph (cached — this is the expensive LLM part).
            rk = _ck(mode, "resp", q)
            if use_cache and rk in cache:
                resp = cache[rk]
            else:
                r = G.get_response(q, thread_id=f"eval-{rk}", graph_override=g)
                resp = {"answer": r["answer"], "context": r["context"]}
                cache[rk] = resp
                _save_cache(cache)
            answer, context = resp["answer"], resp["context"]

            if gold.get("expected") == "refusal":
                refused = _is_refusal(answer)
                print(f"refusal={'✓' if refused else '✗'}", flush=True)
                rows.append({"id": gold["id"], "refusal_case": True, "refusal": refused})
                continue

            # Retrieval hit-rate is deterministic and grader-independent.
            metas = [d.metadata for d in similarity_search(q, k=TOP_K)]
            hit = _retrieval_hit(metas, gold)
            kw = _keyword_hit(answer, gold.get("answer_keywords"))

            gk = _ck(mode, "gnd", q)
            if use_cache and gk in cache:
                grounded = cache[gk]
            else:
                grounded = _judge_groundedness(answer, context)
                cache[gk] = grounded
                _save_cache(cache)

            print(f"hit={'✓' if hit else '✗'} kw={'✓' if kw else '✗'} "
                  f"grounded={'✓' if grounded else '✗'}", flush=True)
            rows.append({"id": gold["id"], "modality": gold["expected_source_type"],
                         "hit": hit, "kw": kw, "grounded": grounded})
        except groq.RateLimitError as e:
            print("\n  ⚠️  Groq rate limit reached — stopping this pass with partial "
                  "results.\n      Progress is cached; re-run to resume when it resets.",
                  flush=True)
            print(f"      {str(e)[:110]}", flush=True)
            interrupted = True
            break
    return _summarize(rows), interrupted


def _ingest_test_corpus():
    """Convenience: ingest test_dataset audio + slides so the harness has data."""
    from backend.ingest.dispatch import ingest_file
    root = os.path.join(G.__file__.rsplit("backend", 1)[0], "test_dataset")
    files = [os.path.join(root, "audio", "lecture_graph_algorithms.mp3"),
             os.path.join(root, "audio", "me_at_the_zoo.mp3"),
             os.path.join(root, "audio", "lecture_data_structures.mp3"),
             os.path.join(root, "slides", "sorting_algorithms_slides.pdf"),
             os.path.join(root, "slides", "data_structures_slides.pdf")]
    for f in files:
        if os.path.exists(f):
            print(f"ingesting {os.path.basename(f)} …")
            n = ingest_file(f, os.path.basename(f))
            print(f"  {n} chunks")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grader", choices=["on", "off", "both"], default="both")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--ingest", action="store_true",
                    help="ingest the test corpus first, then evaluate")
    args = ap.parse_args()

    if args.ingest:
        _ingest_test_corpus()

    cache = _load_cache()
    use_cache = not args.no_cache
    modes = {"on": [True], "off": [False], "both": [True, False]}[args.grader]

    summaries = {}
    interrupted_any = False
    for grader_on in modes:
        label = "grader ON" if grader_on else "grader OFF"
        print(f"\n=== Evaluating: {label} ===")
        summaries[label], interrupted = run(grader_on, cache, use_cache)
        interrupted_any = interrupted_any or interrupted

    report = _markdown(summaries)
    if interrupted_any:
        report += ("\n> ⚠️ A pass stopped early at the Groq daily token limit, so some "
                   "numbers are partial. Re-run when the limit resets — the cache makes "
                   "it cheap (completed questions are reused).\n")
    with open(RESULTS, "w") as f:
        f.write(report)
    print("\n" + report)
    print(f"\nWritten to {RESULTS}")


if __name__ == "__main__":
    main()
