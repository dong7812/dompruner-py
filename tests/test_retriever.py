"""Tests for DomPrunerRetriever."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from dompruner.pipeline import PipelineResult
from dompruner.langchain import DomPrunerRetriever


def _fake_result(url: str, bm25: float = 2.5) -> PipelineResult:
    return PipelineResult(
        url=url,
        render_type="SSR",
        markdown=f"# {url}\n\nContent.",
        original_tokens=1000,
        refined_tokens=50,
        reduction_ratio=0.95,
        fetch_ms=100.0,
        parse_ms=10.0,
        bm25_confidence=bm25,
        cached=False,
        meta={"title": f"Page: {url}", "lang": "en"},
    )


URLS = [
    "https://example.com/page-1",
    "https://example.com/page-2",
    "https://example.com/page-3",
]


@pytest.mark.asyncio
async def test_retriever_returns_all_urls():
    async def fake_pipeline(url, query=""):
        return _fake_result(url)

    retriever = DomPrunerRetriever(urls=URLS)
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        docs = await retriever._aget_relevant_documents("test query", run_manager=None)

    assert len(docs) == 3
    sources = {d.metadata["source"] for d in docs}
    assert sources == set(URLS)


@pytest.mark.asyncio
async def test_retriever_query_as_bm25_true():
    """query_as_bm25=True: retrieval query forwarded to run_pipeline."""
    received_queries = []

    async def fake_pipeline(url, query=""):
        received_queries.append(query)
        return _fake_result(url)

    retriever = DomPrunerRetriever(urls=["https://example.com"], query_as_bm25=True)
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        await retriever._aget_relevant_documents("asyncio", run_manager=None)

    assert received_queries == ["asyncio"]


@pytest.mark.asyncio
async def test_retriever_query_as_bm25_false():
    """query_as_bm25=False: run_pipeline always receives empty query."""
    received_queries = []

    async def fake_pipeline(url, query=""):
        received_queries.append(query)
        return _fake_result(url)

    retriever = DomPrunerRetriever(urls=["https://example.com"], query_as_bm25=False)
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        await retriever._aget_relevant_documents("asyncio", run_manager=None)

    assert received_queries == [""]


@pytest.mark.asyncio
async def test_retriever_ignore_errors_skips_failed_url():
    async def fake_pipeline(url, query=""):
        if "fail" in url:
            raise RuntimeError("fetch failed")
        return _fake_result(url)

    urls = ["https://example.com/ok", "https://example.com/fail"]
    retriever = DomPrunerRetriever(urls=urls, ignore_errors=True)
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        docs = await retriever._aget_relevant_documents("q", run_manager=None)

    assert len(docs) == 1
    assert docs[0].metadata["source"] == "https://example.com/ok"


@pytest.mark.asyncio
async def test_retriever_ignore_errors_false_raises():
    async def fake_pipeline(url, query=""):
        raise RuntimeError("fetch failed")

    retriever = DomPrunerRetriever(urls=["https://example.com"], ignore_errors=False)
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        with pytest.raises(RuntimeError):
            await retriever._aget_relevant_documents("q", run_manager=None)


@pytest.mark.asyncio
async def test_retriever_metadata_includes_meta_fields():
    async def fake_pipeline(url, query=""):
        result = _fake_result(url)
        return result

    retriever = DomPrunerRetriever(urls=["https://example.com"])
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        docs = await retriever._aget_relevant_documents("q", run_manager=None)

    meta = docs[0].metadata
    assert "title" in meta
    assert "lang" in meta
    assert meta["lang"] == "en"


@pytest.mark.asyncio
async def test_retriever_concurrency_respected():
    """Semaphore limits how many fetches run simultaneously."""
    active = 0
    max_active = 0

    async def fake_pipeline(url, query=""):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return _fake_result(url)

    urls = [f"https://example.com/page-{i}" for i in range(10)]
    retriever = DomPrunerRetriever(urls=urls, concurrency=3)
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        docs = await retriever._aget_relevant_documents("q", run_manager=None)

    assert len(docs) == 10
    assert max_active <= 3


def test_retriever_sync_invoke():
    """sync _get_relevant_documents works via sync_run."""
    async def fake_pipeline(url, query=""):
        return _fake_result(url)

    retriever = DomPrunerRetriever(urls=["https://example.com/page"])
    with patch("dompruner.langchain.retriever.run_pipeline", side_effect=fake_pipeline):
        docs = retriever.invoke("test")

    assert len(docs) == 1
    assert "source" in docs[0].metadata
