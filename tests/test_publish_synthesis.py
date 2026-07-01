from memory.publish import make_synthesis_fn, cluster_key


def _mem(mid, content):
    return {"memory_id": mid, "type": "learning", "content": content}


def test_synthesis_uses_llm_and_caches():
    calls = []

    def synth(cluster):
        calls.append(1)
        return ("Chart publish pipeline", "BE-496 collapsed the split into one pipeline.")

    cache = {}
    fn = make_synthesis_fn(cache, synth=synth)
    c = [_mem("a", "BE-496 stuff"), _mem("b", "pipeline stuff")]
    first = fn(c)
    second = fn(c)
    assert first == ("Chart publish pipeline", "BE-496 collapsed the split into one pipeline.")
    assert second == first
    assert len(calls) == 1  # cached


def test_synthesis_falls_back_to_slug_when_no_synth():
    fn = make_synthesis_fn({}, synth=None)
    title, brief = fn([_mem("a", "a genuinely useful long learning here")])
    assert title  # slug title
    assert brief  # falls back to raw content


def test_synthesis_falls_back_on_error():
    def boom(cluster):
        raise RuntimeError("proxy down")

    fn = make_synthesis_fn({}, synth=boom)
    title, brief = fn([_mem("a", "real content that is long enough here")])
    assert title
    assert brief


def test_cache_key_stable_across_calls():
    c = [_mem("x", "1"), _mem("y", "2")]
    assert cluster_key(c) == cluster_key(list(reversed(c)))
