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


def test_manager_saves_embedding_text_and_uses_it_for_vector(tmp_path, monkeypatch):
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

    assert captured["encoded_text"].startswith("Project byte-edge.")
    assert captured["payload"]["embedding_text"] == captured["encoded_text"]
    assert "Longhorn" in captured["payload"]["entities"]


def test_manager_uses_embedding_text_for_duplicate_search_before_save(tmp_path, monkeypatch):
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

    assert events[0][0] == "encode"
    assert events[0][1].startswith("Project byte-edge.")
    assert events[1] == ("search", events[0][1])
    assert events[2] == ("encode", events[0][1])
    assert events[3][0] == "save"
    assert captured["payload"]["content"] == "Longhorn settings matter"
