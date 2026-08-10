from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Plus

from .extractor import FQNNode

_TOKEN_RE = re.compile(r"[\s\W]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.split(text.lower()) if len(t) >= 2]


@dataclass
class Section:
    heading: FQNNode | None
    nodes: list[FQNNode]
    token_count: int
    depth: int


def group_sections(nodes: list[FQNNode]) -> list[Section]:
    sections: list[Section] = []
    current = Section(heading=None, nodes=[], token_count=0, depth=999)

    for node in nodes:
        if node.tag in ("h1", "h2", "h3", "h4", "h5"):
            if current.nodes or current.heading:
                sections.append(current)
            current = Section(
                heading=node,
                nodes=[],
                token_count=len(tokenize(node.text)),
                depth=int(node.tag[1]),
            )
        else:
            current.nodes.append(node)
            current.token_count += len(tokenize(node.text))
            current.depth = min(current.depth, node.depth)

    if current.nodes or current.heading:
        sections.append(current)
    return sections


def bm25_filter(
    nodes: list[FQNNode],
    query: str,
    token_budget: int = 1_200,
    heading_boost: float = 2.5,
    depth_decay: float = 0.4,
    min_sections: int = 2,
) -> tuple[list[FQNNode], float]:
    if not query.strip():
        return nodes, 0.0

    sections = group_sections(nodes)
    if len(sections) <= min_sections:
        return nodes, 0.0

    total = sum(s.token_count for s in sections)
    if total <= token_budget:
        return nodes, 0.0

    query_terms = tokenize(query)
    if not query_terms:
        return nodes, 0.0

    body_corpora = [tokenize(" ".join(n.text for n in s.nodes)) for s in sections]
    heading_corpora = [tokenize(s.heading.text if s.heading else "") for s in sections]

    body_bm25 = BM25Plus(body_corpora)
    heading_bm25 = BM25Plus(heading_corpora)

    body_scores = body_bm25.get_scores(query_terms)
    heading_scores = heading_bm25.get_scores(query_terms)

    depths = [s.depth if s.depth < 999 else 0 for s in sections]
    min_d, max_d = min(depths), max(depths)
    depth_range = max(1, max_d - min_d)

    scored = []
    for i, section in enumerate(sections):
        depth_w = 1.0 - depth_decay * ((depths[i] - min_d) / depth_range)
        score = body_scores[i] * depth_w + heading_boost * heading_scores[i]
        scored.append((i, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    max_score = scored[0][1] if scored else 0.0

    # zero-score fallback: query terms appear nowhere
    if max_score == 0:
        return nodes, 0.0

    # ancestor preservation
    ancestor_map = _build_ancestor_map(sections)

    selected: set[int] = set()
    used = 0
    for i, _ in scored:
        if used + sections[i].token_count > token_budget and len(selected) >= min_sections:
            break
        selected.add(i)
        used += sections[i].token_count

    for idx in list(selected):
        for ancestor in ancestor_map.get(idx, []):
            selected.add(ancestor)

    result: list[FQNNode] = []
    for i, section in enumerate(sections):
        if i not in selected:
            continue
        if section.heading:
            result.append(section.heading)
        result.extend(section.nodes)

    return result, max_score


def _build_ancestor_map(sections: list[Section]) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    stack: list[tuple[int, int]] = []  # (level, idx)

    for i, section in enumerate(sections):
        level = int(section.heading.tag[1]) if section.heading else 99
        while stack and stack[-1][0] >= level:
            stack.pop()
        result[i] = [idx for _, idx in stack]
        if section.heading:
            stack.append((level, i))

    return result
