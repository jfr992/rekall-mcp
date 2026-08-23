from memory.publish import cluster_key, make_synthesis_fn


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
    assert title  # slug title always present
    assert brief == ""  # empty brief signals "not synthesized"


def test_synthesis_error_is_not_cached():
    def boom(cluster):
        raise RuntimeError("proxy down")

    cache: dict = {}
    fn = make_synthesis_fn(cache, synth=boom)
    title, brief = fn([_mem("a", "real content that is long enough here")])
    assert title
    assert brief == ""
    assert cache == {}  # failures must NOT poison the cache — retried next run


def test_cache_key_stable_across_calls():
    c = [_mem("x", "1"), _mem("y", "2")]
    assert cluster_key(c) == cluster_key(list(reversed(c)))


def test_llm_complete_uses_bearer_for_oauth_tokens(monkeypatch):
    import httpx

    from memory.publish import _llm_complete

    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(headers)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "ok"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    _llm_complete("hi", model="m", base_url="https://api.anthropic.com", token="sk-ant-oat01-xyz")
    assert seen["Authorization"] == "Bearer sk-ant-oat01-xyz"
    assert seen["anthropic-beta"] == "oauth-2025-04-20"
    assert "x-api-key" not in seen


def test_llm_complete_uses_x_api_key_for_api_keys(monkeypatch):
    import httpx

    from memory.publish import _llm_complete

    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(headers)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "ok"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    _llm_complete("hi", model="m", base_url="https://api.anthropic.com", token="sk-ant-api03-xyz")
    assert seen["x-api-key"] == "sk-ant-api03-xyz"
    assert "Authorization" not in seen
