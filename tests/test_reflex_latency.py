"""Reflex route latency against a real Qdrant instance.

Requires a real Qdrant at localhost:6334.
"""

import time
from uuid import uuid4

import pytest

from memory.manager import MemoryManager

pytestmark = pytest.mark.integration


@pytest.fixture
def integration_manager(tmp_path):
    """MemoryManager wired to the test Qdrant on :6334 with an isolated collection."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    collection_name = f"rekall_test_{uuid4().hex[:12]}"

    mgr = MemoryManager(
        memory_dir=memory_dir,
        qdrant_url="http://localhost:6334",
    )
    mgr.COLLECTION = collection_name

    yield mgr

    try:
        mgr.store.delete_collection()
    except Exception:
        pass


def test_reflex_completes_well_under_hook_curl_ceiling(integration_manager):
    mgr = integration_manager
    project = "rekall-it"

    for content in [
        "Always tarball ~/.claude/memory before running terraform destroy",
        "kubectl delete pods should be scoped to a namespace, never cluster-wide",
        "Rotate API keys through the secret manager, never hardcode them",
        "helm uninstall on production requires a change ticket reference",
        "prune old snapshots only after confirming an off-site backup exists",
    ]:
        mgr.save(content, type="learning", project=project, source_tool="test")

    start = time.perf_counter()
    packet = mgr.reflex(
        text="running terraform destroy and kubectl delete to prune old resources",
        project=project,
        limit=4,
    )
    elapsed = time.perf_counter() - start

    assert isinstance(packet["memories"], list)
    # Hook's curl ceiling is 1s (--max-time 1); 0.8s leaves headroom to avoid
    # CI flake while still catching a regression back to per-cue recall calls.
    assert elapsed < 0.8, f"reflex took {elapsed:.3f}s, expected < 0.8s"
