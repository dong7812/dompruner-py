"""DomPrunerRetriever — LangChain BaseRetriever integration."""
from __future__ import annotations

from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from ..pipeline import run_pipeline, sync_run


class DomPrunerRetriever(BaseRetriever):
    """Retrieve documents from a fixed URL list using DOM-pruned Markdown.

    Fetches each URL through dompruner's L1→L2→L3 pipeline and returns
    all pages as Documents. When query_as_bm25=True, the retrieval query
    is passed as a BM25 filter to surface the most relevant sections of
    each page within a token budget.

    Fits directly into RetrievalQA, ConversationalRetrievalChain, and any
    chain that accepts a BaseRetriever.

    Args:
        urls: List of URLs to fetch on every retrieval call.
        query_as_bm25: If True, pass the retrieval query to dompruner's
            BM25 section filter. Default True.
        concurrency: Max simultaneous page fetches. Default 10.
        ignore_errors: Skip URLs that fail to fetch. Default True.
    """

    urls: list[str]
    query_as_bm25: bool = True
    concurrency: int = 10
    ignore_errors: bool = True

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        return sync_run(self._aget_relevant_documents(query, run_manager=run_manager))

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        import asyncio

        bm25_query = query if self.query_as_bm25 else ""
        sem = asyncio.Semaphore(self.concurrency)

        async def fetch_one(url: str) -> Document | None:
            async with sem:
                try:
                    result = await run_pipeline(url, bm25_query)
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
                            **result.meta,
                        },
                    )
                except Exception:
                    if self.ignore_errors:
                        return None
                    raise

        results = await asyncio.gather(*[fetch_one(u) for u in self.urls])
        return [doc for doc in results if doc is not None]
