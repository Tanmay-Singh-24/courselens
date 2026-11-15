"""Course Map — concept parsing and pure graph assembly."""
import backend.concept_map as CM


def test_parse_concepts_clean_and_embedded():
    assert CM._parse_concepts('["Dijkstra", "priority queue"]') == ["Dijkstra", "priority queue"]
    assert CM._parse_concepts('sure: ["A", "B"] done') == ["A", "B"]


def test_parse_concepts_garbage_is_empty():
    assert CM._parse_concepts("not json") == []


def test_assemble_graph_links_cooccurring_concepts():
    per_source = {
        "lectureA": ["Dijkstra", "priority queue", "BFS"],
        "slidesB": ["priority queue", "sorting"],
    }
    nodes, edges, cmap = CM.assemble_graph(per_source)
    assert sorted(n["id"] for n in nodes) == ["BFS", "Dijkstra", "priority queue", "sorting"]
    # 3 pairs from lectureA + 1 pair from slidesB
    assert len(edges) == 4
    assert ["priority queue", "sorting"] in edges
    assert cmap["priority queue"] == ["lectureA", "slidesB"]   # spans both sources


def test_node_cap_avoids_hairball():
    nodes, _, _ = CM.assemble_graph({"s": [f"c{i}" for i in range(60)]}, max_concepts=40)
    assert len(nodes) == 40


def test_relate_concepts_links_similar_and_drops_weak():
    labels = ["queue", "priority queue", "elephant"]
    vectors = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]
    links = CM.relate_concepts(labels, vectors, k=2, floor=0.3)
    pairs = {(a, b) for a, b, _ in links}
    assert ("priority queue", "queue") in pairs        # sorted pair, near-identical vectors
    assert ("elephant", "queue") not in pairs           # orthogonal -> below the floor
    assert links[0][2] >= links[-1][2]                  # strongest first


def test_relate_concepts_is_undirected_and_deduplicated():
    links = CM.relate_concepts(["a", "b"], [[1.0, 0.0], [1.0, 0.0]], k=3)
    assert links == [("a", "b", 1.0)]


def test_relate_concepts_survives_zero_vector():
    # A zero vector must not divide by zero; it simply relates to nothing.
    assert CM.relate_concepts(["a", "b"], [[0.0, 0.0], [1.0, 0.0]]) == []
