import yaml

from memory.publish_types import Concept
from memory.renderers.okf import OkfRenderer, slugify


def _c(path, mtype="runbook", body="hello"):
    return Concept(path=path, frontmatter={"type": mtype, "title": "T"}, body=body)


def test_every_concept_has_nonempty_type_frontmatter():
    b = OkfRenderer().render([_c("byte-edge/runbooks/x.md")])
    content = b.files["byte-edge/runbooks/x.md"]
    assert content.startswith("---\n")
    fm = yaml.safe_load(content.split("---\n")[1])
    assert fm["type"] == "runbook"


def test_reserved_names_generate_index():
    b = OkfRenderer().render([_c("a/b.md")])
    assert "a/index.md" in b.files or "index.md" in b.files


def test_slugify_stable_and_safe():
    assert slugify("KubeVirt namespace recovery!") == "kubevirt-namespace-recovery"
    assert slugify("a/b c") == "a-b-c"


def test_tree_lists_all_files_sorted():
    b = OkfRenderer().render([_c("z/a.md"), _c("a/b.md")])
    assert b.tree == sorted(b.tree)
    assert "z/a.md" in b.tree and "a/b.md" in b.tree


def test_stats_reports_concept_count():
    b = OkfRenderer().render([_c("a/b.md"), _c("a/c.md")])
    assert b.stats["concepts"] == 2
