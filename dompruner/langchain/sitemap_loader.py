"""DomPrunerSitemapLoader — load an entire site via sitemap.xml.

## Sitemap 포맷 두 종류

1. **urlset** (일반 사이트맵): 페이지 URL을 직접 나열
   ```xml
   <urlset>
     <url><loc>https://example.com/page-a</loc></url>
     <url><loc>https://example.com/page-b</loc></url>
   </urlset>
   ```

2. **sitemapindex** (인덱스 사이트맵): 다른 사이트맵 파일들을 가리킴
   ```xml
   <sitemapindex>
     <sitemap><loc>https://example.com/sitemap-blog.xml</loc></sitemap>
     <sitemap><loc>https://example.com/sitemap-docs.xml</loc></sitemap>
   </sitemapindex>
   ```
   대형 사이트(URL 50,000개 초과)가 사이트맵을 분할할 때 사용.

## 재귀 전략 (_collect_urls)

  _collect_urls(root_url)
    └─ XML 가져옴
    └─ sitemapindex 감지?
        YES → <loc>들을 꺼내 각각 _collect_urls() 재귀 호출
              → asyncio.gather로 병렬 처리 → 결과 flat merge
        NO  → urlset으로 간주 → <loc>들을 그대로 반환

## 동시성 제어 (Semaphore)

URL 목록을 모두 한 번에 fetch하면 서버 부하 + 차단 위험이 있으므로
asyncio.Semaphore(concurrency)로 동시 실행 수를 제한한다.

  asyncio.as_completed 사용 이유:
  asyncio.gather는 모든 완료를 기다린 후 한꺼번에 반환하지만,
  as_completed는 완료된 순서대로 즉시 yield할 수 있어
  alazy_load()의 스트리밍 특성과 잘 맞는다.
"""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from typing import AsyncIterator, Iterator

import httpx
from langchain_core.document_loaders.base import BaseLoader
from langchain_core.documents import Document

from ..pipeline import run_pipeline, sync_run


def _strip_ns(el: ET.Element) -> ET.Element:
    """XML 네임스페이스 프리픽스를 모든 태그에서 제거한다 (in-place).

    표준 사이트맵은 xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"를 선언하는데,
    ElementTree는 이를 태그에 붙여 {http://...}urlset 형태로 파싱한다.
    프리픽스를 제거하면 findall("url/loc") 같은 단순 경로로 검색 가능해진다.
    """
    for node in el.iter():
        if "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
    return el


async def _collect_urls(sitemap_url: str, client: httpx.AsyncClient) -> list[str]:
    """사이트맵 URL 하나를 받아 페이지 URL 목록을 반환한다.

    sitemapindex면 자식 사이트맵들을 asyncio.gather로 병렬 재귀 탐색해
    평탄화(flat)된 배열로 합친다.
    네트워크 오류가 발생한 자식은 빈 배열로 처리해 전체 수집이 중단되지 않는다.
    """
    try:
        r = await client.get(sitemap_url, follow_redirects=True, timeout=15)
        r.raise_for_status()
    except Exception:
        # 이 사이트맵 파일 자체를 가져오지 못하면 빈 배열 반환 (부모 재귀에서 무시됨)
        return []

    root = _strip_ns(ET.fromstring(r.text))

    if root.tag == "sitemapindex":
        # ── sitemapindex 분기 ─────────────────────────────────────────────
        child_urls = [
            (loc.text or "").strip()
            for loc in root.findall("sitemap/loc")
            if loc.text
        ]
        # 자식 사이트맵들을 병렬 재귀 탐색 (각 자식도 sitemapindex일 수 있음)
        results = await asyncio.gather(*[_collect_urls(u, client) for u in child_urls])
        return [url for batch in results for url in batch]  # flat merge

    # ── 일반 urlset 분기 ─────────────────────────────────────────────────
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

        yield from sync_run(_gather())

    async def alazy_load(self) -> AsyncIterator[Document]:
        # 1단계: 사이트맵에서 URL 목록 수집 (재귀 포함)
        async with httpx.AsyncClient(
            headers={"User-Agent": "dompruner-sitemap/1.0"},
        ) as client:
            all_urls = await _collect_urls(self.sitemap_url, client)

        # 2단계: prefix 필터 적용
        urls = [u for u in all_urls if u and self._matches(u)]

        # 3단계: Semaphore로 동시 fetch 수 제한
        # concurrency=10이면 최대 10개 페이지를 동시에 fetch하고,
        # 하나가 완료되면 다음 대기 중인 URL이 즉시 시작됨
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
                            **result.meta,
                        },
                    )
                except Exception:
                    return None

        # 4단계: as_completed로 완료된 순서대로 즉시 yield
        # gather()와 달리 모든 완료를 기다리지 않고 스트리밍 방식으로 반환
        for coro in asyncio.as_completed([fetch_one(u) for u in urls]):
            doc = await coro
            if doc is not None:
                yield doc
