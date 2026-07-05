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
