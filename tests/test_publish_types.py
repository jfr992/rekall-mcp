import pytest

from memory.publish_types import Bundle, Concept


def test_bundle_holds_tree_files_stats():
    b = Bundle(tree=["a/b.md"], files={"a/b.md": "x"}, stats={"concepts": 1})
    assert b.tree == ["a/b.md"]
    assert b.files["a/b.md"] == "x"
    assert b.stats["concepts"] == 1


def test_concept_defaults_empty():
    c = Concept(path="t/x.md", frontmatter={"type": "note"}, body="hello")
    assert c.frontmatter["type"] == "note"


def test_get_renderer_unknown_raises():
    from memory.renderers import get_renderer

    with pytest.raises(ValueError):
        get_renderer("nonesuch")
