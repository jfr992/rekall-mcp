"""OKF v0.1 renderer — emits conformant concept docs + per-directory index.

Conformance: every non-reserved .md has parseable YAML frontmatter with a
non-empty `type`. `index.md`/`log.md` are reserved (never concept docs).
Cross-links are bundle-relative (`/…`).
"""

from __future__ import annotations

import re

import yaml

from memory.publish_types import Bundle, Concept

_RESERVED = {"index.md", "log.md"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "concept"


def _emit(concept: Concept) -> str:
    fm = dict(concept.frontmatter)
    if not fm.get("type"):
        raise ValueError(f"OKF concept requires non-empty type: {concept.path}")
    front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
    return f"---\n{front}\n---\n{concept.body}\n"


class OkfRenderer:
    def render(self, concepts: list[Concept]) -> Bundle:
        files: dict[str, str] = {}
        dirs: dict[str, list[str]] = {}
        for c in concepts:
            if c.path.rsplit("/", 1)[-1] in _RESERVED:
                raise ValueError(f"reserved filename used as concept: {c.path}")
            files[c.path] = _emit(c)
            d = c.path.rsplit("/", 1)[0] if "/" in c.path else ""
            dirs.setdefault(d, []).append(c.path)

        for d, paths in dirs.items():
            idx = f"{d}/index.md" if d else "index.md"
            listing = "\n".join(f"- [/{p[:-3]}](/{p})" for p in sorted(paths))
            files[idx] = f"---\ntype: index\n---\n# {d or 'root'}\n\n{listing}\n"

        return Bundle(tree=sorted(files), files=files, stats={"concepts": len(concepts)})
