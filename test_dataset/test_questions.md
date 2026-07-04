# CourseLens — Test Questions (gold answers)

Ask these in the chat after ingesting the matching source. Each row lists the
expected answer and the timestamp the citation *should* point to, so you can
verify both the answer **and** that the deep-link lands on the right moment.

---

## Source A — `audio/lecture_graph_algorithms.mp3` (upload it)

A 89-second synthetic lecture with **known** content. Topic timeline:

| Topic | Starts at |
|---|---|
| Intro (what a graph is) | 0:00 |
| Traversal (BFS / DFS) | 0:17 |
| Dijkstra | 0:38 |
| Bellman-Ford | 0:56 |
| Minimum spanning trees (Kruskal / Prim) | 1:10 |

### Questions

| # | Question | Expected answer | Citation ≈ |
|---|---|---|---|
| 1 | What is the time complexity of Dijkstra's algorithm? | O(E log V) | 0:38 |
| 2 | Which algorithm should I use when there are negative edge weights? | Bellman-Ford | 0:56 |
| 3 | What does breadth-first search find in an unweighted graph? | The shortest path | 0:17 |
| 4 | What is depth-first search used for? | Detecting cycles and topological sorting | 0:17 |
| 5 | What can Bellman-Ford detect, and how many times does it relax edges? | Negative-weight cycles; relaxes all edges V−1 times (O(V·E)) | 0:56 |
| 6 | Name two minimum spanning tree algorithms. | Kruskal's and Prim's | 1:10 |
| 7 | What data structure does Dijkstra use to pick the next node? | A priority queue | 0:38 |
| 8 | What is a graph made of? | Nodes (vertices) connected by edges | 0:00 |

### Special checks
- **Follow-up / memory + query-rewrite test:** ask Q1 first, then ask
  *"Why doesn't it work with negative weights?"* — "it" must resolve to Dijkstra.
  Expected: Dijkstra doesn't support negative edge weights (cite ≈ 0:38).
- **Grounding test (off-corpus):** ask *"What is the capital of France?"*
  Expected (V3): the corrective-RAG grader marks the context irrelevant and the
  answer becomes *"I couldn't find anything in your materials… your library covers: …"*
  — **not** "Paris." Open the **Retrieval check** expander to see the grader's
  verdict(s). (Toggle `ENABLE_GRADER=0` to see the old ungraded behavior.)

---

## Source B — `audio/me_at_the_zoo.mp3` (upload it) — or the YouTube link

Real 19-second clip ("Me at the zoo"). Known content:

| # | Question | Expected answer | Citation ≈ |
|---|---|---|---|
| 1 | What animal is the speaker standing in front of? | Elephants | 0:00 |
| 2 | What does the speaker say is cool about them? | Their really long trunks | 0:10 |

---

## Source C — `slides/sorting_algorithms_slides.pdf` (upload it) — V2

A 2-page slide deck: text about sorting algorithms **plus an embedded bar chart**
(and a tiny logo that should be *filtered out*, not captioned).

### Text questions (source_type = pdf_text)
| # | Question | Expected answer | Citation ≈ |
|---|---|---|---|
| 1 | What is the worst-case time complexity of QuickSort? | O(n²) | p.1 |
| 2 | Which sorting algorithm is stable? | MergeSort | p.1 |
| 3 | When should I use MergeSort? | When stability matters | p.2 |

### Figure question (source_type = pdf_figure — tests vision caption + inline image)
| # | Question | Expected answer | Citation ≈ |
|---|---|---|---|
| 4 | According to the runtime chart, which algorithm is slowest? | BubbleSort (≈40 ms) | Figure, p.1 |

**Expected UI:** Q4's **Sources** panel shows the actual bar-chart image inline,
labeled *"…— Figure (p.1)"*. (Caption quality depends on the vision model; the
real image is always shown so you can verify.)

---

## Source D — `audio/lecture_data_structures.mp3` (upload it)

A 48-second known-answer lecture. Timeline: arrays 0:00 · linked lists 0:10 ·
hash tables 0:22 · stacks & queues 0:31 · trees 0:40.

| # | Question | Expected answer | Citation ≈ |
|---|---|---|---|
| D1 | Time complexity of random access in an array? | O(1) / constant | 0:00 |
| D2 | How are hash-table collisions handled? | Chaining | 0:22 |
| D3 | What order does a stack follow? | LIFO (last in first out) | 0:31 |
| D4 | What order does a queue follow? | FIFO (first in first out) | 0:31 |
| D5 | Search complexity of a balanced BST? | O(log n) | 0:40 |
| D6 | Access an element by position in a linked list? | O(n) / linear | 0:10 |

## Source E — `slides/data_structures_slides.pdf` (upload it) — two figures

Page 1: overview text + a **memory bar chart**. Page 2: an **access-time table**
(both are real embedded images the vision model captions).

| # | Question | Expected answer | Citation ≈ |
|---|---|---|---|
| E1 | Which structure uses the most memory (per the chart)? | HashTable (30 MB) | Figure, p.1 |
| E2 | Access complexity of a linked list (per the table)? | O(n) | Figure, p.2 |
| E3 | Which structure makes insertion cheap (per the overview)? | Linked lists | p.1 (text) |

---

## Cross-source check (after ingesting several sources)
- Ask *"What do my materials cover?"* → the answer should reference **both** the
  graph-algorithms lecture and the zoo clip, showing retrieval spans sources.
- Ask a graph question → the citation should point to Source A, **not** B,
  confirming retrieval picks the right source among several.
