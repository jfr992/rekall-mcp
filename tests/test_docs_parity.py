"""Docs stay honest: README tables and .env.example must match the source.

Static parse — no server import, no Qdrant. If this fails, either the code
grew surface README doesn't document, or .env.example names a var nothing reads.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = (REPO / "README.md").read_text()
SERVER_SRC = (REPO / "src" / "server.py").read_text()
TOOLS_SRC = (REPO / "src" / "tools" / "builtin" / "memory.py").read_text()

ROUTE_RE = re.compile(r'@mcp\.custom_route\(\s*"([^"]+)"\s*,\s*methods=\[([^\]]+)\]')
# All @mcp.tool() decorators in the codebase use @mcp.tool(structured_output=False),
# so [^)]* is needed to match the optional arguments inside the parens.
TOOL_RE = re.compile(r"@mcp\.tool\([^)]*\)\s*\n\s*(?:async\s+)?def\s+(\w+)")


def _norm(path: str) -> str:
    # README writes `/api/memory/{id}`; code writes `{memory_id}` — compare shape, not names
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_every_route_is_in_readme():
    # Restrict to table rows (lines starting with "|") to avoid matching prose
    # mentions of paths (e.g. "/health" appears in a description sentence before
    # the REST table, which lacks the method column and would cause false failures).
    readme_rows = [
        (_norm(m.group(1)), ln)
        for ln in README.splitlines()
        if ln.startswith("|") and (m := re.search(r"`(/[^`]*)`", ln))
    ]
    missing = []
    for path, methods in ROUTE_RE.findall(SERVER_SRC):
        row = next((ln for p, ln in readme_rows if p == _norm(path)), None)
        if row is None:
            missing.append(path)
            continue
        for method in re.findall(r'"(\w+)"', methods):
            if method not in row:
                missing.append(f"{path} [{method}]")
    assert not missing, f"routes not documented in README REST table: {missing}"


def test_every_mcp_tool_is_in_readme():
    tools = TOOL_RE.findall(TOOLS_SRC) + TOOL_RE.findall(SERVER_SRC)
    assert tools, "tool regex matched nothing — decorator pattern changed?"
    missing = [t for t in tools if f"`{t}(" not in README and f"`{t}`" not in README]
    assert not missing, f"MCP tools not documented in README tools table: {missing}"


def test_env_example_vars_are_read_somewhere():
    env_text = (REPO / ".env.example").read_text()
    keys = re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", env_text, flags=re.MULTILINE)
    haystack = "\n".join(
        p.read_text()
        for p in [
            *(REPO / "src").rglob("*.py"),
            REPO / "docker-compose.yaml",
            *(REPO / "claude" / "hooks").glob("*.sh"),
        ]
    )
    dead = [k for k in set(keys) if k not in haystack]
    assert not dead, f".env.example vars read nowhere: {dead}"
