"""Ephemeral eval backend: never touches prod, seeds via the production write path.

Prod = Qdrant :6333 / backend :8000 / ~/.claude/memory (or MEMORY_STORAGE_PATH).
The eval refuses to start against any of them — two zero-vector incidents and one
99-memory data loss are why this is code, not convention.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx


def assert_not_prod(qdrant_url: str, storage_path: Path) -> None:
    """Refuse prod targets. Raises RuntimeError — there is no override flag."""
    if ":6333" in qdrant_url:
        raise RuntimeError(f"prod Qdrant refused: {qdrant_url}")
    resolved = storage_path.resolve()
    prod_paths = [Path.home() / ".claude" / "memory"]
    env_prod = os.getenv("MEMORY_STORAGE_PATH")
    if env_prod:
        prod_paths.append(Path(env_prod))
    for prod in prod_paths:
        if resolved == prod.resolve() or resolved.is_relative_to(prod.resolve()):
            raise RuntimeError(f"prod storage refused: {resolved}")


def make_workspace(root: Path, item_id: str) -> Path:
    """Per-item dir: basename = project name; observe cwd AND driver cwd.

    git init is required so Claude Code recognizes the directory as a project root
    and reads cwd/.claude/settings.json. Without a .git marker, Claude Code ignores
    project-level settings entirely — ENABLE_TOOL_SEARCH=1 never overrides auto:0.
    """
    ws = root / f"eval-{item_id}"
    ws.mkdir(parents=True, exist_ok=True)
    # ponytail: minimal git init — only HEAD + config; no index or pack needed
    git_dir = ws / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n"
    )
    return ws


class EphemeralBackend:
    """One Rekall server on :8010 bound to test Qdrant :6334 + temp storage."""

    def __init__(
        self,
        qdrant_url: str = "http://localhost:6334",
        port: int = 8010,
        storage_path: Path | None = None,
    ) -> None:
        if storage_path is None:
            raise ValueError("storage_path is required")
        assert_not_prod(qdrant_url, storage_path)
        self.qdrant_url = qdrant_url
        self.port = port
        self.storage_path = storage_path
        self.base_url = f"http://127.0.0.1:{port}"
        self._proc: subprocess.Popen | None = None

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Strip pytest markers: server.py _is_testing = "PYTEST_VERSION" in os.environ
        # If inherited, setup_tools() is skipped — only 2 of 28 rekall tools register.
        for _k in ("PYTEST_VERSION", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER"):
            env.pop(_k, None)
        env.update(
            QDRANT_URL=self.qdrant_url,
            MEMORY_STORAGE_PATH=str(self.storage_path),
            MCP_TRANSPORT="streamable-http",
            PORT=str(self.port),
            REKALL_AUTOSAVE="0",
        )
        return env

    def start(self, timeout_s: float = 60.0) -> None:
        self.storage_path.mkdir(parents=True, exist_ok=True)
        repo_root = Path(__file__).resolve().parents[2]
        self._proc = subprocess.Popen(
            ["uv", "run", "python", "src/server.py"],
            env=self._child_env(),
            cwd=str(repo_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base_url}/health", timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"ephemeral backend failed to become healthy on :{self.port}")

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def __enter__(self) -> "EphemeralBackend":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def wipe(self) -> None:
        """Per-item isolation: recreate Qdrant collection + empty temp storage.

        Delete then immediately recreate the collection so the server's cached
        QdrantClient remains valid (it was connected before the wipe).
        """
        httpx.delete(f"{self.qdrant_url}/collections/agent_memory", timeout=10.0)
        # Recreate empty collection — server singleton reuses this connection.
        httpx.put(
            f"{self.qdrant_url}/collections/agent_memory",
            json={"vectors": {"size": 384, "distance": "Cosine"}},
            timeout=10.0,
        ).raise_for_status()
        for child in self.storage_path.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        remaining = list(self.storage_path.iterdir())
        if remaining:
            raise RuntimeError(f"wipe incomplete: {remaining[:3]}")

    def seed(self, memories: list[dict], cwd: str) -> dict[str, str]:
        """Production write path (POST /api/memory/observe). Returns memory_id -> session_id."""
        idmap: dict[str, str] = {}
        for i, m in enumerate(memories):
            resp = httpx.post(
                f"{self.base_url}/api/memory/observe",
                json={"summary": m["summary"], "type": m.get("type", "fact"), "cwd": cwd},
                timeout=30.0,
            )
            resp.raise_for_status()
            idmap[resp.json()["memory_id"]] = m.get("session_id", f"probe:{i}")
        return idmap

    def recall_ids(self, query: str, project: str | None, limit: int = 5) -> list[str]:
        """Direct REST retrieval — the agent-free precision@5 path."""
        resp = httpx.post(
            f"{self.base_url}/api/memory/recall",
            json={"query": query, "limit": limit, "project": project},
            timeout=30.0,
        )
        resp.raise_for_status()
        return [m["memory_id"] for m in resp.json()["memories"] if m.get("memory_id")]
