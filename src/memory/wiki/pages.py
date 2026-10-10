"""Wiki page model: Docusaurus-compatible markdown with Rekall frontmatter."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

PAGE_ID_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*/(process|policy|reference|entity)/[a-z0-9][a-z0-9-]*$"
)
MEMORY_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}_[a-z]+_[0-9a-f]+")
_H2_RE = re.compile(r"^## (.+?)(?:\s*\{#([a-z0-9-]+)\})?\s*$", re.M)
_SOURCE_RE = re.compile(r"\[source:\s*([^\]]+)\]")
_STEP_RE = re.compile(r"^\s*(?:\d+\.|[-*])\s+", re.M)
_REQUIRED = {
    "process": [
        "when",
        "preconditions",
        "steps",
        "expected",
        "verify",
        "stop",
        "rollback",
        "limits",
    ],
    "policy": ["rule", "why", "exceptions", "sources"],
    "reference": ["facts", "sources"],
    "entity": ["what", "related", "sources"],
}


@dataclass(frozen=True)
class Page:
    frontmatter: dict
    body: str

    @property
    def page_id(self) -> str:
        return str(self.frontmatter["page_id"])

    @property
    def type(self) -> str:
        return str(self.frontmatter["type"])

    @property
    def project(self) -> str:
        return str(self.frontmatter.get("project") or self.page_id.split("/")[0])

    @property
    def sources(self) -> list[str]:
        return [str(s) for s in (self.frontmatter.get("sources") or [])]

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status") or "draft")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def parse_page(text: str) -> Page:
    if not text.startswith("---\n"):
        raise ValueError("page has no frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    fm = yaml.safe_load(text[4:end]) or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter must be a mapping")
    for key in ("page_id", "type", "title"):
        if not fm.get(key):
            raise ValueError(f"frontmatter missing {key}")
    if not PAGE_ID_RE.match(str(fm["page_id"])):
        raise ValueError("invalid page_id")
    if fm["type"] not in _REQUIRED:
        raise ValueError("invalid type")
    body = text[end + 4 :].lstrip("\n")
    return Page(frontmatter=fm, body=body)


def emit_page(page: Page) -> str:
    fm = yaml.safe_dump(
        page.frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=None
    ).strip()
    return f"---\n{fm}\n---\n{page.body.rstrip()}\n"


def split_sections(body: str) -> list[tuple[str, str, str]]:
    matches = list(_H2_RE.finditer(body))
    out = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group(1).strip()
        section_id = m.group(2) or slugify(heading)
        out.append((section_id, heading, body[start:end].strip()))
    return out


def required_sections(page_type: str) -> list[str]:
    return list(_REQUIRED.get(page_type, []))


def missing_sections(page: Page) -> list[str]:
    present = {s[0] for s in split_sections(page.body)}
    return [s for s in required_sections(page.type) if s not in present]


def has_redaction(text: str) -> bool:
    return "[REDACTED]" in text


def step_sources(section_markdown: str) -> list[list[str]]:
    steps = [s for s in _STEP_RE.split(section_markdown) if s.strip()]
    return [[sid.strip() for sid in _SOURCE_RE.findall(step)] for step in steps]


def unsourced_steps(page: Page) -> int:
    if page.type != "process":
        return 0
    sections = {s[0]: s[2] for s in split_sections(page.body)}
    return sum(1 for sources in step_sources(sections.get("steps", "")) if not sources)


def token_estimate(text: str) -> int:
    return len(text) // 4
