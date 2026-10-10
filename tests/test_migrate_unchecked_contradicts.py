"""Relabel of model-unchecked contradicts edges. Tmp graphs only — never production."""

from __future__ import annotations

from scripts.migrate_unchecked_contradicts import main, migrate

from memory.knowledge_graph import KnowledgeGraph


def _write_graph(tmp_path) -> None:
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    for node in ("a", "b", "c", "d"):
        kg.add_node(node)
    kg.add_edge("a", "b", "contradicts", 0.7)
    kg.add_edge("a", "c", "contradicts", 0.8, llm_refined=True)
    kg.add_edge("a", "d", "related_to", 0.6)
    kg._dirty = True
    kg.save()


def test_dry_run_counts_and_changes_nothing(tmp_path):
    _write_graph(tmp_path)
    before = (tmp_path / "_graph.json").read_text()

    result = migrate(KnowledgeGraph(tmp_path / "_graph.json"))

    assert result == {"applied": False, "total": 2, "relabeled": 1, "kept": 1}
    assert (tmp_path / "_graph.json").read_text() == before
    assert list(tmp_path.glob("_graph.json.bak-*")) == []


def test_apply_relabels_only_unchecked_with_backup_and_is_idempotent(tmp_path, monkeypatch, capsys):
    _write_graph(tmp_path)
    original = (tmp_path / "_graph.json").read_text()
    monkeypatch.setenv("MEMORY_STORAGE_PATH", str(tmp_path))

    assert main(["--apply", "--force"]) == 0

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    unchecked = kg._graph.edges["a", "b"]
    assert unchecked["relation"] == "related_to"
    assert unchecked["weight"] == 0.7
    assert unchecked["auto"] is True
    assert unchecked["migrated_from"] == "contradicts"
    assert kg._graph.edges["a", "c"]["relation"] == "contradicts"
    assert kg._graph.edges["a", "d"]["relation"] == "related_to"
    backups = list(tmp_path.glob("_graph.json.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    assert str(backups[0]) in capsys.readouterr().out

    after_first = (tmp_path / "_graph.json").read_text()
    assert main(["--apply", "--force"]) == 0
    assert (tmp_path / "_graph.json").read_text() == after_first
    assert len(list(tmp_path.glob("_graph.json.bak-*"))) == 1


def test_apply_refused_when_server_reachable(tmp_path, monkeypatch):
    _write_graph(tmp_path)
    monkeypatch.setenv("MEMORY_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("scripts.migrate_unchecked_contradicts._server_reachable", lambda: True)
    before = (tmp_path / "_graph.json").read_text()

    assert main(["--apply"]) == 1
    assert (tmp_path / "_graph.json").read_text() == before
