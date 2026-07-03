import yaml


def test_doctor_detects_yaml_qdrant_drift(tmp_path):
    from memory.doctor import run_memory_doctor

    project_dir = tmp_path / "byte-edge"
    project_dir.mkdir()
    (project_dir / "2026-07-03.yaml").write_text(
        yaml.dump(
            {
                "date": "2026-07-03",
                "learnings": [
                    {"id": "m_yaml_only", "content": "Only in YAML", "project": "byte-edge"}
                ],
            }
        )
    )

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [{"memory_id": "m_qdrant_only", "content": "Only in Qdrant", "project": "byte-edge"}]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 0, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 0},
        },
    )()

    report = run_memory_doctor(manager, project="byte-edge")

    assert report["status"] == "degraded"
    assert "m_yaml_only" in report["missing_from_qdrant"]
    assert "m_qdrant_only" in report["missing_from_yaml"]


def test_doctor_flags_missing_provenance(tmp_path):
    from memory.doctor import run_memory_doctor

    class Store:
        def scroll(self, filters=None, limit=10000, with_vectors=False):
            return [{"memory_id": "m1", "content": "No provenance", "project": "rekall-mcp"}]

    manager = type(
        "Manager",
        (),
        {
            "memory_dir": tmp_path,
            "store": Store(),
            "knowledge_graph": type(
                "Graph", (), {"stats": lambda self: {"nodes": 1, "edges": 0, "relations": {}}}
            )(),
            "vector_health": lambda self: {"sampled": 1, "zero_vectors": 0},
        },
    )()

    report = run_memory_doctor(manager)

    assert report["status"] == "degraded"
    assert report["provenance"]["missing_agent"] == 1
    assert report["provenance"]["missing_source_tool"] == 1
