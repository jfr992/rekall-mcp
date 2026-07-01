from memory.publish import slug_title, make_title_fn, cluster_key


def _mem(mid, content):
    return {"memory_id": mid, "type": "learning", "content": content}


def test_slug_title_deterministic():
    c = [_mem("a", "KubeVirt namespace recovery recipe for stuck ns")]
    t1 = slug_title(c)
    t2 = slug_title(c)
    assert t1 == t2
    assert t1[0]  # non-empty title


def test_cluster_key_order_independent():
    a = [_mem("x", "1"), _mem("y", "2")]
    b = [_mem("y", "2"), _mem("x", "1")]
    assert cluster_key(a) == cluster_key(b)


def test_title_fn_uses_cache():
    calls = []

    def judge(cluster):
        calls.append(1)
        return ("Judged Title", "summary")

    cache = {}
    fn = make_title_fn(cache, judge=judge)
    c = [_mem("a", "content")]
    first = fn(c)
    second = fn(c)
    assert first == ("Judged Title", "summary")
    assert second == first
    assert len(calls) == 1


def test_title_fn_falls_back_when_no_judge():
    fn = make_title_fn({}, judge=None)
    title, _ = fn([_mem("a", "some memory content here")])
    assert title


def test_title_fn_falls_back_on_implausible_judge():
    fn = make_title_fn({}, judge=lambda c: ("", ""))
    title, _ = fn([_mem("a", "real content")])
    assert title
