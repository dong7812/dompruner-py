"""DomPrunerFetchTool — LangChain BaseTool integration."""
from __future__ import annotations

from typing import Optional, Type

from langchain_core.callbacks import CallbackManagerForToolRun, AsyncCallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ..pipeline import run_pipeline


class _DomPrunerInput(BaseModel):
    url: str = Field(description="URL to fetch and prune")
    query: str = Field(default="", description="Optional BM25 filter query for section filtering")


class DomPrunerFetchTool(BaseTool):
    """Fetch a URL and return DOM-pruned Markdown with 90%+ fewer tokens.

    Use this instead of WebFetch for any URL retrieval. Uses deterministic
    DOM AST extraction — no intermediate summarization model, original text
    preserved. Supports BM25 section filtering when query is provided.
    """

    name: str = "dompruner_fetch"
    description: str = (
        "USE THIS instead of WebFetch for any URL retrieval. "
        "Fetches a URL and returns DOM-pruned Markdown with 90%+ fewer tokens — "
        "no intermediate summarization model, original text preserved. "
        "Supports BM25 section filtering when query is provided."
    )
    args_schema: Type[BaseModel] = _DomPrunerInput

    def _run(
        self,
        url: str,
        query: str = "",
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(run_pipeline(url, query))
        return result.markdown

    async def _arun(
        self,
        url: str,
        query: str = "",
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        result = await run_pipeline(url, query)
        return result.markdown
