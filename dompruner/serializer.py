from __future__ import annotations

from .extractor import FQNNode

_HEADING_PREFIX = {
    "h1": "# ", "h2": "## ", "h3": "### ",
    "h4": "#### ", "h5": "##### ",
}


def serialize(nodes: list[FQNNode]) -> str:
    parts: list[str] = []
    for node in nodes:
        text = node.text.strip()
        if not text:
            continue
        tag = node.tag
        if tag in _HEADING_PREFIX:
            parts.append(f"{_HEADING_PREFIX[tag]}{text}")
        elif tag in ("pre", "code"):
            lang = node.code_lang or ""
            parts.append(f"```{lang}\n{text}\n```")
        elif tag == "li":
            parts.append(f"- {text}")
        elif tag == "blockquote":
            parts.append(f"> {text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
