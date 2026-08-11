"""
dompruner-py load test

세 가지 시나리오를 검증한다:

  1. Cache thrash   — 동일 URL에 N개 코루틴이 동시 요청 → 1회 fetch + 나머지 캐시 히트
  2. Batch load     — 실제 URL 목록을 DomPrunerBatchLoader로 병렬 수집 → 처리량 측정
  3. Memory bound   — maxsize(256)를 초과하는 URL 수를 캐시해도 메모리가 상한을 지키는지 확인

Usage:
    uv run python loadtest.py
"""
from __future__ import annotations

import asyncio
import sys
import time
import tracemalloc
from unittest.mock import AsyncMock, patch

sys.path.insert(0, ".")
from dompruner import PipelineResult, get_cache, run_pipeline
from dompruner.langchain import DomPrunerBatchLoader

# ── 공통 픽스처 ───────────────────────────────────────────────────────────────

def _fake_result(url: str) -> PipelineResult:
    """네트워크 없이 캐시·동시성 로직만 검증하기 위한 더미 결과."""
    return PipelineResult(
        url=url,
        render_type="SSR",
        markdown=f"# {url}\n\n" + "content " * 200,   # ~6KB 수준
        original_tokens=10_000,
        refined_tokens=400,
        reduction_ratio=0.96,
        fetch_ms=50.0,
        parse_ms=5.0,
    )


# ── 시나리오 1: Cache thrash ──────────────────────────────────────────────────

async def scenario_cache_thrash(concurrency: int = 30) -> None:
    """
    같은 URL에 30개 코루틴이 동시 요청.
    기대: single-flight로 fetch는 정확히 1회, 나머지는 Future 대기 후 캐시 히트.
    """
    print(f"\n{'─'*60}")
    print(f"[Scenario 1] Cache thrash — {concurrency} concurrent requests / same URL")

    get_cache().clear()
    target_url = "https://example.com/docs/api"
    fetch_count = 0

    async def fake_fetch_page(url: str) -> object:
        nonlocal fetch_count
        fetch_count += 1
        await asyncio.sleep(0.05)   # 네트워크 지연 시뮬레이션
        from dompruner.fetcher import FetchResult
        return FetchResult(url=url, html="<html><body><p>" + "word " * 300 + "</p></body></html>",
                           render_type="SSR", ssg_payload=None)

    t0 = time.perf_counter()
    with patch("dompruner.pipeline.fetch_page", side_effect=fake_fetch_page):
        tasks = [run_pipeline(target_url) for _ in range(concurrency)]
        results = await asyncio.gather(*tasks)
    elapsed = (time.perf_counter() - t0) * 1000

    cache_hits = sum(1 for r in results if r.cached)
    print(f"  Total requests : {concurrency}")
    print(f"  Actual fetches : {fetch_count}  (expected = 1, single-flight)")
    print(f"  Cache hits     : {cache_hits}")
    print(f"  Elapsed        : {elapsed:.0f}ms")
    print(f"  Cache stats    : {get_cache().stats}")

    # Semaphore + double-check: fetch는 1회, 나머지는 캐시 히트
    assert fetch_count == 1, f"Semaphore+double-check failed: {fetch_count} fetches (expected 1)"
    print("  ✅ PASS")


# ── 시나리오 2: Batch load 처리량 ────────────────────────────────────────────

async def scenario_batch_throughput(n_urls: int = 20, concurrency: int = 5) -> None:
    """
    20개 URL을 BatchLoader로 병렬 fetch.
    기대: concurrency=5 제한이 지켜지면서 순차 대비 빠른 처리.
    """
    print(f"\n{'─'*60}")
    print(f"[Scenario 2] Batch throughput — {n_urls} URLs, concurrency={concurrency}")

    get_cache().clear()
    urls = [f"https://example.com/page/{i}" for i in range(n_urls)]
    active_count = 0
    max_active = 0

    async def fake_fetch(url: str, query: str = "") -> PipelineResult:
        nonlocal active_count, max_active
        active_count += 1
        max_active = max(max_active, active_count)
        await asyncio.sleep(0.05)               # 50ms fetch 시뮬레이션
        active_count -= 1
        result = _fake_result(url)
        await get_cache().set(url, query, result)
        return result

    loader = DomPrunerBatchLoader(urls, concurrency=concurrency)

    t0 = time.perf_counter()
    with patch("dompruner.langchain.batch_loader.run_pipeline", side_effect=fake_fetch):
        docs = []
        async for doc in loader.alazy_load():
            docs.append(doc)
    elapsed = (time.perf_counter() - t0) * 1000

    sequential_estimate = n_urls * 50          # 순차라면 20 × 50ms = 1000ms
    print(f"  URLs loaded        : {len(docs)} / {n_urls}")
    print(f"  Max concurrent     : {max_active}  (limit={concurrency})")
    print(f"  Elapsed            : {elapsed:.0f}ms")
    print(f"  Sequential estimate: {sequential_estimate}ms")
    print(f"  Speedup            : {sequential_estimate / elapsed:.1f}×")

    assert len(docs) == n_urls,        f"Missing docs: {len(docs)}"
    assert max_active <= concurrency,  f"Concurrency exceeded: {max_active} > {concurrency}"
    print("  ✅ PASS")


# ── 시나리오 3: Memory bound ──────────────────────────────────────────────────

async def scenario_memory_bound(n_urls: int = 300) -> None:
    """
    maxsize(256)를 초과하는 300개 URL을 캐시.
    기대: 캐시 엔트리는 256개로 유지, 메모리는 ~4MB 이하.
    """
    print(f"\n{'─'*60}")
    print(f"[Scenario 3] Memory bound — caching {n_urls} URLs (maxsize=256)")

    get_cache().clear()
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for i in range(n_urls):
        url = f"https://example.com/article/{i}"
        result = _fake_result(url)
        await get_cache().set(url, "", result)

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_diff_kb = sum(s.size_diff for s in stats) / 1024

    cache_size = get_cache().size
    print(f"  URLs inserted  : {n_urls}")
    print(f"  Cache entries  : {cache_size}  (maxsize=256)")
    print(f"  Memory delta   : {total_diff_kb:.0f} KB")
    print(f"  Cache stats    : {get_cache().stats}")

    assert cache_size <= 256, f"Cache exceeded maxsize: {cache_size}"
    assert total_diff_kb < 4_096, f"Memory too high: {total_diff_kb:.0f} KB"
    print("  ✅ PASS")


# ── 실행 ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("dompruner-py load test")
    print("=" * 60)

    await scenario_cache_thrash(concurrency=30)
    await scenario_batch_throughput(n_urls=20, concurrency=5)
    await scenario_memory_bound(n_urls=300)

    print(f"\n{'='*60}")
    print("All scenarios passed ✅")


if __name__ == "__main__":
    asyncio.run(main())
