"""Sanitize Confluence storage HTML into plain text / light Markdown."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low in {"script", "style"}:
            self._skip += 1
            return
        if self._skip:
            return
        attr_map = {k: (v or "") for k, v in attrs}
        if low in {"br", "hr"}:
            self.parts.append("\n")
        elif low in {"p", "div", "tr"}:
            self.parts.append("\n")
        elif low in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(low[1])
            self.parts.append("\n" + "#" * level + " ")
        elif low == "li":
            self.parts.append("\n- ")
        elif low == "a" and attr_map.get("href"):
            self.parts.append("[")
            self._pending_href = attr_map["href"]
        elif low == "code":
            self.parts.append("`")
        elif low == "ac:structured-macro":
            name = attr_map.get("ac:name") or attr_map.get("name") or "macro"
            self.parts.append(f"\n[Unsupported Confluence macro: {name}]\n")

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if low == "a" and hasattr(self, "_pending_href"):
            href = getattr(self, "_pending_href", "")
            self.parts.append(f"]({href})")
            self._pending_href = ""
        elif low == "code":
            self.parts.append("`")
        elif low in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "table"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data)


_EVENT_ATTR = re.compile(r"\son\w+\s*=\s*([\"']).*?\1", re.I | re.S)
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    cleaned = _SCRIPT.sub("", html)
    cleaned = _EVENT_ATTR.sub("", cleaned)
    parser = _HTMLToText()
    try:
        parser.feed(cleaned)
        parser.close()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", cleaned)
    text = "".join(parser.parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
