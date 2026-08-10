"""
SSG Extractor — Python port of ssg-extractor.ts

Walks React Server Components (RSC) tuple tree extracted from __NEXT_DATA__
and converts it to Markdown. Returns None to signal DOM fallback.
"""
from __future__ import annotations

import json
import re
from typing import Any


# Layout wrappers: recurse into children transparently
_PASS_THROUGH_TAGS = {
    "MaxWidth", "Intro", "Note", "Callout", "CanaryBadge", "Canary",
    "Deprecated", "Experimental", "Added", "Wip", "CodeStep",
    "div", "section", "article", "main", "aside", "header", "footer",
    "nav", "figure", "figcaption", "details", "summary",
}

# Tags that produce no output
_SKIP_TAGS = {"InlineToc", "Meta", "SandpackWithHTMLOutput"}

# Inline HTML tags
_INLINE_TAGS = {"code", "strong", "b", "em", "i", "a", "span", "small", "sup", "sub", "mark"}


def _is_rsc_tuple(v: object) -> bool:
    """Check for RSC tuple: [marker_starting_$, tag_str, key, props_dict_or_None]"""
    if not isinstance(v, list) or len(v) < 4:
        return False
    marker, tag, _, props = v[0], v[1], v[2], v[3]
    if not isinstance(marker, str) or not marker.startswith("$"):
        return False
    if not isinstance(tag, str):
        return False
    if props is not None and not isinstance(props, dict):
        return False
    return True


def _render_inline(node: Any) -> str:
    if isinstance(node, str):
        return node
    if node is None or isinstance(node, bool):
        return ""
    if isinstance(node, (int, float)):
        return ""
    if not isinstance(node, list):
        return ""

    if _is_rsc_tuple(node):
        tag: str = node[1]
        props: dict = node[3] or {}
        ch = props.get("children")
        if tag == "code":
            return f"`{_render_inline(ch)}`"
        if tag in ("strong", "b"):
            return f"**{_render_inline(ch)}**"
        if tag in ("em", "i"):
            return f"_{_render_inline(ch)}_"
        if tag == "a":
            return _render_inline(ch)
        return _render_inline(ch if ch is not None else "")

    return "".join(_render_inline(child) for child in node)


def _render_block(node: Any, list_depth: int = 0) -> list[str]:
    if isinstance(node, str):
        t = node.strip()
        return [t] if t else []
    if node is None or isinstance(node, bool):
        return []
    if isinstance(node, (int, float)):
        return []
    if not isinstance(node, list):
        return []

    if not _is_rsc_tuple(node):
        out: list[str] = []
        for child in node:
            out.extend(_render_block(child, list_depth))
        return out

    tag: str = node[1]
    props: dict = node[3] or {}
    ch = props.get("children")

    if tag in _SKIP_TAGS:
        return []

    if tag in _PASS_THROUGH_TAGS:
        return _render_block(ch, list_depth)

    if tag in _INLINE_TAGS:
        text = _render_inline(node).strip()
        return [text] if text else []

    if tag == "h1":
        return [f"# {_render_inline(ch).strip()}"]
    if tag == "h2":
        return [f"## {_render_inline(ch).strip()}"]
    if tag == "h3":
        return [f"### {_render_inline(ch).strip()}"]
    if tag in ("h4", "h5"):
        return [f"#### {_render_inline(ch).strip()}"]

    if tag == "p":
        text = _render_inline(ch).strip()
        return [text] if text else []

    if tag == "pre":
        lang = ""
        code = ""
        if _is_rsc_tuple(ch):
            code_props: dict = ch[3] or {}
            cls = code_props.get("className") or ""
            lang = cls.replace("language-", "")
            inner = code_props.get("children")
            code = inner if isinstance(inner, str) else _render_inline(inner)
        else:
            code = _render_inline(ch)
        return [f"```{lang}", code.rstrip(), "```"]

    if tag in ("ul", "ol"):
        return _render_block(ch, list_depth)

    if tag == "li":
        inner = _render_inline(ch).strip()
        return [f"{'  ' * list_depth}- {inner}"] if inner else []

    if tag == "blockquote":
        return [f"> {line}" for line in _render_block(ch, list_depth)]

    if tag == "hr":
        return ["---"]
    if tag == "br":
        return [""]

    # Unknown — recurse
    return _render_block(ch, list_depth)


def _dedup(lines: list[str]) -> list[str]:
    """Collapse consecutive blank lines."""
    out: list[str] = []
    prev_blank = False
    for line in lines:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        out.append(line)
        prev_blank = blank
    return out


def _get_nextjs_rsc_content(payload: Any) -> Any:
    try:
        page_props = payload.get("props", {}).get("pageProps")
        if not page_props:
            return None
        raw = page_props.get("content")
        if isinstance(raw, str):
            return json.loads(raw)
        if raw is not None:
            return raw
        return None
    except Exception:
        return None


def _get_meta_desc(payload: Any) -> str:
    try:
        page_props = payload.get("props", {}).get("pageProps", {})
        return page_props.get("description") or ""
    except Exception:
        return ""


def extract_ssg_markdown(ssg_payload: Any) -> dict | None:
    """
    Returns dict(markdown, title, meta_desc) or None to signal DOM fallback.
    """
    try:
        return _extract_ssg_markdown(ssg_payload)
    except Exception:
        return None


def _extract_ssg_markdown(ssg_payload: Any) -> dict | None:
    content = _get_nextjs_rsc_content(ssg_payload)
    if content is None:
        return None

    raw_lines = _render_block(content)
    lines = _dedup(raw_lines)
    markdown = "\n".join(lines).strip()

    if not markdown or len(markdown) < 100:
        return None

    heading_re = re.compile(r"^(#{1,3}) (.+)")
    anchors = []
    for line in lines:
        m = heading_re.match(line)
        if m:
            level = len(m.group(1))
            anchors.append({"level": level, "text": m.group(2).strip()})

    title = next((a["text"] for a in anchors if a["level"] == 1), None)
    title = title or (anchors[0]["text"] if anchors else "")
    meta_desc = _get_meta_desc(ssg_payload)

    return {"markdown": markdown, "title": title, "meta_desc": meta_desc}
