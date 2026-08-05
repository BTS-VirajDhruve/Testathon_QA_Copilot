"""Atlassian Document Format (ADF) → plain Markdown/text."""

from __future__ import annotations

from typing import Any


def adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(adf_to_text(n) for n in node if n is not None).strip()
    if not isinstance(node, dict):
        return str(node)

    ntype = node.get("type")
    content = node.get("content") or []
    text = node.get("text") or ""
    marks = node.get("marks") or []

    if ntype == "text":
        out = text
        for mark in marks:
            mtype = mark.get("type")
            if mtype == "code":
                out = f"`{out}`"
            elif mtype == "link":
                href = (mark.get("attrs") or {}).get("href") or ""
                out = f"[{out}]({href})" if href else out
            elif mtype == "strong":
                out = f"**{out}**"
            elif mtype == "em":
                out = f"*{out}*"
        return out

    if ntype == "hardBreak":
        return "\n"
    if ntype == "mention":
        attrs = node.get("attrs") or {}
        return str(attrs.get("text") or attrs.get("id") or "@user")
    if ntype == "emoji":
        attrs = node.get("attrs") or {}
        return str(attrs.get("shortName") or attrs.get("text") or "")
    if ntype == "inlineCard":
        attrs = node.get("attrs") or {}
        return str(attrs.get("url") or "")

    children = "".join(adf_to_text(c) for c in content)

    if ntype == "paragraph":
        return children.strip() + "\n\n"
    if ntype == "heading":
        level = int((node.get("attrs") or {}).get("level") or 1)
        return f"{'#' * max(1, min(level, 6))} {children.strip()}\n\n"
    if ntype == "bulletList":
        items = []
        for c in content:
            item = adf_to_text(c).strip()
            items.append(f"- {item}" if item else "-")
        return "\n".join(items) + "\n\n"
    if ntype == "orderedList":
        items = []
        for i, c in enumerate(content, start=1):
            item = adf_to_text(c).strip()
            items.append(f"{i}. {item}" if item else f"{i}.")
        return "\n".join(items) + "\n\n"
    if ntype == "listItem":
        return children.strip()
    if ntype == "codeBlock":
        lang = (node.get("attrs") or {}).get("language") or ""
        return f"```{lang}\n{children.strip()}\n```\n\n"
    if ntype == "blockquote":
        lines = [f"> {line}" for line in children.strip().splitlines() or [""]]
        return "\n".join(lines) + "\n\n"
    if ntype == "panel":
        return children.strip() + "\n\n"
    if ntype == "table":
        rows = [adf_to_text(c).strip() for c in content]
        return "\n".join(r for r in rows if r) + "\n\n"
    if ntype in {"tableRow"}:
        cells = [adf_to_text(c).replace("\n", " ").strip() for c in content]
        return "| " + " | ".join(cells) + " |"
    if ntype in {"tableCell", "tableHeader"}:
        return children.strip()
    if ntype == "doc":
        return children.strip()
    if ntype == "rule":
        return "---\n\n"
    return children.strip()
