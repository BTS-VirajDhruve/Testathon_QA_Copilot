"""Phase 1 — fast text normalization before any LLM call."""

from __future__ import annotations

import re

from app.graph.nl.models import PreprocessResult

_BULLET_CHARS = "\\-\\*•∙·‣▪▫○●"
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_PUNCT = re.compile(r"([.!?]){2,}")
_EMPTY_BULLET = re.compile(rf"^[\s]*[{_BULLET_CHARS}]\s*$")
_BULLET_LINE = re.compile(rf"^(\s*)([{_BULLET_CHARS}]|\d+[.)])\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")


def normalize_text(raw: str) -> PreprocessResult:
    """Normalize whitespace, bullets, numbering; preserve hierarchy."""
    if not raw:
        return PreprocessResult(text="", lines=[], stats={"empty": True})

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    # Normalize exotic bullets to "-"
    for ch in ("•", "∙", "·", "‣", "▪", "▫", "○", "●", "*"):
        text = text.replace(ch, "-")

    raw_lines = text.split("\n")
    lines: list[str] = []
    max_depth = 0
    heading_count = 0

    for line in raw_lines:
        # Strip trailing whitespace; keep leading for indentation
        stripped_end = line.rstrip()
        if _EMPTY_BULLET.match(stripped_end):
            continue

        # Collapse internal runs of spaces (preserve indent)
        m_indent = re.match(r"^(\s*)(.*)$", stripped_end)
        indent = m_indent.group(1) if m_indent else ""
        body = m_indent.group(2) if m_indent else stripped_end
        body = _MULTI_SPACE.sub(" ", body)
        body = _MULTI_PUNCT.sub(r"\1", body)
        body = body.strip()
        if not body:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        # Normalize numbering "1)" / "1." → "- "
        num = _NUMBERED.match(indent + body)
        if num:
            indent = num.group(1)
            body = num.group(3)
            depth = _indent_depth(indent)
            max_depth = max(max_depth, depth)
            lines.append(f"{'  ' * depth}- {body}")
            continue

        bul = _BULLET_LINE.match(indent + body)
        if bul:
            indent = bul.group(1)
            body = bul.group(3)
            depth = _indent_depth(indent)
            max_depth = max(max_depth, depth)
            lines.append(f"{'  ' * depth}- {body}")
            continue

        # Markdown-ish headings
        if body.startswith("#"):
            heading_count += 1
            body = body.lstrip("#").strip()
            lines.append(body)
            continue

        # Title-ish short lines without period → treat as potential heading
        if len(body) <= 64 and not body.endswith((".", ",", ";", ":")) and " " in body:
            # keep as-is; parser may promote
            pass

        lines.append(f"{indent}{body}" if indent.startswith("  ") else body)

    # Drop leading/trailing blank lines; collapse 3+ blanks to 1
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    collapsed: list[str] = []
    blank_run = 0
    for ln in lines:
        if ln == "":
            blank_run += 1
            if blank_run <= 1:
                collapsed.append("")
        else:
            blank_run = 0
            collapsed.append(ln)
    lines = collapsed

    paragraphs = [p for p in "\n".join(lines).split("\n\n") if p.strip()]
    normalized = "\n".join(lines)
    stats = {
        "paragraph_count": len(paragraphs),
        "heading_count": heading_count,
        "bullet_depth": max_depth,
        "line_count": len(lines),
        "char_count": len(normalized),
    }
    return PreprocessResult(
        text=normalized,
        lines=lines,
        paragraph_count=len(paragraphs),
        heading_count=heading_count,
        bullet_depth=max_depth,
        stats=stats,
    )


def _indent_depth(indent: str) -> int:
    if not indent:
        return 0
    # tabs count as 2 spaces
    spaces = indent.replace("\t", "  ")
    return max(0, len(spaces) // 2)
