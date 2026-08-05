"""Phase 2 — rule-based NL parser → Intermediate Tree (no LLM)."""

from __future__ import annotations

import re
from typing import Iterable

from app.graph.nl.models import IntermediateNode, IntermediateTree, PreprocessResult
from app.models.enums import NodeType, Priority

# Verb patterns that introduce child lists under a parent subject.
_RELATION_VERBS = (
    r"includes?",
    r"contains?",
    r"consists\s+of",
    r"supports?",
    r"has",
    r"requires?",
    r"uses?",
    r"validates?",
    r"depends\s+on",
    r"covers?",
    r"provides?",
    r"offers?",
    r"allows?",
    r"enables?",
    r"lets\s+\w+",
    r"starts?\s+with",
    r"leads?\s+to",
)

_RELATION_RE = re.compile(
    rf"^(?P<sub>.+?)\s+(?:(?:is|are)\s+)?(?P<verb>{'|'.join(_RELATION_VERBS)})\s+(?P<obj>.+)$",
    re.I,
)

_ROOT_RE = re.compile(
    r"^(?P<root>.+?)\s+is\s+the\s+root\s+feature\b",
    re.I,
)

_SECTION_HINTS: list[tuple[re.Pattern[str], NodeType | None, dict]] = [
    (re.compile(r"failure\s+paths?", re.I), NodeType.FAILURE_PATH, {"is_failure_path": True}),
    (re.compile(r"external\s+dependenc", re.I), NodeType.EXTERNAL_DEPENDENCY, {"is_external_dependency": True}),
    (re.compile(r"alternate\s+flows?", re.I), NodeType.ALTERNATE_FLOW, {}),
    (re.compile(r"business\s+rules?", re.I), NodeType.BUSINESS_RULE, {}),
    (re.compile(r"\bapis?\b", re.I), NodeType.API, {}),
    (re.compile(r"\bservices?\b", re.I), NodeType.SERVICE, {}),
    (re.compile(r"\bdatabases?\b", re.I), NodeType.DATABASE, {}),
    (re.compile(r"validat", re.I), NodeType.VALIDATION, {}),
]

_FAILURE_WORDS = re.compile(
    r"\b(failure|timeout|decline|reject|invalid|lockout|error|fail|unavailable|out of stock)\b",
    re.I,
)
_EXTERNAL_WORDS = re.compile(
    r"\b(external|third[- ]party|gateway|provider|oauth|upi|sso|saml|oidc)\b",
    re.I,
)
_CRITICAL_WORDS = re.compile(r"\b(critical|must|required|blocking)\b", re.I)

_BULLET = re.compile(r"^(\s*)-\s+(.*)$")
_CLAUSE_SPLIT = re.compile(r"[.;]\s+(?=[A-Z0-9])")
_LIST_SPLIT = re.compile(r",\s*(?:and\s+)?|\s+and\s+|\s*;\s*")


def parse_to_tree(pre: PreprocessResult) -> IntermediateTree:
    """Build an IntermediateTree from normalized text using rules only."""
    text = pre.text.strip()
    if not text:
        root = IntermediateNode(name="Feature", type=NodeType.FEATURE, type_confidence=1.0)
        return IntermediateTree(root=root, description="", stats={"empty": True})

    # Prefer explicit bullet hierarchy when present
    if pre.bullet_depth > 0 or any(_BULLET.match(ln) for ln in pre.lines):
        tree = _parse_bullet_tree(pre)
        if tree and len(tree.all_nodes()) > 1:
            tree.stats.update(pre.stats)
            tree.stats["parser"] = "bullet"
            return tree

    tree = _parse_prose_tree(pre)
    tree.stats.update(pre.stats)
    tree.stats["parser"] = "prose"
    return tree


def _parse_bullet_tree(pre: PreprocessResult) -> IntermediateTree | None:
    # Collect non-bullet preamble for root/description
    preamble: list[str] = []
    items: list[tuple[int, str]] = []
    for ln in pre.lines:
        if not ln.strip():
            continue
        m = _BULLET.match(ln)
        if m:
            depth = len(m.group(1)) // 2
            items.append((depth, m.group(2).strip()))
        elif not items:
            preamble.append(ln.strip())

    if not items:
        return None

    root_name = _guess_root_from_preamble(preamble) or _title_case_token(items[0][1])
    # If first bullet is depth 0 and looks like root title matching preamble, use it as root
    if items and items[0][0] == 0 and not preamble:
        root_name = _clean_node_name(items[0][1])
        items = items[1:]

    root = IntermediateNode(
        name=root_name,
        type=NodeType.FEATURE,
        description=" ".join(preamble)[:400] if preamble else f"Root feature: {root_name}",
        type_confidence=1.0,
        is_critical=True,
        criticality=Priority.HIGH,
    )

    stack: list[tuple[int, IntermediateNode]] = [(-1, root)]
    section_flags: dict = {}
    for depth, raw in items:
        name, flags = _annotate_name(raw, section_flags)
        # Section headers like "Failure paths:" with no real name
        section = _match_section_header(name)
        if section is not None:
            ntype, extra = section
            section_flags = {"type": ntype, **extra}
            continue

        node = IntermediateNode(
            name=name,
            description="",
            type=flags.get("type"),
            is_failure_path=bool(flags.get("is_failure_path")),
            is_external_dependency=bool(flags.get("is_external_dependency")),
            is_critical=bool(flags.get("is_critical")),
            criticality=flags.get("criticality"),
            type_confidence=float(flags.get("type_confidence", 0.0)),
            metadata={"source": "bullet"},
        )
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1]
        parent.children.append(node)
        stack.append((depth, node))

    return IntermediateTree(root=root, description=root.description)


def _parse_prose_tree(pre: PreprocessResult) -> IntermediateTree:
    text = pre.text
    root_name = None
    description_bits: list[str] = []

    for ln in pre.lines[:5]:
        if not ln.strip() or _BULLET.match(ln):
            continue
        m = _ROOT_RE.match(ln.strip())
        if m:
            root_name = _clean_node_name(m.group("root"))
            break

    if not root_name:
        root_name = _guess_root_from_preamble([ln for ln in pre.lines if ln.strip()][:3])

    if not root_name:
        # First sentence subject
        first = pre.lines[0].strip() if pre.lines else "Feature"
        root_name = _subject_of_sentence(first) or "Feature"

    root = IntermediateNode(
        name=root_name,
        type=NodeType.FEATURE,
        type_confidence=1.0,
        is_critical=True,
        criticality=Priority.HIGH,
    )

    # Split into sentences / clauses and apply relation patterns
    sentences = _iter_sentences(text)
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if _ROOT_RE.match(sent):
            continue

        # Section label alone
        section = _match_section_header(sent.rstrip(":"))
        if section and len(sent) < 48:
            # Next items inherit — store on metadata for following clauses
            root.metadata["_section"] = section
            continue

        rel = _RELATION_RE.match(sent)
        if rel:
            sub = _clean_node_name(rel.group("sub"))
            obj = rel.group("obj").strip()
            children_raw = _split_list_items(obj)
            parent = root if _names_match(sub, root.name) else root.find_by_name(sub)
            if parent is None:
                # Create subject as top-level child of root when it looks like a feature area
                parent = IntermediateNode(
                    name=sub,
                    type=NodeType.SUB_FEATURE,
                    type_confidence=0.55,
                    metadata={"source": "prose_subject"},
                )
                root.children.append(parent)

            section_state = root.metadata.get("_section")
            for raw_child in children_raw:
                name, flags = _annotate_name(raw_child, {})
                if not name or _names_match(name, parent.name):
                    continue
                if parent.find_by_name(name) and any(
                    _names_match(c.name, name) for c in parent.children
                ):
                    continue
                extra = {}
                conf = 0.5
                ntype = flags.get("type")
                if section_state:
                    ntype = ntype or section_state[0]
                    extra = {**section_state[1]}
                    conf = 0.75
                child = IntermediateNode(
                    name=name,
                    type=ntype,
                    is_failure_path=bool(flags.get("is_failure_path") or extra.get("is_failure_path")),
                    is_external_dependency=bool(
                        flags.get("is_external_dependency") or extra.get("is_external_dependency")
                    ),
                    is_critical=bool(flags.get("is_critical")),
                    criticality=flags.get("criticality"),
                    type_confidence=float(flags.get("type_confidence", conf)),
                    metadata={"source": "prose_relation", "verb": rel.group("verb").lower()},
                    description=_trim_desc(raw_child, name),
                )
                # Nested "with X and Y" / "including A, B"
                nested = _extract_nested_with(raw_child)
                for nest_name in nested:
                    n2, f2 = _annotate_name(nest_name, {})
                    if not n2:
                        continue
                    child.children.append(
                        IntermediateNode(
                            name=n2,
                            type=f2.get("type"),
                            is_failure_path=bool(f2.get("is_failure_path")),
                            is_external_dependency=bool(f2.get("is_external_dependency")),
                            type_confidence=float(f2.get("type_confidence", 0.45)),
                            metadata={"source": "nested_with"},
                        )
                    )
                parent.children.append(child)
            continue

        # Standalone failure / dependency mentions attached to nearest context
        if _FAILURE_WORDS.search(sent) and len(sent) < 160:
            name, flags = _annotate_name(sent, {"type": NodeType.FAILURE_PATH, "is_failure_path": True})
            if name and not root.find_by_name(name):
                # Prefer last feature-like child as parent
                parent = root.children[-1] if root.children else root
                parent.children.append(
                    IntermediateNode(
                        name=_shorten_failure_name(name),
                        type=NodeType.FAILURE_PATH,
                        is_failure_path=True,
                        type_confidence=0.7,
                        metadata={"source": "failure_sentence"},
                        description=sent[:240],
                    )
                )
            continue

        description_bits.append(sent)

    if not root.children:
        # Fallback: noun-ish phrases from first paragraph
        for phrase in _fallback_phrases(text, root.name):
            root.children.append(
                IntermediateNode(
                    name=phrase,
                    type=NodeType.SUB_FEATURE,
                    type_confidence=0.35,
                    metadata={"source": "fallback_phrase"},
                )
            )

    root.description = (" ".join(description_bits)[:400] if description_bits else f"Root feature: {root.name}")
    return IntermediateTree(root=root, description=root.description)


def _iter_sentences(text: str) -> Iterable[str]:
    for para in text.split("\n"):
        para = para.strip()
        if not para or para.startswith("-"):
            continue
        # Split on . ; when followed by capital — keep commas inside lists
        parts = _CLAUSE_SPLIT.split(para)
        for part in parts:
            part = part.strip(" \t")
            if part:
                yield part


def _split_list_items(obj: str) -> list[str]:
    """Split 'A, B, and C with X' into top-level list items."""
    # Strip trailing relative clauses that aren't list items
    obj = re.sub(r"\s+which\s+.+$", "", obj, flags=re.I)
    obj = re.sub(r"\.\s*$", "", obj)

    # Protect parentheses content from splits
    protected: list[str] = []

    def _protect(m: re.Match[str]) -> str:
        protected.append(m.group(0))
        return f"__P{len(protected) - 1}__"

    tmp = re.sub(r"\([^)]*\)", _protect, obj)
    # Split on commas / and — but not inside protected
    parts = [p.strip() for p in _LIST_SPLIT.split(tmp) if p.strip()]
    restored: list[str] = []
    for p in parts:
        for i, val in enumerate(protected):
            p = p.replace(f"__P{i}__", val)
        # Drop very long narrative tails after colon
        if ":" in p and len(p) > 80:
            p = p.split(":", 1)[0].strip()
        restored.append(p)
    # Filter noise
    out: list[str] = []
    for p in restored:
        cleaned = _clean_node_name(p)
        if not cleaned:
            continue
        if len(cleaned) > 80:
            cleaned = cleaned[:77] + "..."
        out.append(cleaned if cleaned != p else _clean_node_name(p) or p)
    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _extract_nested_with(raw: str) -> list[str]:
    m = re.search(r"\b(?:with|including|via)\s+(.+)$", raw, re.I)
    if not m:
        # Parenthetical list
        paren = re.search(r"\(([^)]+)\)", raw)
        if paren and ("," in paren.group(1) or " and " in paren.group(1)):
            return _split_list_items(paren.group(1))
        return []
    return _split_list_items(m.group(1))


def _annotate_name(raw: str, inherit: dict) -> tuple[str, dict]:
    flags = dict(inherit)
    text = raw.strip().rstrip(".")
    # Strip trailing "are failure paths" etc.
    text = re.sub(r"\s+are\s+(a\s+)?failure\s+paths?\.?$", "", text, flags=re.I)
    text = re.sub(r"\s+is\s+(a\s+)?(?:critical\s+)?(?:external\s+)?failure\s+path\.?$", "", text, flags=re.I)
    text = re.sub(r"\s+\((?:external|failure|critical)\)\s*$", "", text, flags=re.I)

    if _FAILURE_WORDS.search(text) or flags.get("is_failure_path"):
        flags["is_failure_path"] = True
        flags.setdefault("type", NodeType.FAILURE_PATH)
        flags["type_confidence"] = max(float(flags.get("type_confidence", 0)), 0.85)

    if _EXTERNAL_WORDS.search(text) or flags.get("is_external_dependency"):
        flags["is_external_dependency"] = True
        if flags.get("type") is None:
            flags["type"] = NodeType.EXTERNAL_DEPENDENCY
            flags["type_confidence"] = max(float(flags.get("type_confidence", 0)), 0.8)

    if _CRITICAL_WORDS.search(text):
        flags["is_critical"] = True
        flags["criticality"] = Priority.CRITICAL

    name = _clean_node_name(text)
    return name, flags


def _clean_node_name(raw: str) -> str:
    s = raw.strip().strip("\"'`")
    s = re.sub(r"^(?:the|a|an)\s+", "", s, flags=re.I)
    # Remove leading verb leftovers
    s = re.sub(
        r"^(?:customers?\s+can|users?\s+can|system\s+can)\s+",
        "",
        s,
        flags=re.I,
    )
    # Cut at relative clause markers that make names too long
    s = re.split(r"\b(?:when|where|that|which|if|because|only when)\b", s, maxsplit=1, flags=re.I)[0]
    s = s.strip(" ,;:-")
    # Title-ish cleanup: keep original casing if mixed, else title case short names
    if s.isupper() and len(s) > 3:
        s = s.title()
    elif s == s.lower() and any(c.isalpha() for c in s):
        # Title-case plain lowercase phrases; keep mixed/acronym casing as authored
        s = s.title()
    if len(s) > 72:
        s = s[:69].rstrip() + "…"
    return s


def _shorten_failure_name(name: str) -> str:
    # Prefer noun phrase before "are/is"
    m = re.match(r"^(.+?)\s+(?:are|is)\b", name, re.I)
    if m:
        return _clean_node_name(m.group(1))
    return name


def _match_section_header(text: str) -> tuple[NodeType, dict] | None:
    t = text.strip().rstrip(":")
    for pat, ntype, extra in _SECTION_HINTS:
        if pat.fullmatch(t) or pat.search(t) and len(t) < 40:
            if ntype is None:
                return None
            return ntype, dict(extra)
    return None


def _guess_root_from_preamble(lines: list[str]) -> str | None:
    for ln in lines:
        m = _ROOT_RE.match(ln)
        if m:
            return _clean_node_name(m.group("root"))
        rel = _RELATION_RE.match(ln)
        if rel:
            return _clean_node_name(rel.group("sub"))
        # "ShopEase Ecommerce is a simple online store..."
        m2 = re.match(r"^([A-Z][\w][\w\s\-_/]{1,48}?)\s+is\s+(?:a|an|the)\b", ln)
        if m2:
            return _clean_node_name(m2.group(1))
    if lines:
        return _subject_of_sentence(lines[0])
    return None


def _subject_of_sentence(sent: str) -> str | None:
    rel = _RELATION_RE.match(sent.strip())
    if rel:
        return _clean_node_name(rel.group("sub"))
    m = re.match(r"^([A-Z][\w][\w\s+\-/]{0,48}?)(?:\s+(?:is|are|supports|has|includes)\b|,)", sent)
    if m:
        return _clean_node_name(m.group(1))
    tokens = sent.split()
    if tokens:
        return _clean_node_name(" ".join(tokens[:4]))
    return None


def _names_match(a: str, b: str) -> bool:
    x, y = a.strip().lower(), b.strip().lower()
    if not x or not y:
        return False
    if x == y:
        return True
    # Soft match: shorter may be a prefix token of longer ("Email" ~ "Email login"),
    # but not a trailing substring ("Checkout" must NOT match "guest checkout").
    shorter, longer = (x, y) if len(x) <= len(y) else (y, x)
    if len(shorter) < 4:
        return False
    if longer.startswith(shorter) and (
        len(longer) == len(shorter) or longer[len(shorter)] in " \t+-/(:|"
    ):
        return True
    return False


def _title_case_token(s: str) -> str:
    return _clean_node_name(s) or "Feature"


def _trim_desc(raw: str, name: str) -> str:
    if raw.strip().lower() == name.strip().lower():
        return ""
    return raw.strip()[:240]


def _fallback_phrases(text: str, root_name: str) -> list[str]:
    lower = text.lower()
    catalog = [
        ("guest checkout", "Guest Checkout"),
        ("registered user", "Registered User"),
        ("payment", "Payment"),
        ("address validation", "Address Validation"),
        ("email password", "Email + Password"),
        ("google oauth", "Google OAuth"),
        ("self registration", "Self Registration"),
        ("mfa", "MFA"),
        ("forgot password", "Forgot Password"),
        ("account lockout", "Account Lockout"),
        ("shopping cart", "Shopping Cart"),
        ("product catalog", "Product Catalog"),
        ("checkout", "Checkout"),
        ("sign in", "Sign In"),
    ]
    out: list[str] = []
    for needle, label in catalog:
        if needle in lower and not _names_match(label, root_name):
            out.append(label)
    return out[:12]
