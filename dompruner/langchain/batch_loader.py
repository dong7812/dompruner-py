"""DomPrunerBatchLoader — fetch a list of URLs concurrently."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterator

from langchain_core.document_loaders.base import BaseLoader
from langchain_core.documents import Document

from ..pipeline import run_pipeline


class DomPrunerBatchLoader(BaseLoader):
    """Load multiple URLs concurrently as pruned Markdown Documents.

    Sitemap 없이 URL 리스트만으로 병렬 fetch. 캐시 히트 시 네트워크
    요청 없이 즉시 반환한다.

    Args:
        urls: 가져올 URL 목록.
        query: 모든 페이지에 적용할 BM25 필터 쿼리 (선택).
        concurrency: 동시 fetch 수 (기본 10). Semaphore로 제어.
        ignore_errors: True면 개별 URL fetch 실패 시 건너뜀 (기본 True).
    """

    def __init__(
        self,
        urls: list[str],
        query: str = "",
        concurrency: int = 10,
        ignore_errors: bool = True,
    ) -> None:
        self.urls = urls
        self.query = query
        self.concurrency = concurrency
        self.ignore_errors = ignore_errors

    def lazy_load(self) -> Iterator[Document]:
        async def _gather() -> list[Document]:
            docs: list[Document] = []
            async for doc in self.alazy_load():
                docs.append(doc)
            return docs

        yield from asyncio.get_event_loop().run_until_complete(_gather())

    async def alazy_load(self) -> AsyncIterator[Document]:
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
                            "cached": result.cached,
                        },
                    )
                except Exception:
                    if self.ignore_errors:
                        return None
                    raise

        for coro in asyncio.as_completed([fetch_one(u) for u in self.urls]):
            doc = await coro
            if doc is not None:
                yield doc
