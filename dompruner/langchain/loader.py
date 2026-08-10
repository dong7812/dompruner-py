"""DomPrunerLoader — LangChain BaseLoader integration."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterator

from langchain_core.document_loaders.base import BaseLoader
from langchain_core.documents import Document

from ..pipeline import run_pipeline


class DomPrunerLoader(BaseLoader):
    """Load a web page as a pruned Markdown Document.

    Uses dompruner's L1→L2→L3 DOM AST pipeline to reduce token count by
    90%+ versus raw HTML, without LLM summarization.

    Args:
        url: URL to fetch and prune.
        query: Optional BM25 filter query to return only the most relevant
            sections within a token budget.
    """

    def __init__(self, url: str, query: str = "") -> None:
        self.url = url
        self.query = query

    def lazy_load(self) -> Iterator[Document]:
        result = asyncio.get_event_loop().run_until_complete(
            run_pipeline(self.url, self.query)
        )
        yield Document(
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

    async def alazy_load(self) -> AsyncIterator[Document]:
        result = await run_pipeline(self.url, self.query)
        yield Document(
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
