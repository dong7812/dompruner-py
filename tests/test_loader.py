"""Tests for DomPrunerLoader."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dompruner.langchain import DomPrunerLoader
from dompruner.pipeline import PipelineResult


def _fake_result(cached: bool = False) -> PipelineResult:
    return PipelineResult(
        url="https://example.com/page",
        render_type="SSR",
        markdown="# Page\n\nContent.",
        original_tokens=800,
        refined_tokens=40,
        reduction_ratio=0.95,
        fetch_ms=100.0,
        parse_ms=10.0,
        bm25_confidence=None,
        cached=cached,
        meta={"title": "Page Title", "lang": "en"},
    )


def test_loader_lazy_load_returns_document():
    with patch("dompruner.langchain.loader.sync_run", return_value=_fake_result()):
        loader = DomPrunerLoader("https://example.com/page")
        docs = list(loader.lazy_load())

    assert len(docs) == 1
    assert docs[0].page_content == "# Page\n\nContent."


def test_loader_metadata_includes_cached_false():
    with patch("dompruner.langchain.loader.sync_run", return_value=_fake_result(cached=False)):
        docs = list(DomPrunerLoader("https://example.com/page").lazy_load())

    assert docs[0].metadata["cached"] is False


def test_loader_metadata_includes_cached_true():
    with patch("dompruner.langchain.loader.sync_run", return_value=_fake_result(cached=True)):
        docs = list(DomPrunerLoader("https://example.com/page").lazy_load())

    assert docs[0].metadata["cached"] is True


def test_loader_metadata_includes_meta_fields():
    with patch("dompruner.langchain.loader.sync_run", return_value=_fake_result()):
        docs = list(DomPrunerLoader("https://example.com/page").lazy_load())

    meta = docs[0].metadata
    assert meta["source"] == "https://example.com/page"
    assert meta["render_type"] == "SSR"
    assert meta["reduction_ratio"] == pytest.approx(0.95)
    assert meta["title"] == "Page Title"
    assert meta["lang"] == "en"


@pytest.mark.asyncio
async def test_loader_alazy_load_returns_document():
    with patch("dompruner.langchain.loader.run_pipeline", new=AsyncMock(return_value=_fake_result())):
        loader = DomPrunerLoader("https://example.com/page")
        docs = [doc async for doc in loader.alazy_load()]

    assert len(docs) == 1
    assert "cached" in docs[0].metadata
