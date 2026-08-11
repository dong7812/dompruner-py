"""Tests for DomPrunerSitemapLoader."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dompruner.langchain.sitemap_loader import _collect_urls, _strip_ns


URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
  <url><loc>https://example.com/c</loc></url>
</urlset>"""

SITEMAPINDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-2.xml</loc></sitemap>
</sitemapindex>"""

CHILD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc></url>
</urlset>"""


def test_strip_ns_removes_namespace():
    root = ET.fromstring(URLSET_XML)
    assert "}" in root.tag
    _strip_ns(root)
    assert root.tag == "urlset"
    assert root.find("url/loc") is not None


@pytest.mark.asyncio
async def test_collect_urls_urlset():
    mock_response = MagicMock()
    mock_response.text = URLSET_XML
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    urls = await _collect_urls("https://example.com/sitemap.xml", mock_client)
    assert urls == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


@pytest.mark.asyncio
async def test_collect_urls_sitemapindex():
    def make_response(text):
        r = MagicMock()
        r.text = text
        r.raise_for_status = MagicMock()
        return r

    responses = {
        "https://example.com/sitemap.xml": make_response(SITEMAPINDEX_XML),
        "https://example.com/sitemap-1.xml": make_response(CHILD_XML),
        "https://example.com/sitemap-2.xml": make_response(CHILD_XML),
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=lambda url, **_: responses[url])

    urls = await _collect_urls("https://example.com/sitemap.xml", mock_client)
    assert urls == ["https://example.com/page1", "https://example.com/page1"]


@pytest.mark.asyncio
async def test_sitemap_loader_filter_urls():
    from dompruner.langchain import DomPrunerSitemapLoader
    from dompruner.pipeline import PipelineResult

    mock_result = PipelineResult(
        url="https://example.com/docs/intro",
        render_type="SSR",
        markdown="# Intro",
        original_tokens=1000,
        refined_tokens=50,
        reduction_ratio=0.95,
        fetch_ms=100,
        parse_ms=10,
    )

    with (
        patch(
            "dompruner.langchain.sitemap_loader._collect_urls",
            new=AsyncMock(
                return_value=[
                    "https://example.com/docs/intro",
                    "https://example.com/blog/post",
                ]
            ),
        ),
        patch("dompruner.langchain.sitemap_loader.run_pipeline", new=AsyncMock(return_value=mock_result)),
    ):
        loader = DomPrunerSitemapLoader(
            "https://example.com/sitemap.xml",
            filter_urls=["https://example.com/docs/"],
        )
        docs = []
        async for doc in loader.alazy_load():
            docs.append(doc)

    assert len(docs) == 1
    assert docs[0].metadata["source"] == "https://example.com/docs/intro"
    assert docs[0].metadata["reduction_ratio"] == 0.95


@pytest.mark.asyncio
async def test_sitemap_loader_metadata_includes_cached():
    from dompruner.langchain import DomPrunerSitemapLoader
    from dompruner.pipeline import PipelineResult

    mock_result = PipelineResult(
        url="https://example.com/page",
        render_type="SSR",
        markdown="# Page",
        original_tokens=500,
        refined_tokens=25,
        reduction_ratio=0.95,
        fetch_ms=80,
        parse_ms=8,
        cached=False,
    )

    with (
        patch(
            "dompruner.langchain.sitemap_loader._collect_urls",
            new=AsyncMock(return_value=["https://example.com/page"]),
        ),
        patch("dompruner.langchain.sitemap_loader.run_pipeline", new=AsyncMock(return_value=mock_result)),
    ):
        loader = DomPrunerSitemapLoader("https://example.com/sitemap.xml")
        docs = [doc async for doc in loader.alazy_load()]

    assert len(docs) == 1
    assert "cached" in docs[0].metadata
    assert docs[0].metadata["cached"] is False

