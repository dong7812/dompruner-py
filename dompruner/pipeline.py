from __future__ import annotations

import time
from dataclasses import dataclass

from .bm25 import bm25_filter
from .extractor import extract_content
from .fetcher import FetchResult, fetch_page
from .serializer import estimate_tokens, serialize
from .ssg import extract_ssg_markdown


@dataclass
class PipelineResult:
    url: str
    render_type: str
    markdown: str
    original_tokens: int
    refined_tokens: int
    reduction_ratio: float
    fetch_ms: float
    parse_ms: float
    bm25_confidence: float | None = None


async def run_pipeline(url: str, query: str = "") -> PipelineResult:
    t0 = time.perf_counter()
    fetched: FetchResult = await fetch_page(url)
    fetch_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    original_tokens = estimate_tokens(fetched.html)
    bm25_confidence: float | None = None
    render_type = fetched.render_type

    if fetched.render_type == "SSG" and fetched.ssg_payload is not None:
        ssg = extract_ssg_markdown(fetched.ssg_payload)
        if ssg is not None:
            # SSG RSC walk succeeded — apply BM25 on top if query given
            markdown = ssg["markdown"]
            if query:
                nodes = extract_content(fetched.html)
                nodes, bm25_confidence = bm25_filter(nodes, query)
                if bm25_confidence and bm25_confidence > 0:
                    markdown = serialize(nodes)
        else:
            # RSC structure unknown — fall through to DOM extraction
            render_type = "SSR"
            nodes = extract_content(fetched.html)
            if query:
                nodes, bm25_confidence = bm25_filter(nodes, query)
            markdown = serialize(nodes)
    else:
        nodes = extract_content(fetched.html)
        if query:
            nodes, bm25_confidence = bm25_filter(nodes, query)
        markdown = serialize(nodes)

    parse_ms = (time.perf_counter() - t1) * 1000
    refined_tokens = estimate_tokens(markdown)

    return PipelineResult(
        url=fetched.url,
        render_type=render_type,
        markdown=markdown,
        original_tokens=original_tokens,
        refined_tokens=refined_tokens,
        reduction_ratio=1 - refined_tokens / max(original_tokens, 1),
        fetch_ms=fetch_ms,
        parse_ms=parse_ms,
        bm25_confidence=bm25_confidence,
    )
