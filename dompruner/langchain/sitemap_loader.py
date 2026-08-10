"""DomPrunerSitemapLoader — load an entire site via sitemap.xml."""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from typing import AsyncIterator, Iterator

import httpx
from langchain_core.document_loaders.base import BaseLoader
from langchain_core.documents import Document

from ..pipeline import run_pipeline


def _strip_ns(el: ET.Element) -> ET.Element:
    """Strip XML namespace prefixes from all tags in-place."""
    for node in el.iter():
        if "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
    return el


async def _collect_urls(sitemap_url: str, client: httpx.AsyncClient) -> list[str]:
    """Recursively resolve a sitemap or sitemap index into a flat list of page URLs."""
    try:
        r = await client.get(sitemap_url, follow_redirects=True, timeout=15)
        r.raise_for_status()
    except Exception:
        return []

    root = _strip_ns(ET.fromstring(r.text))

    if root.tag == "sitemapindex":
        child_urls = [
            (loc.text or "").strip()
            for loc in root.findall("sitemap/loc")
            if loc.text
        ]
        results = await asyncio.gather(*[_collect_urls(u, client) for u in child_urls])
        return [url for batch in results for url in batch]

    return [
        (loc.text or "").strip()
        for loc in root.findall("url/loc")
        if loc.text
    ]


class DomPrunerSitemapLoader(BaseLoader):
    """Load an entire site from sitemap.xml as pruned Markdown Documents.

    Fetches all page URLs listed in the sitemap (including sitemap indexes),
    runs each through dompruner's DOM AST pipeline, and returns one Document
    per page. Pages are fetched concurrently up to `concurrency` at a time.

    Args:
        sitemap_url: URL of the sitemap (e.g. https://example.com/sitemap.xml).
        query: Optional BM25 filter query applied to every page.
        filter_urls: Optional list of URL prefixes — only pages whose URL starts
            with one of these prefixes are included.
        concurrency: Max simultaneous page fetches (default 10).
    """

    def __init__(
        self,
        sitemap_url: str,
        query: str = "",
        filter_urls: list[str] | None = None,
        concurrency: int = 10,
    ) -> None:
        self.sitemap_url = sitemap_url
        self.query = query
        self.filter_urls = filter_urls
        self.concurrency = concurrency

    def _matches(self, url: str) -> bool:
        if not self.filter_urls:
            return True
        return any(url.startswith(prefix) for prefix in self.filter_urls)

    def lazy_load(self) -> Iterator[Document]:
        async def _gather() -> list[Document]:
            docs: list[Document] = []
            async for doc in self.alazy_load():
                docs.append(doc)
            return docs

        yield from asyncio.get_event_loop().run_until_complete(_gather())

    async def alazy_load(self) -> AsyncIterator[Document]:
        async with httpx.AsyncClient(
            headers={"User-Agent": "dompruner-sitemap/1.0"},
        ) as client:
            all_urls = await _collect_urls(self.sitemap_url, client)

        urls = [u for u in all_urls if u and self._matches(u)]
        sem = asyncio.Semaphore(self.concurrency)

        async def fetch_one(url: str) -> Document | None:
            async with sem:
                try:
                    result = await run_pipeline(url, self.query)
                    return Document(
                        page_content=result.markdown,
                        metadata={
                            "source": result.url,
                            "render_type": result.render_type,
                            "original_tokens": result.original_tokens,
                            "refined_tokens": result.refined_tokens,
                            "reduction_ratio": result.reduction_ratio,
                            "bm25_confidence": result.bm25_confidence,
                        },
                    )
                except Exception:
                    return None

        for coro in asyncio.as_completed([fetch_one(u) for u in urls]):
            doc = await coro
            if doc is not None:
                yield doc
