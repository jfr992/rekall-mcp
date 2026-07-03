def test_capsule_groups_project_familiarity():
    from memory.capsules import build_project_capsule

    class Store:
        def scroll(self, filters=None, limit=300):
            assert filters == {"project": "byte-edge"}
            assert limit == 2000
            return [
                {
                    "memory_id": "m1",
                    "type": "decision",
                    "tier": "semantic",
                    "date": "2026-07-01",
                    "content": "Use Longhorn tuned settings for two-node k3s.",
                    "entities": ["Longhorn", "k3s"],
                },
                {
                    "memory_id": "m2",
                    "type": "learning",
                    "tier": "episodic",
                    "date": "2026-07-02",
                    "content": "Helm rollout failed until BSO namespace policy was fixed.",
                    "entities": ["Helm", "BSO"],
                },
                {
                    "memory_id": "m3",
                    "type": "requirement",
                    "tier": "semantic",
                    "date": "2026-07-02",
                    "content": "Back up live Claude files before editing hooks.",
                    "entities": ["Claude"],
                },
            ]

    manager = type(
        "Manager",
        (),
        {
            "store": Store(),
            "knowledge_graph": type(
                "Graph",
                (),
                {
                    "get_importance": lambda self, memory_id: {
                        "m1": 0.9,
                        "m2": 0.5,
                        "m3": 0.8,
                    }.get(memory_id, 0.5)
                },
            )(),
        },
    )()

    capsule = build_project_capsule(manager, "byte-edge")

    assert capsule["project"] == "byte-edge"
    assert "Longhorn" in capsule["entities"]
    assert any("two-node k3s" in item["content"] for item in capsule["standing_context"])
    assert any("Back up live Claude files" in item["content"] for item in capsule["operating_rules"])


def test_capsule_scans_beyond_small_limit_for_recent_high_priority_items():
    from memory.capsules import build_project_capsule

    points = [
        {
            "memory_id": f"m{i}",
            "type": "decision",
            "tier": "semantic",
            "date": f"2026-06-{(i % 28) + 1:02d}",
            "content": f"Filler decision {i}.",
            "entities": ["Filler"],
        }
        for i in range(320)
    ]
    points[319] = {
        "memory_id": "m319",
        "type": "decision",
        "tier": "semantic",
        "date": "2026-07-02",
        "content": "Ship the high priority startup capsule fix.",
        "entities": ["Startup"],
    }

    class Store:
        def scroll(self, filters=None, limit=300):
            assert filters == {"project": "byte-edge"}
            assert limit == 2000
            return points[:limit]

    class Graph:
        def get_importance(self, memory_id):
            return 0.99 if memory_id == "m319" else 0.1

    manager = type("Manager", (), {"store": Store(), "knowledge_graph": Graph()})()

    capsule = build_project_capsule(manager, "byte-edge", limit=300)

    assert any(item["memory_id"] == "m319" for item in capsule["standing_context"])
    assert len(capsule["standing_context"]) <= 8


def test_render_project_capsule_is_thin():
    from memory.capsules import render_project_capsule

    text = render_project_capsule(
        {
            "project": "byte-edge",
            "entities": ["Longhorn", "Helm"],
            "standing_context": [{"content": "Use Longhorn tuned settings.", "date": "2026-07-01"}],
            "active_workstreams": [{"content": "Helm rollout policy.", "date": "2026-07-02"}],
            "operating_rules": [{"content": "Back up hooks before editing.", "date": "2026-07-02"}],
            "danger_zones": [{"content": "Qdrant cleanup requires backup.", "date": "2026-07-02"}],
            "open_loops": [],
        }
    )

    assert text.startswith("# Project Capsule: byte-edge")
    assert "Entities: Longhorn, Helm" in text
    assert len(text) < 2000
