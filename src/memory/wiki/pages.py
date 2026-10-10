"""Wiki page model: Docusaurus-compatible markdown with Rekall frontmatter."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

PAGE_ID_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*/(process|policy|reference|entity)/[a-z0-9][a-z0-9-]*$"
)
MEMORY_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}_[a-z]+_[0-9a-f]+")
_H2_RE = re.compile(r"^## (.+?)(?:\s*\{#([a-z0-9-]+)\})?\s*$")
_SOURCE_RE = re.compile(r"\[source:\s*([^\]]+)\]")
_STEP_START_RE = re.compile(r"^(?:\d+\.|[-*])\s")
_FRONTMATTER_RE = re.compile(r"---\n(?:(.*?)\n)?---[ \t]*(?:\n|$)", re.S)
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
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("page has no frontmatter")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("unterminated frontmatter")
    fm = yaml.safe_load(match.group(1) or "") or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter must be a mapping")
    for key in ("page_id", "type", "title"):
        if not fm.get(key):
            raise ValueError(f"frontmatter missing {key}")
    if not PAGE_ID_RE.match(str(fm["page_id"])):
        raise ValueError("invalid page_id")
    if fm["type"] not in _REQUIRED:
        raise ValueError("invalid type")
    body = text[match.end() :].lstrip("\n")
    return Page(frontmatter=fm, body=body)


def emit_page(page: Page) -> str:
    fm = yaml.safe_dump(
        page.frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=None
    ).strip()
    return f"---\n{fm}\n---\n{page.body.rstrip()}\n"


def split_sections(body: str) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, list[str]]] = []
    fence = None
    for line in body.split("\n"):
        marker = line[:3]
        if marker in ("```", "~~~"):
            fence = None if fence == marker else (fence or marker)
        heading = None if fence else _H2_RE.match(line)
        if heading:
            heading_text = heading.group(1).strip()
            sections.append((heading.group(2) or slugify(heading_text), heading_text, []))
        elif sections:
            sections[-1][2].append(line)
    return [(sid, heading, "\n".join(lines).strip()) for sid, heading, lines in sections]


def required_sections(page_type: str) -> list[str]:
    return list(_REQUIRED.get(page_type, []))


def missing_sections(page: Page) -> list[str]:
    present = {s[0] for s in split_sections(page.body)}
    return [s for s in required_sections(page.type) if s not in present]


def has_redaction(text: str) -> bool:
    return "[REDACTED]" in text


def step_sources(section_markdown: str) -> list[list[str]]:
    items: list[list[str]] = []
    for line in section_markdown.split("\n"):
        if _STEP_START_RE.match(line):
            items.append([line])
        elif items:
            items[-1].append(line)
    return [
        [mid for tag in _SOURCE_RE.findall("\n".join(item)) for mid in MEMORY_ID_RE.findall(tag)]
        for item in items
    ]


def cited_ids(text: str) -> list[str]:
    return list(
        dict.fromkeys(mid for tag in _SOURCE_RE.findall(text) for mid in MEMORY_ID_RE.findall(tag))
    )


def unsourced_steps(page: Page) -> int:
    if page.type != "process":
        return 0
    sections = {s[0]: s[2] for s in split_sections(page.body)}
    steps = step_sources(sections.get("steps", ""))
    return sum(1 for sources in steps if not sources) or (0 if steps else 1)


def token_estimate(text: str) -> int:
    return len(text) // 4


SECTION_BUDGET, FULL_BUDGET = 1500, 3000


def trim_to_budget(text: str, budget: int) -> tuple[str, bool]:
    if token_estimate(text) <= budget:
        return text, False
    cut = text[: budget * 4]
    boundary = cut.rfind("\n\n")
    return (cut[:boundary] if boundary > 0 else cut), True
