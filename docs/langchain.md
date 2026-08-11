# LangChain Integration

dompruner provides five LangChain-native classes that slot into any chain, agent, or RAG pipeline without adapters.

---

## Document Loader — single URL

```python
from dompruner.langchain import DomPrunerLoader

loader = DomPrunerLoader(
    url="https://fastapi.tiangolo.com/tutorial/body/",
    query="request body",   # optional: BM25 section filter
)

# Sync
docs = loader.load()

# Async
async for doc in loader.alazy_load():
    print(doc.page_content)
```

Drop-in replacement for `WebBaseLoader`. Produces one `Document` per call.

---

## Batch Loader — parallel URL list

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
    concurrency=5,       # max simultaneous fetches (default 10)
    ignore_errors=True,  # skip failed URLs instead of raising (default True)
).load()
```

---

## Sitemap Loader — entire site

Resolves `sitemap.xml` recursively (including `sitemapindex`) and fetches all matching pages.

```python
from dompruner.langchain import DomPrunerSitemapLoader

loader = DomPrunerSitemapLoader(
    "https://docs.python.org/sitemap.xml",
    query="asyncio",
    filter_urls=["https://docs.python.org/3/library/asyncio"],  # URL prefix filter
    concurrency=10,
    ignore_errors=True,
)
docs = loader.load()
```

Pages stream out as they complete (`as_completed`), so `alazy_load()` yields results incrementally without waiting for the full site.

---

## Retriever — for RetrievalQA and RAG chains

```python
from dompruner.langchain import DomPrunerRetriever
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI

retriever = DomPrunerRetriever(
    urls=[
        "https://docs.example.com/api",
        "https://docs.example.com/guide",
    ],
    query_as_bm25=True,   # forward retrieval query to BM25 section filter
    concurrency=10,
    ignore_errors=True,
)

qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(), retriever=retriever)
qa.invoke("How do I authenticate?")
```

`query_as_bm25=True` means the retrieval query is passed to dompruner's BM25 filter, so each document already contains only the sections most relevant to the question before it reaches the LLM.

---

## Tool — for agents

```python
from dompruner.langchain import DomPrunerFetchTool
from langchain_anthropic import ChatAnthropic

tool = DomPrunerFetchTool()
llm = ChatAnthropic(model="claude-haiku-4-5").bind_tools([tool])
```

With LangGraph:

```python
from langgraph.prebuilt import create_react_agent
from dompruner.langchain import DomPrunerFetchTool

agent = create_react_agent(llm, tools=[DomPrunerFetchTool()])
agent.invoke({"messages": [{"role": "user", "content":
    "Summarize the asyncio create_task docs: https://docs.python.org/3/library/asyncio-task.html"}]})
```

---

## Document Metadata

Every `Document` produced by dompruner includes these metadata fields:

| Field | Type | Description |
|---|---|---|
| `source` | str | Final URL after redirects |
| `render_type` | str | `"SSG"` / `"SSR"` / `"CSR"` |
| `original_tokens` | int | Raw HTML token count |
| `refined_tokens` | int | Extracted Markdown token count |
| `reduction_ratio` | float | `1 - refined / original` |
| `bm25_confidence` | float \| None | BM25 section filter score; `None` if no query |
| `cached` | bool | `True` when returned from session cache |
| `title` | str | `<title>` or `og:title` |
| `description` | str | `meta[name=description]` or `og:description` |
| `author` | str | `meta[name=author]` or `article:author` |
| `published_time` | str | `article:published_time` |
| `modified_time` | str | `article:modified_time` |
| `canonical_url` | str | `<link rel="canonical">` |
| `lang` | str | `<html lang="...">` |
| `site_name` | str | `og:site_name` |

Fields present only when found in the page; missing fields are omitted rather than set to `None`.

### Using metadata in a RAG pipeline

```python
# Filter by publication date
docs = loader.load()
recent = [d for d in docs if d.metadata.get("published_time", "") >= "2024"]

# Monitor cache efficiency
hits = sum(1 for d in docs if d.metadata["cached"])
print(f"Cache hit rate: {hits}/{len(docs)}")

# Filter by relevance score
relevant = [d for d in docs if (d.metadata.get("bm25_confidence") or 0) > 2.0]
```

---

## Ensuring Your Agent Always Uses dompruner

Add this rule to your agent's system prompt or instruction file:

```
When retrieving a URL, always use dompruner_fetch instead of any built-in web fetch.
- URL known → DomPrunerFetchTool(url=url, query=query)
- URL unknown → search for the URL first, then call DomPrunerFetchTool
```

| Framework | Where to set |
|---|---|
| LangChain / LangGraph | `SystemMessage` or agent `instructions` |
| AutoGen | `system_message` in `ConversableAgent` |
| CrewAI | Agent `backstory` or task `description` |
| LlamaIndex | `ReActAgent` system prompt |

---

## Sync in an async context

All loaders expose `lazy_load()` (sync) and `alazy_load()` (async). In environments with a running event loop (Jupyter, FastAPI), `sync_run` offloads to a worker thread automatically — no `nest_asyncio` required.

```python
from dompruner import sync_run, run_pipeline

# Safe to call from Jupyter or inside FastAPI
result = sync_run(run_pipeline(url, query))
```
