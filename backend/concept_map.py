"""CourseLens — Course Map (V6).

Builds a concept graph over the ingested library: one LLM pass per source extracts
its key concepts, nodes are concepts, and edges connect concepts that co-occur in
the same source. Concepts are cached per source (keyed by content hash) so reopening
the map is free. The graph-assembly step is pure and unit-tested; only concept
extraction touches the LLM.
"""
import hashlib
import json
import os
import re
from collections import defaultdict

from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import MEDIA_DIR
from backend.store import vectorstore

CACHE_PATH = os.path.join(MEDIA_DIR, "concept_cache.json")
MAX_CONCEPTS = 40

EXTRACT_PROMPT = (
    "Extract the key technical concepts or topics from this course material. Return "
    'ONLY a JSON array of 4-8 short concept names (2-4 words each), e.g. '
    '["Dijkstra\'s algorithm", "priority queue"]. No prose, no explanations.'
)


def _llm():
    from backend.graph import llm   # lazy import (keeps this module import-light)
    return llm


def _load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            return json.load(open(CACHE_PATH))
        except Exception:
            return {}
    return {}


def _save_cache(c):
    os.makedirs(MEDIA_DIR, exist_ok=True)
    json.dump(c, open(CACHE_PATH, "w"))


def _sources_text():
    """{source_name: concatenated chunk text} for everything in the store."""
    data = vectorstore.get(include=["documents", "metadatas"])
    by = defaultdict(list)
    for doc, m in zip(data.get("documents", []), data.get("metadatas", [])):
        if m and m.get("source_name"):
            by[m["source_name"]].append(doc)
    return {s: "\n".join(t) for s, t in by.items()}


def _parse_concepts(raw):
    """Parse the LLM's JSON array of concept names; [] on any failure."""
    try:
        arr = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        return [str(x).strip() for x in arr if str(x).strip()][:8]
    except Exception:
        return []


def _extract_concepts(text):
    raw = _llm().invoke([
        SystemMessage(content=EXTRACT_PROMPT),
        HumanMessage(content=text[:4000]),
    ]).content
    return _parse_concepts(raw)


def assemble_graph(per_source, max_concepts=MAX_CONCEPTS):
    """Pure: {source: [concepts]} -> (nodes, edges, concept_sources).

    nodes: [{"id","label","sources":[...]}]; edges: [[a,b], ...] (co-occurrence in a
    source); concept_sources: {concept: [sources]}. Capped to the concepts spanning
    the most sources (keeps the map readable — avoids the hairball)."""
    concept_sources = defaultdict(set)
    for name, concepts in per_source.items():
        for c in concepts:
            concept_sources[c].add(name)

    ranked = sorted(concept_sources, key=lambda c: (-len(concept_sources[c]), c))
    kept = set(ranked[:max_concepts])

    edge_set = set()
    for concepts in per_source.values():
        cs = [c for c in concepts if c in kept]
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                edge_set.add(tuple(sorted((cs[i], cs[j]))))

    nodes = [{"id": c, "label": c, "sources": sorted(concept_sources[c])} for c in kept]
    edges = [list(e) for e in sorted(edge_set)]
    cmap = {c: sorted(concept_sources[c]) for c in kept}
    return nodes, edges, cmap


def build_concept_map(max_concepts=MAX_CONCEPTS):
    """Extract concepts per source (cached) and assemble the graph.
    Returns (nodes, edges, concept_sources)."""
    cache = _load_cache()
    per_source = {}
    changed = False
    for name, text in _sources_text().items():
        key = f"{name}:{hashlib.sha1(text.encode()).hexdigest()[:12]}"
        if key not in cache:
            cache[key] = _extract_concepts(text)
            changed = True
        per_source[name] = cache[key]
    if changed:
        _save_cache(cache)
    return assemble_graph(per_source, max_concepts)
