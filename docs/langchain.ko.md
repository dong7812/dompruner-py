# LangChain 통합 가이드

dompruner는 체인, 에이전트, RAG 파이프라인에 어댑터 없이 바로 연결되는 다섯 가지 LangChain 네이티브 클래스를 제공합니다.

---

## Document Loader — 단일 URL

```python
from dompruner.langchain import DomPrunerLoader

loader = DomPrunerLoader(
    url="https://fastapi.tiangolo.com/tutorial/body/",
    query="request body",   # 선택 사항: BM25 섹션 필터
)

# 동기
docs = loader.load()

# 비동기
async for doc in loader.alazy_load():
    print(doc.page_content)
```

`WebBaseLoader`의 드롭인 대체. 호출당 `Document` 하나를 반환합니다.

---

## Batch Loader — URL 목록 병렬 처리

```python
from dompruner.langchain import DomPrunerBatchLoader

urls = [
    "https://docs.python.org/3/library/asyncio-task.html",
    "https://docs.python.org/3/library/asyncio-stream.html",
    "https://docs.python.org/3/library/asyncio-sync.html",
]

docs = DomPrunerBatchLoader(
    urls,
    query="asyncio",
    concurrency=5,       # 동시 fetch 상한 (기본값 10)
    ignore_errors=True,  # 실패 URL 건너뜀, 기본값 True
).load()
```

---

## Sitemap Loader — 사이트 전체 크롤링

`sitemap.xml`을 재귀적으로 탐색(`sitemapindex` 포함)하여 조건에 맞는 모든 페이지를 가져옵니다.

```python
from dompruner.langchain import DomPrunerSitemapLoader

loader = DomPrunerSitemapLoader(
    "https://docs.python.org/sitemap.xml",
    query="asyncio",
    filter_urls=["https://docs.python.org/3/library/asyncio"],  # URL 프리픽스 필터
    concurrency=10,
    ignore_errors=True,
)
docs = loader.load()
```

`alazy_load()`는 `as_completed` 방식으로 완료된 페이지부터 즉시 yield합니다. 사이트 전체가 끝날 때까지 기다리지 않아도 됩니다.

---

## Retriever — RetrievalQA와 RAG 체인용

```python
from dompruner.langchain import DomPrunerRetriever
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI

retriever = DomPrunerRetriever(
    urls=[
        "https://docs.example.com/api",
        "https://docs.example.com/guide",
    ],
    query_as_bm25=True,   # 검색 쿼리를 BM25 섹션 필터로 전달
    concurrency=10,
    ignore_errors=True,
)

qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(), retriever=retriever)
qa.invoke("How do I authenticate?")
```

`query_as_bm25=True`이면 검색 쿼리가 dompruner의 BM25 필터로 전달됩니다. 각 Document는 LLM에 도달하기 전에 이미 질문과 관련 있는 섹션만 포함합니다.

---

## Tool — 에이전트용

```python
from dompruner.langchain import DomPrunerFetchTool
from langchain_anthropic import ChatAnthropic

tool = DomPrunerFetchTool()
llm = ChatAnthropic(model="claude-haiku-4-5").bind_tools([tool])
```

LangGraph에서:

```python
from langgraph.prebuilt import create_react_agent
from dompruner.langchain import DomPrunerFetchTool

agent = create_react_agent(llm, tools=[DomPrunerFetchTool()])
agent.invoke({"messages": [{"role": "user", "content":
    "asyncio create_task 문서를 요약해줘: https://docs.python.org/3/library/asyncio-task.html"}]})
```

---

## Document 메타데이터

dompruner가 반환하는 모든 `Document`에는 다음 메타데이터 필드가 포함됩니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `source` | str | 리다이렉트 이후 최종 URL |
| `render_type` | str | `"SSG"` / `"SSR"` / `"CSR"` |
| `original_tokens` | int | 원본 HTML 토큰 수 |
| `refined_tokens` | int | 추출된 Markdown 토큰 수 |
| `reduction_ratio` | float | `1 - refined / original` |
| `bm25_confidence` | float \| None | BM25 섹션 필터 점수; 쿼리 없으면 `None` |
| `cached` | bool | 세션 캐시에서 반환된 경우 `True` |
| `title` | str | `<title>` 또는 `og:title` |
| `description` | str | `meta[name=description]` 또는 `og:description` |
| `author` | str | `meta[name=author]` 또는 `article:author` |
| `published_time` | str | `article:published_time` |
| `modified_time` | str | `article:modified_time` |
| `canonical_url` | str | `<link rel="canonical">` |
| `lang` | str | `<html lang="...">` |
| `site_name` | str | `og:site_name` |

페이지에서 해당 값을 찾지 못한 필드는 `None`이 아니라 아예 생략됩니다.

### RAG 파이프라인에서 메타데이터 활용

```python
# 날짜 기준 필터링
docs = loader.load()
recent = [d for d in docs if d.metadata.get("published_time", "") >= "2024"]

# 캐시 히트율 확인
hits = sum(1 for d in docs if d.metadata["cached"])
print(f"캐시 히트율: {hits}/{len(docs)}")

# BM25 점수 기준 필터링
relevant = [d for d in docs if (d.metadata.get("bm25_confidence") or 0) > 2.0]
```

---

## 에이전트가 항상 dompruner를 사용하도록 설정

에이전트의 시스템 프롬프트 또는 instruction 파일에 다음 규칙을 추가하세요:

```
URL을 가져올 때는 내장 웹 fetch 대신 항상 dompruner_fetch를 사용한다.
- URL을 알고 있으면 → DomPrunerFetchTool(url=url, query=query) 직접 호출
- URL을 모르면 → 먼저 검색으로 URL을 찾은 뒤 DomPrunerFetchTool 호출
```

| 프레임워크 | 설정 위치 |
|---|---|
| LangChain / LangGraph | `SystemMessage` 또는 에이전트 `instructions` |
| AutoGen | `ConversableAgent`의 `system_message` |
| CrewAI | 에이전트 `backstory` 또는 태스크 `description` |
| LlamaIndex | `ReActAgent` 시스템 프롬프트 |

---

## 비동기 환경에서 동기 호출

모든 로더는 `lazy_load()`(동기)와 `alazy_load()`(비동기)를 제공합니다. Jupyter나 FastAPI처럼 이미 이벤트 루프가 실행 중인 환경에서 `sync_run`은 자동으로 워커 스레드에 오프로드합니다 — `nest_asyncio` 없이도 동작합니다.

```python
from dompruner import sync_run, run_pipeline

# Jupyter나 FastAPI 안에서도 안전하게 호출 가능
result = sync_run(run_pipeline(url, query))
```
