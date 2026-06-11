"""Fix M11 — repo_remote must not contain credentials when persisted."""

from memory.scope import _strip_creds


def test_strip_creds_from_https_with_user_token():
    assert (
        _strip_creds("https://user:ghp_abc@github.com/foo/bar.git")
        == "https://github.com/foo/bar.git"
    )


def test_strip_creds_from_https_with_token_only():
    assert (
        _strip_creds("https://x-access-token:ghs_xyz@github.com/foo/bar.git")
        == "https://github.com/foo/bar.git"
    )


def test_strip_creds_from_https_user_only():
    assert _strip_creds("https://user@github.com/foo/bar.git") == "https://github.com/foo/bar.git"


def test_strip_creds_leaves_plain_https_alone():
    assert _strip_creds("https://github.com/foo/bar.git") == "https://github.com/foo/bar.git"


def test_strip_creds_leaves_ssh_alone():
    assert _strip_creds("git@github.com:foo/bar.git") == "git@github.com:foo/bar.git"


def test_strip_creds_handles_none():
    assert _strip_creds(None) == ""
    assert _strip_creds("") == ""


def test_strip_creds_leaves_git_scheme_alone():
    assert _strip_creds("git://github.com/foo/bar.git") == "git://github.com/foo/bar.git"
