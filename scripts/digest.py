#!/usr/bin/env python
"""Export memories to human-readable Markdown digests.

Usage: uv run python scripts/digest.py [--project NAME] [--out DIR]

Emits: RUNBOOK.md (learnings), DECISIONS.md (ADR shadow), HOW_I_WORK.md
(preferences + requirements). Reads YAML source-of-truth directly — no backend.
"""

from __future__ import annotations

import argparse
import glob
import os
from collections import defaultdict

import yaml

# ponytail: skip test noise; add more names here if the corpus grows junk
SKIP_PROJECTS = {"test-project"}
JUNK_MARKERS = ("Setup decision", "Important architectural choice", "Setup learning")

# (yaml list key, output file, heading) — one row per digest
DIGESTS = [
    ("learnings", "RUNBOOK.md", "Ops Runbook — Lessons & Root Causes"),
    ("decisions", "DECISIONS.md", "Decision Log (ADR Shadow)"),
]


def _load_all(base: str) -> list[dict]:
    memories: list[dict] = []
    for f in glob.glob(os.path.join(base, "**", "*.yaml"), recursive=True):
        if any(s in f for s in SKIP_PROJECTS):
            continue
        try:
            doc = yaml.safe_load(open(f))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for key in ("learnings", "decisions", "preferences", "requirements", "facts"):
            for m in doc.get(key) or []:
                if isinstance(m, dict) and m.get("content"):
                    memories.append({**m, "_kind": key})
    return memories


def _clean(memories: list[dict], kind: str, project: str | None) -> list[dict]:
    out = []
    for m in memories:
        if m["_kind"] != kind:
            continue
        c = (m.get("content") or "").strip()
        if len(c) < 40 or any(j in c for j in JUNK_MARKERS):
            continue
        if project and m.get("project") != project:
            continue
        out.append(m)
    # newest first — timestamp or date, whichever is present
    out.sort(key=lambda m: str(m.get("timestamp") or m.get("date") or ""), reverse=True)
    return out


def _by_project(memories: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in memories:
        groups[m.get("project") or "general"].append(m)
    return dict(sorted(groups.items(), key=lambda kv: -len(kv[1])))


def _write_grouped(path: str, title: str, memories: list[dict]) -> int:
    lines = [f"# {title}", "", f"_{len(memories)} entries · auto-generated from memory_", ""]
    for proj, items in _by_project(memories).items():
        lines.append(f"## {proj} ({len(items)})")
        lines.append("")
        for m in items:
            date = m.get("date") or str(m.get("timestamp") or "")[:10]
            lines.append(f"- {m['content'].strip()}" + (f"  _({date})_" if date else ""))
        lines.append("")
    open(path, "w").write("\n".join(lines))
    return len(memories)


def _write_how_i_work(path: str, prefs: list[dict], reqs: list[dict]) -> int:
    lines = ["# How I Work", "", "_Auto-generated from preferences + requirements_", ""]
    lines.append(f"## Preferences ({len(prefs)})")
    lines.append("")
    lines += [f"- {m['content'].strip()}" for m in prefs]
    lines.append("")
    lines.append(f"## Requirements & Hard Rules ({len(reqs)})")
    lines.append("")
    lines += [f"- {m['content'].strip()}" for m in reqs]
    lines.append("")
    open(path, "w").write("\n".join(lines))
    return len(prefs) + len(reqs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="filter to one project")
    ap.add_argument("--base", default=os.path.expanduser("~/.claude/memory"))
    ap.add_argument("--out", default="./digest")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    memories = _load_all(args.base)

    for kind, fname, title in DIGESTS:
        n = _write_grouped(
            os.path.join(args.out, fname), title, _clean(memories, kind, args.project)
        )
        print(f"  {fname:16} {n:>4} entries")

    prefs = _clean(memories, "preferences", args.project)
    reqs = _clean(memories, "requirements", args.project)
    n = _write_how_i_work(os.path.join(args.out, "HOW_I_WORK.md"), prefs, reqs)
    print(f"  {'HOW_I_WORK.md':16} {n:>4} entries")
    print(f"→ {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
