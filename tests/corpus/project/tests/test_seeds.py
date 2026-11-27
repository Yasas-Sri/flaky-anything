from corpuslib import ids, tags


def test_sample_has_no_duplicates_bug():
    """S1: random.choice twice can repeat; depends on the random seed."""
    a, b = ids.pick_two(["ann", "bob", "cy", "dee", "eve"])
    assert a != b


def test_tags_render_in_order():
    """S2: joins a set of str; order depends on PYTHONHASHSEED."""
    assert tags.render(tags.tags_for("release")) == "alpha, beta"


def test_uses_os_urandom():
    """U1: os.urandom-backed randomness; no knob controls it (~20% failure)."""
    assert ids.backoff_jitter_ms() >= 1
