from __future__ import annotations

from .extractor import FQNNode

_HEADING_PREFIX = {
    "h1": "# ", "h2": "## ", "h3": "### ",
    "h4": "#### ", "h5": "##### ",
}


def _render_table(rows: list[FQNNode]) -> str:
    lines: list[str] = []
    for row in rows:
        cells = row.cells or [row.text]
        lines.append("| " + " | ".join(cells) + " |")
        if row.is_header:
            lines.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(lines)


def serialize(nodes: list[FQNNode]) -> str:
    parts: list[str] = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if node.tag == "table_row":
            table_rows: list[FQNNode] = []
            while i < len(nodes) and nodes[i].tag == "table_row":
                table_rows.append(nodes[i])
                i += 1
            parts.append(_render_table(table_rows))
            continue

        text = node.text.strip()
        if text:
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
        i += 1

    return "\n\n".join(parts)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
