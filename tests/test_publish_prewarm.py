import time
from memory.publish import prewarm_synthesis, cluster_key


def _mem(mid, content):
    return {"memory_id": mid, "type": "learning", "content": content}


def test_prewarm_runs_concurrently_and_populates_cache():
    def slow_synth(cluster):
        time.sleep(0.2)
        return (f"t-{cluster[0]['memory_id']}", "brief")

    clusters = [[_mem(str(i), f"content {i}")] for i in range(8)]
    cache: dict = {}
    t = time.time()
    prewarm_synthesis(clusters, cache, slow_synth, workers=8)
    dt = time.time() - t
    # 8 clusters × 0.2s sequential = 1.6s; concurrent should be well under 1s
    assert dt < 1.0
    assert len(cache) == 8
    assert cache[cluster_key(clusters[0])][0] == "t-0"


def test_prewarm_tolerates_synth_errors():
    def boom(cluster):
        raise RuntimeError("down")

    clusters = [[_mem("a", "x")]]
    cache: dict = {}
    prewarm_synthesis(clusters, cache, boom, workers=2)
    # errored clusters simply aren't cached; build falls back to raw later
    assert cache == {}


def test_prewarm_noop_when_no_synth():
    clusters = [[_mem("a", "x")]]
    cache: dict = {}
    prewarm_synthesis(clusters, cache, None, workers=4)
    assert cache == {}
