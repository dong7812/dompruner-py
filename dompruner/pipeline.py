from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .bm25 import bm25_filter
from .cache import LRUTTLCache
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
    cached: bool = False


# 프로세스 전역 캐시 — 같은 세션 내 중복 fetch 방지
# maxsize=256 → ~1.5MB 상한 / ttl=300 → 5분 유효
_cache: LRUTTLCache[PipelineResult] = LRUTTLCache(maxsize=256, ttl=300.0)

# Per-key Semaphore — Thundering herd 방지
# 동일 (url, query) 키에 대해 Semaphore(1)를 걸어 fetch를 직렬화한다.
# 첫 번째 코루틴: fetch → 캐시 저장 → 잠금 해제
# 이후 코루틴: 잠금 획득 → double-check에서 캐시 히트 → 즉시 반환
# trade-off 상세: docs/decisions/thundering-herd.md
_key_sems: dict[str, asyncio.Semaphore] = {}


def get_cache() -> LRUTTLCache[PipelineResult]:
    """전역 캐시 인스턴스 반환. 통계 조회나 수동 clear에 사용."""
    return _cache


def _make_key(url: str, query: str) -> str:
    return f"{url}\x00{query}"


def _as_cached(r: PipelineResult) -> PipelineResult:
    return PipelineResult(
        url=r.url, render_type=r.render_type, markdown=r.markdown,
        original_tokens=r.original_tokens, refined_tokens=r.refined_tokens,
        reduction_ratio=r.reduction_ratio, fetch_ms=0.0, parse_ms=0.0,
        bm25_confidence=r.bm25_confidence, cached=True,
    )


async def run_pipeline(url: str, query: str = "") -> PipelineResult:
    # 1. 빠른 경로: 캐시 히트 시 락 없이 즉시 반환
    hit = _cache.get(url, query)
    if hit is not None:
        return _as_cached(hit)

    # 2. Per-key Semaphore 획득
    key = _make_key(url, query)
    if key not in _key_sems:
        _key_sems[key] = asyncio.Semaphore(1)

    async with _key_sems[key]:
        # 3. Double-check: 락 대기 중 다른 코루틴이 캐시를 채웠을 수 있음
        hit = _cache.get(url, query)
        if hit is not None:
            return _as_cached(hit)

        # 4. 실제 fetch — 이 시점에서 이 키의 fetch는 1개만 실행됨
        result = await _do_fetch(url, query)
        await _cache.set(url, query, result)
        return result


async def _do_fetch(url: str, query: str) -> PipelineResult:
    """실제 fetch·parse 실행. run_pipeline의 semaphore 보호 아래 호출된다."""
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
            markdown = ssg["markdown"]
            if query:
                nodes = extract_content(fetched.html)
                nodes, bm25_confidence = bm25_filter(nodes, query)
                if bm25_confidence and bm25_confidence > 0:
                    markdown = serialize(nodes)
        else:
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
        cached=False,
    )
