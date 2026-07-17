"""T4.1: resume packet must not fabricate scope from the server's own cwd
(live bug: continuity header showed project 'app' — the container workdir)."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def fake_manager(monkeypatch):
    fake = MagicMock()
    fake.get_resume_packet.return_value = {"scope": None, "sections": []}
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


@pytest.fixture
def client():
    from server import build_app

    return TestClient(build_app())


def test_resume_without_project_passes_none_scope(client, fake_manager):
    r = client.get("/api/memory/resume")
    assert r.status_code == 200
    kwargs = fake_manager.get_resume_packet.call_args.kwargs
    assert kwargs.get("project") is None
    assert kwargs.get("all_scopes") is True


def test_resume_with_project_scopes_to_it(client, fake_manager):
    client.get("/api/memory/resume?project=byte-edge")
    assert fake_manager.get_resume_packet.call_args.kwargs["project"] == "byte-edge"
