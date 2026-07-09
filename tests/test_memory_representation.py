def test_extract_entities_preserves_software_identifiers():
    from memory.representation import extract_entities

    entities = extract_entities(
        "byte-edge-core failed Helm rollout for Longhorn on k3s; flag was stable_hash_id and TOPE-123."
    )

    assert "byte-edge-core" in entities
    assert "Longhorn" in entities
    assert "k3s" in entities
    assert "stable_hash_id" in entities
    assert "TOPE-123" in entities


def test_extract_entities_filters_lowercase_boilerplate_stopwords():
    from memory.representation import extract_entities

    entities = extract_entities("project type claim this that Longhorn")

    assert "project" not in entities
    assert "type" not in entities
    assert "claim" not in entities
    assert "this" not in entities
    assert "that" not in entities
    assert entities == ["Longhorn"]


def test_extract_entities_does_not_capture_plain_english_words():
    from memory.representation import extract_entities

    entities = extract_entities("Decided to use PostgreSQL for its JSON support")

    assert entities == ["PostgreSQL", "JSON"]


def test_build_embedding_text_adds_scope_and_entities():
    from memory.representation import build_embedding_text

    text = build_embedding_text(
        "Two-node clusters need Longhorn replica settings.",
        {
            "project": "byte-edge",
            "type": "learning",
            "tier": "semantic",
            "repo_name": "byte-edge",
            "source_tool": "rekall-observe",
        },
    )

    assert text.startswith("Project byte-edge.")
    assert "Type learning." in text
    assert "Tier semantic." in text
    assert "Entities:" in text
    assert "Longhorn" in text
    assert "Claim: Two-node clusters need Longhorn replica settings." in text


def test_manager_encodes_raw_content_for_dense_vector(tmp_path, monkeypatch):
    """Dense vector = encode(content); embedding_text stays for BM25 + payload (repr v2)."""
    from memory.manager import MemoryManager

    captured = {}

    class Store:
        def search(self, *args, **kwargs):
            return []

        def save(self, **kwargs):
            captured.update(kwargs)

    class Embedder:
        def encode(self, text):
            captured["encoded_text"] = text
            return [0.1] * 384

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    manager._store = Store()
    manager._embedder = Embedder()
    manager._knowledge_graph = type(
        "Graph",
        (),
        {"add_node": lambda *args, **kwargs: None, "save": lambda *args, **kwargs: None},
    )()
    monkeypatch.setattr(
        "memory.manager.auto_link",
        lambda **kwargs: type("R", (), {"edges_created": 0, "relations": {}})(),
    )

    manager.save("Longhorn settings matter", type="learning", project="byte-edge")

    assert captured["encoded_text"] == "Longhorn settings matter"
    assert captured["payload"]["embedding_text"].startswith("Project byte-edge.")
    # BM25 sparse leg keeps the enriched representation
    assert captured["content"] == captured["payload"]["embedding_text"]
    assert "Longhorn" in captured["payload"]["entities"]
    assert captured["payload"]["repr_version"] == 2


def test_manager_uses_raw_content_for_duplicate_search_before_save(tmp_path, monkeypatch):
    """Dedupe dense leg queries with raw content first (matches stored repr v2
    vectors); embedding_text runs second for the BM25 leg + legacy vectors."""
    from memory.manager import MemoryManager

    events = []
    captured = {}

    class Store:
        def search(self, *args, **kwargs):
            events.append(("search", kwargs["query_text"]))
            return []

        def save(self, **kwargs):
            events.append(("save", kwargs["content"]))
            captured.update(kwargs)

    class Embedder:
        def encode(self, text):
            events.append(("encode", text))
            return [0.1] * 384

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    manager._store = Store()
    manager._embedder = Embedder()
    manager._knowledge_graph = type(
        "Graph",
        (),
        {"add_node": lambda *args, **kwargs: None, "save": lambda *args, **kwargs: None},
    )()
    monkeypatch.setattr(
        "memory.manager.auto_link",
        lambda **kwargs: type("R", (), {"edges_created": 0, "relations": {}})(),
    )

    manager.save("Longhorn settings matter", type="learning", project="byte-edge")

    assert events[0] == ("encode", "Longhorn settings matter")
    assert events[1] == ("search", "Longhorn settings matter")
    assert events[2][0] == "encode"
    assert events[2][1].startswith("Project byte-edge.")
    assert events[3] == ("search", events[2][1])
    assert events[4] == ("encode", "Longhorn settings matter")
    assert events[5][0] == "save"
    assert captured["payload"]["content"] == "Longhorn settings matter"


def test_duplicate_search_falls_back_to_embedding_text_for_legacy_vectors(tmp_path):
    """Pre-migration points were encoded from embedding_text; the second dedupe
    pass keeps catching them (and feeds the BM25 leg the enriched text)."""
    from memory.manager import MemoryManager

    queries = []

    class Store:
        def search(self, *args, **kwargs):
            queries.append(kwargs["query_text"])
            if kwargs["query_text"] == "Project byte-edge. Claim: Longhorn settings matter":
                return [{"memory_id": "legacy", "content": "Longhorn settings matter"}]
            return []

    class Embedder:
        def encode(self, text):
            return [0.1] * 384

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    manager._store = Store()
    manager._embedder = Embedder()

    memory_id = manager._find_duplicate_memory_id(
        content="Longhorn settings matter",
        query_text="Project byte-edge. Claim: Longhorn settings matter",
        project="byte-edge",
        memory_type="learning",
    )

    assert memory_id == "legacy"
    assert queries == [
        "Longhorn settings matter",
        "Project byte-edge. Claim: Longhorn settings matter",
    ]
