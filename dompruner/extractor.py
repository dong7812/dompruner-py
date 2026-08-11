"""
Content Extractor — L1 → L2 → L3 오케스트레이터 (Python port of dompruner-mcp)

L1: FQN Router      — NOISE_TAGS 기반 subtree prune + content 추출
L2: Heading Cluster — 개발 문서 특화 (H2-H4 앵커 + link density 검증)
L3: CETD Engine     — 텍스트 밀도 기반 최고 컨테이너 선택
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

# ── Tag sets ──────────────────────────────────────────────────────────────────

_NOISE_TAGS = {
    "script", "style", "nav", "footer", "header", "aside",
    "noscript", "iframe", "form", "head", "button", "svg",
}

_CONTENT_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5",
    "li", "blockquote", "pre", "code",
}

_TABLE_TAGS = {"table"}

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5"}
_DEV_HEADING_TAGS = {"h2", "h3", "h4"}
_CLUSTER_BOUNDARY_TAGS = {"h1", "h2", "h3", "h4"}

_CONTAINER_TAGS = {"article", "main", "section", "div", "td"}
_INLINE_TAGS = {"a", "strong", "em", "b", "i", "code", "span", "small"}

_NOISE_ROLES = {"navigation", "menu", "menubar", "banner", "complementary", "search"}
_NOISE_CLASS_RE = re.compile(
    r"\b(skip-link|skip-to|breadcrumb|cookie-banner|cookie-notice|"
    r"advertisement|ad-container|popup|modal-overlay|topbar|toolbar)\b",
    re.IGNORECASE,
)
_BOILERPLATE_RE = [
    re.compile(r"^skip (to|navigation|main|content)", re.IGNORECASE),
    re.compile(r"^jump to (content|main|navigation)", re.IGNORECASE),
    re.compile(r"^go to (main content|content|navigation)", re.IGNORECASE),
]


@dataclass
class FQNNode:
    tag: str
    text: str
    depth: int
    href: str | None = None
    code_lang: str | None = None
    cells: list[str] | None = None  # populated for tag="table_row"
    is_header: bool = False          # True when the row came from <thead> or contains <th>


# ── Public API ────────────────────────────────────────────────────────────────

def extract_content(html: str) -> list[FQNNode]:
    """Parse HTML and extract content nodes. Public API — accepts raw HTML string."""
    return _extract_content_from_soup(BeautifulSoup(html, "html.parser"))


def extract_meta(html: str) -> dict[str, str]:
    """Extract page-level metadata from DOM-native tags (<meta>, <title>, <link>, <html lang>).

    JSON-LD is intentionally excluded — it lives inside <script> and is not part of the
    DOM content tree that dompruner operates on.

    Returns only keys that have a non-empty value; missing fields are omitted.
    """
    return _extract_meta_from_soup(BeautifulSoup(html, "html.parser"))


def extract_content_and_meta(html: str) -> tuple[list[FQNNode], dict[str, str]]:
    """Parse HTML once and return both content nodes and metadata.

    Use this in pipeline code to avoid parsing the same HTML twice.
    """
    soup = BeautifulSoup(html, "html.parser")
    return _extract_content_from_soup(soup), _extract_meta_from_soup(soup)


def _extract_content_from_soup(soup: BeautifulSoup) -> list[FQNNode]:
    layer1 = _fqn_route(soup)
    if _has_coverage(layer1):
        return layer1

    layer2 = _cluster_by_headings(soup)
    if layer2 is not None and _has_coverage(layer2):
        return layer2

    layer3 = _cetd_extract(soup)
    if layer3:
        return layer3

    return layer1 if layer1 else (layer2 or [])


def _extract_meta_from_soup(soup: BeautifulSoup) -> dict[str, str]:
    meta: dict[str, str] = {}

    # <title> tag — highest priority for title
    title_tag = soup.find("title")
    if isinstance(title_tag, Tag):
        t = title_tag.get_text(strip=True)
        if t:
            meta["title"] = t

    # <html lang="...">
    html_tag = soup.find("html")
    if isinstance(html_tag, Tag):
        lang = html_tag.get("lang", "")
        if lang:
            meta["lang"] = str(lang).strip()

    # <link rel="canonical">
    canonical = soup.find("link", attrs={"rel": "canonical"})
    if isinstance(canonical, Tag):
        href = canonical.get("href", "")
        if href:
            meta["canonical_url"] = str(href).strip()

    # <meta> and <meta property="og:..."> — checked in priority order per field
    _META_SELECTORS: list[tuple[str, list[tuple[str, str]]]] = [
        ("title",          [("property", "og:title")]),                          # <title> already handled above
        ("description",    [("name", "description"), ("property", "og:description")]),
        ("author",         [("name", "author"), ("property", "article:author")]),
        ("published_time", [("property", "article:published_time")]),
        ("modified_time",  [("property", "article:modified_time")]),
        ("site_name",      [("property", "og:site_name")]),
    ]
    for key, selectors in _META_SELECTORS:
        if key in meta:
            continue
        for attr, val in selectors:
            el = soup.find("meta", attrs={attr: val})
            if isinstance(el, Tag):
                content = str(el.get("content", "")).strip()
                if content:
                    meta[key] = content
                    break

    return meta


def _collect_fqn_nodes(root: Tag) -> list[FQNNode]:
    """Shared walk used by L1 and L3: prunes NOISE_TAGS, stops at CONTENT_TAGS."""
    results: list[FQNNode] = []
    seen: set[str] = set()

    def walk(el: Tag, depth: int) -> None:
        if not isinstance(el, Tag):
            return
        tag = el.name
        if tag in _NOISE_TAGS:
            return
        if tag not in _CONTENT_TAGS and tag not in _TABLE_TAGS and _is_noise(el):
            return
        if tag in _TABLE_TAGS:
            results.extend(_collect_table_rows(el, depth))
            return  # don't recurse; table handler owns its subtree
        if tag in _CONTENT_TAGS:
            text = _extract_text(el)
            min_len = 3 if tag in _HEADING_TAGS else 10
            if len(text) >= min_len and not _is_boilerplate(text) and text not in seen:
                seen.add(text)
                code_lang = None
                if tag == "pre":
                    # Check <pre> class first, then fall back to inner <code> class.
                    # Many syntax highlighters (e.g. highlight.js, Prism) put
                    # language-xxx on the <code> child rather than <pre> itself.
                    cls = " ".join(el.get("class", []))
                    code_child = el.find("code")
                    if isinstance(code_child, Tag):
                        cls = cls + " " + " ".join(code_child.get("class", []))
                    m = re.search(r"language-(\w+)", cls)
                    code_lang = m.group(1) if m else None
                results.append(FQNNode(tag=tag, text=text, depth=depth, code_lang=code_lang))
            return  # stop: don't recurse into CONTENT_TAG children
        for child in el.children:
            if isinstance(child, Tag):
                walk(child, depth + 1)

    walk(root, 0)
    return results


def _collect_table_rows(table_el: Tag, depth: int) -> list[FQNNode]:
    """Convert a <table> element into table_row FQNNodes (one per <tr>)."""
    rows: list[FQNNode] = []
    for tr in table_el.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        parent = tr.parent
        is_header = (isinstance(parent, Tag) and parent.name == "thead") or bool(tr.find("th"))
        cells = [
            cell.get_text(" ", strip=True)
            for cell in tr.find_all(["td", "th"])
            if isinstance(cell, Tag)
        ]
        if not any(cells):
            continue
        rows.append(FQNNode(
            tag="table_row",
            text=" | ".join(cells),
            depth=depth,
            cells=cells,
            is_header=is_header,
        ))
    return rows


# ── Shared helpers ────────────────────────────────────────────────────────────

def _has_coverage(nodes: list[FQNNode]) -> bool:
    return len(nodes) >= 4 and sum(len(n.text) for n in nodes) >= 200


def _is_noise(tag: Tag) -> bool:
    if not isinstance(tag, Tag):
        return False
    role = tag.get("role", "")
    if role in _NOISE_ROLES:
        return True
    cls = " ".join(tag.get("class", []))
    id_ = tag.get("id", "")
    if _NOISE_CLASS_RE.search(f"{cls} {id_}"):
        return True
    aria = (tag.get("aria-label") or "").lower()
    if aria in ("navigation", "breadcrumb", "table of contents"):
        return True
    return False


def _extract_text(el: Tag) -> str:
    return el.get_text(" ", strip=True)


def _is_boilerplate(text: str) -> bool:
    t = text.strip()
    return any(r.match(t) for r in _BOILERPLATE_RE)


def _link_text_len(el: Tag) -> int:
    return sum(len(a.get_text()) for a in el.find_all("a"))


# ── L1: FQN Router ───────────────────────────────────────────────────────────

def _fqn_route(soup: BeautifulSoup) -> list[FQNNode]:
    body = soup.find("body") or soup
    return _collect_fqn_nodes(body)


# ── L2: Heading Cluster ───────────────────────────────────────────────────────

def _cluster_by_headings(soup: BeautifulSoup) -> list[FQNNode] | None:
    container = soup.find("main") or soup.find("article") or soup

    # find role="main"
    if container is soup:
        for el in soup.find_all(True):
            if isinstance(el, Tag) and el.get("role") == "main":
                container = el
                break

    blocks = _extract_flat_blocks(container)
    if not blocks:
        return None

    clusters = _group_clusters(blocks)

    dev_headings = [c for c in clusters if c["heading"] and c["heading"].tag in _DEV_HEADING_TAGS]
    if len(dev_headings) < 2:
        return None

    avg_text = sum(c["total_text"] for c in dev_headings) / len(dev_headings)
    if avg_text < 400:
        return None

    good = [
        c for c in clusters
        if c["total_text"] > 0 and c["total_link"] / c["total_text"] < 0.3
    ]
    if not good:
        return None

    result: list[FQNNode] = []
    for c in good:
        if c["heading"]:
            result.append(c["heading"])
        result.extend(c["blocks"])

    return result if len(result) >= 3 else None


def _extract_flat_blocks(container) -> list[dict]:
    results = []

    def walk(el: Tag, depth: int) -> None:
        if not isinstance(el, Tag):
            return
        tag = el.name
        if tag in _NOISE_TAGS or _is_noise(el):
            return
        if tag in _CONTENT_TAGS:
            text = _extract_text(el)
            min_len = 2 if tag in _HEADING_TAGS else 10
            if len(text) >= min_len:
                results.append({
                    "node": FQNNode(tag=tag, text=text, depth=depth),
                    "link_len": _link_text_len(el),
                })
            return
        for child in el.children:
            if isinstance(child, Tag):
                walk(child, depth + 1)

    walk(container, 0)
    return results


def _group_clusters(blocks: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    cur: dict = {"heading": None, "blocks": [], "total_text": 0, "total_link": 0}

    for b in blocks:
        node: FQNNode = b["node"]
        if node.tag in _CLUSTER_BOUNDARY_TAGS:
            if cur["blocks"] or cur["heading"]:
                clusters.append(cur)
            cur = {
                "heading": node,
                "blocks": [],
                "total_text": len(node.text),
                "total_link": b["link_len"],
            }
        else:
            cur["blocks"].append(node)
            cur["total_text"] += len(node.text)
            cur["total_link"] += b["link_len"]

    if cur["blocks"] or cur["heading"]:
        clusters.append(cur)
    return clusters


# ── L3: CETD Engine ───────────────────────────────────────────────────────────

def _cetd_extract(soup: BeautifulSoup) -> list[FQNNode]:
    best_el: Tag | None = None
    best_score = -1.0

    for el in soup.find_all(_CONTAINER_TAGS):
        if not isinstance(el, Tag) or _is_noise(el):
            continue
        text_len = len(el.get_text(strip=True))
        if text_len < 200:
            continue
        tags = el.find_all(True)
        tag_count = sum(0.5 if t.name in _INLINE_TAGS else 1.0 for t in tags)
        tag_count = max(tag_count, 1)
        link_len = _link_text_len(el)
        link_ratio = link_len / text_len if text_len > 0 else 1.0
        depth = len(list(el.parents))
        depth_penalty = max(0.0, 1 - depth * 0.04)
        score = (text_len / tag_count) * (1 - link_ratio) * depth_penalty
        if score > best_score:
            best_score = score
            best_el = el

    if not best_el:
        return []

    # Reuse the same pruning walk so code-inside-p and code_lang are handled correctly
    return _collect_fqn_nodes(best_el)
