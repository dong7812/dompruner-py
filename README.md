# dompruner

[한국어](./README.ko.md) | English

> Python port of [dompruner-mcp](https://github.com/dong7812/dompruner-mcp) — DOM AST pruning for LangChain, LlamaIndex, and direct use.

When an LLM agent fetches a web page, it receives tens of thousands of raw HTML tokens it doesn't need — navigation, ads, scripts, footers. dompruner strips all of that via DOM AST parsing and passes the **original content, unchanged, directly to the model**. No intermediate summarization model, no API key, no vector database.

The result: **97.3% fewer tokens on average** across documentation, API references, and technical pages.

```
> docs.python.org/3/library/asyncio-task.html
> Raw HTML   44,315 tokens
> dompruner   1,275 tokens  (97.1% reduction)
> Fetch: 133ms · Parse: 73.4ms
```

---

## Quick Start

```bash
pip install dompruner
```

### CLI

```bash
# Human-readable output
python -m dompruner https://docs.python.org/3/library/asyncio-task.html

# With BM25 section filter
python -m dompruner https://docs.python.org/3/library/asyncio-task.html "create_task"

# JSON output
python -m dompruner https://docs.python.org/3/library/asyncio-task.html --json
```

```
URL          : https://docs.python.org/3/library/asyncio-task.html
Title        : asyncio — Asynchronous I/O
Render type  : SSR
Tokens       : 44,315 → 1,275  (97.1% reduction)
BM25 score   : 4.21
Cached       : No
Fetch        : 133ms  Parse: 73ms
────────────────────────────────────────
# asyncio — Asynchronous I/O
...
```

### Direct use (Python)

```python
import asyncio
from dompruner import run_pipeline

result = asyncio.run(run_pipeline(
    "https://docs.python.org/3/library/asyncio-task.html",
    query="create_task",
))
print(result.markdown)
print(f"Tokens: {result.original_tokens:,} → {result.refined_tokens:,} ({result.reduction_ratio:.1%})")
print(result.meta)
# {'title': 'asyncio — Asynchronous I/O', 'lang': 'en', 'description': '...', ...}
```

---

## LangChain Integration

> Listed in the [LangChain Python integrations overview](https://docs.langchain.com/oss/python/integrations/document_loaders) as a third-party web loader.

### Document Loader — single URL

```python
from dompruner.langchain import DomPrunerLoader

docs = DomPrunerLoader(
    "https://fastapi.tiangolo.com/tutorial/body/",
    query="request body",
).load()

doc = docs[0]
print(doc.page_content)
print(doc.metadata)
# {
#   'source': 'https://fastapi.tiangolo.com/tutorial/body/',
#   'render_type': 'SSR',
#   'original_tokens': 31659,
#   'refined_tokens': 1694,
#   'reduction_ratio': 0.946,
#   'bm25_confidence': 3.21,
#   'title': 'Request Body - FastAPI',
#   'description': 'FastAPI framework, high performance...',
#   'lang': 'en',
# }

# Async
async def main():
    async for doc in DomPrunerLoader(url, query).alazy_load():
        print(doc.page_content)
```

### Batch Loader — parallel URL list

```python
from dompruner.langchain import DomPrunerBatchLoader

urls = [
    "https://docs.python.org/3/library/asyncio-task.html",
    "https://docs.python.org/3/library/asyncio-stream.html",
    "https://docs.python.org/3/library/asyncio-sync.html",
]

# Fetches all URLs concurrently (default: 10 at a time)
docs = DomPrunerBatchLoader(urls, query="asyncio", concurrency=5).load()
print(f"Loaded {len(docs)} documents")
```

### Sitemap Loader — entire site

```python
from dompruner.langchain import DomPrunerSitemapLoader

loader = DomPrunerSitemapLoader(
    "https://docs.python.org/sitemap.xml",
    query="asyncio",
    filter_urls=["https://docs.python.org/3/library/asyncio"],  # optional prefix filter
    concurrency=10,
)
docs = loader.load()
print(f"Loaded {len(docs)} pages from sitemap")
```

### Retriever — for RetrievalQA and RAG chains

```python
from dompruner.langchain import DomPrunerRetriever
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI

retriever = DomPrunerRetriever(
    urls=[
        "https://docs.example.com/api",
        "https://docs.example.com/guide",
    ],
    query_as_bm25=True,  # retrieval query is forwarded to BM25 section filter
)

qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(), retriever=retriever)
qa.invoke("How do I authenticate?")
```

### Tool — for agents

```python
from dompruner.langchain import DomPrunerFetchTool
from langchain_anthropic import ChatAnthropic

tool = DomPrunerFetchTool()
llm = ChatAnthropic(model="claude-haiku-4-5").bind_tools([tool])
```

Or with LangGraph:

```python
from langgraph.prebuilt import create_react_agent
from dompruner.langchain import DomPrunerFetchTool

agent = create_react_agent(llm, tools=[DomPrunerFetchTool()])
agent.invoke({"messages": [{"role": "user", "content":
    "Summarize the asyncio create_task docs: https://docs.python.org/3/library/asyncio-task.html"}]})
```

---

## Ensuring Your Agent Always Uses dompruner

Add the rule to your agent's system prompt or instruction file:

```
When retrieving a URL, always use dompruner_fetch instead of any built-in web fetch.
- URL known → DomPrunerFetchTool(url=url, query=query)
- URL unknown → search for the URL first, then call DomPrunerFetchTool
```

| Framework | Where to set |
|-----------|-------------|
| LangChain / LangGraph | `SystemMessage` or agent `instructions` |
| AutoGen | `system_message` in `ConversableAgent` |
| CrewAI | Agent `backstory` or task `description` |
| LlamaIndex | `ReActAgent` system prompt |

---

## How It Works

```
URL
 └─▶ fetch_page()       — tiered fetch: direct → UA rotation → Playwright fallback
      │
      ├─▶ [SSG]  extract_ssg_markdown()
      │           walks __NEXT_DATA__ RSC tuple tree → clean Markdown  (≥ 97% reduction)
      │           skips DOM parse entirely
      │
      └─▶ [SSR/CSR]  BeautifulSoup DOM tree  (parsed once — content + meta shared)
                └─▶ FQN Router (L1)        keeps p / h1–h5 / li / pre / code / table
                     │                     prunes nav / footer / aside / form
                     └─▶ Heading Cluster (L2)  dev-doc structure detection
                          └─▶ CETD Engine (L3)  text-density scoring fallback
                               └─▶ BM25+ Section Filter  query-aware ranking
                                    └─▶ Compact Markdown  ──▶  LLM context
```

### Render Type Detection

| Type | Signal | Strategy |
|------|--------|----------|
| SSG | `__NEXT_DATA__`, `window.__NUXT__`, `window.page` | RSC tuple tree walk — DOM parse skipped |
| SSR | Body text density ≥ 2% | Full DOM AST pipeline (L1→L2→L3) |
| CSR | Body text density < 2% | DOM AST pipeline (partial content) |

### Tiered Fetch

| Level | Trigger | Method |
|-------|---------|--------|
| L1 | Default | `httpx` direct fetch |
| L2 | 403 / 429 response | User-Agent rotation (3 browser UA strings) |
| L3 | CSR detected or L2 fails | `playwright` headless browser (optional dep) |

Install Playwright only if needed:

```bash
pip install "dompruner[playwright]"
playwright install chromium
```

### BM25+ Section Filter

When `query` is provided, extracted sections are ranked by BM25+ score. Three adjustments:

- **Heading boost (2.5×)** — sections under a relevant heading rank higher
- **Depth decay (0.4)** — deeply nested sections score lower than top-level content
- **Ancestor preservation** — parent headings of selected sections are always included for context

Result: only the most relevant sections enter the LLM context, within a 1,200-token budget (configurable).

**Zero-score fallback:** if the query terms appear nowhere in the document (BM25 max score = 0), dompruner returns the full clean content instead of the filtered subset. No arbitrary cutoff, no small model involved.

---

## Benchmark

All numbers are **live measurements** against real documentation sites. Raw HTML token counts use the `len(html) // 4` estimator (same as the MCP version). Reproducible script at [`bench.py`](./bench.py).

| Site | Raw HTML | **dompruner** | **Reduction** | Fetch | Parse | Mode |
|------|:--------:|:-------------:|:-------------:|:-----:|:-----:|:----:|
| Python asyncio | 44,315 | **1,275** | **97.1%** | 133ms | 73.4ms | BM25 |
| Rust Book ch04 | 14,003 | **2,713** | **80.6%** | 92ms | 13.2ms | BM25 |
| React useState (SSG) | 110,963 | **2,599** | **97.7%** | 186ms | 68.8ms | BM25 |
| FastAPI Body | 31,659 | **1,694** | **94.6%** | 85ms | 33.9ms | full† |
| MDN Fetch API | 38,086 | **691** | **98.2%** | 257ms | 30.4ms | full† |
| Next.js Routing | 156,578 | **1,828** | **98.8%** | 732ms | 66.5ms | full† |
| TypeScript Handbook | 47,333 | **305** | **99.4%** | 324ms | 15.8ms | full† |
| Vue Reactivity | 38,375 | **2,045** | **94.7%** | 656ms | 50.2ms | BM25 |
| **Average** | **60,164** | **1,643** | **97.3%** | **308ms** | **44.0ms** | |

`†` BM25 zero-score: query terms absent from document → full clean content returned automatically.

**Notes on the SSG case (React useState):** raw HTML is 110,963 tokens because Next.js embeds the full RSC payload in `__NEXT_DATA__`. dompruner detects the `__NEXT_DATA__` script tag, walks the RSC tuple tree directly, and produces 2,599 tokens — skipping the BeautifulSoup parse step entirely.

---

## Research Backing

**Web page context is too large for LLM agents**
FocusAgent (Oct 2025) confirms web pages routinely exceed tens of thousands of tokens, saturating context limits and increasing cost. Their LLM-based retriever achieves 50%+ observation size reduction. dompruner achieves 97%+ via deterministic DOM AST — no intermediate model, no hallucination risk in the preprocessing step.
→ [FocusAgent: Simple Yet Effective Ways of Trimming the Large Context of Web Agents (2025)](https://arxiv.org/abs/2510.03204)

**Relevant information in long contexts is systematically missed**
LLM accuracy degrades 30%+ when relevant content appears in the middle of a long context (U-shaped curve). Reducing from ~60K to ~1.6K tokens structurally eliminates this problem.
→ [Lost in the Middle: How Language Models Use Long Contexts — Liu et al., Stanford (2023)](https://arxiv.org/abs/2307.03172)

**BM25 is the strongest scalable retrieval default**
A 2026 controlled scaling study shows BM25 overtaking agentic search at 10M corpus tokens by ~20 points while remaining Pareto-optimal without LLM-based construction.
→ [BM25 Wins at Scale: A Scaling Study of RAG Paradigms (2026)](https://arxiv.org/abs/2607.26497)

---

## API Reference

### `run_pipeline(url, query="") → PipelineResult`

```python
@dataclass
class PipelineResult:
    url: str
    render_type: str                # "SSG" | "SSR" | "CSR"
    markdown: str
    original_tokens: int            # len(raw_html) // 4
    refined_tokens: int             # len(markdown) // 4
    reduction_ratio: float          # 1 - refined / original
    fetch_ms: float
    parse_ms: float
    bm25_confidence: float | None   # None = no query or zero-score fallback
    cached: bool                    # True = returned from LRU cache
    meta: dict                      # page-level metadata extracted from DOM
```

`meta` fields (present only when found in the page):

| Key | Source |
|-----|--------|
| `title` | `<title>` → `og:title` fallback |
| `description` | `meta[name=description]` → `og:description` |
| `author` | `meta[name=author]` → `article:author` |
| `published_time` | `article:published_time` |
| `modified_time` | `article:modified_time` |
| `canonical_url` | `<link rel="canonical">` |
| `lang` | `<html lang="...">` |
| `site_name` | `og:site_name` |

### `sync_run(coro) → PipelineResult`

Run `run_pipeline` from synchronous code safely. Handles Jupyter notebooks and frameworks with a running event loop (FastAPI, etc.) by offloading to a worker thread when needed.

```python
from dompruner import sync_run, run_pipeline
result = sync_run(run_pipeline(url, query))
```

### `DomPrunerLoader(url, query="")`

LangChain `BaseLoader`. Produces one `Document` per call. Supports `load()` (sync) and `alazy_load()` (async).

### `DomPrunerBatchLoader(urls, query="", concurrency=10, ignore_errors=True)`

LangChain `BaseLoader`. Fetches a list of URLs concurrently. `asyncio.Semaphore(concurrency)` caps simultaneous fetches. `ignore_errors=True` skips failed URLs silently. Supports `load()` and `alazy_load()`.

### `DomPrunerSitemapLoader(sitemap_url, query="", filter_urls=None, concurrency=10)`

LangChain `BaseLoader`. Resolves a sitemap (including recursive `sitemapindex`) and fetches all matching URLs. `filter_urls` accepts a list of URL prefixes — only pages whose URL starts with a prefix are fetched.

### `DomPrunerRetriever(urls, query_as_bm25=True, concurrency=10, ignore_errors=True)`

LangChain `BaseRetriever`. Plugs directly into `RetrievalQA`, `ConversationalRetrievalChain`, and any chain accepting a retriever. When `query_as_bm25=True`, the retrieval query is forwarded to dompruner's BM25 section filter.

### `DomPrunerFetchTool()`

LangChain `BaseTool`. Name: `dompruner_fetch`. Args: `url` (str), `query` (str, optional). Returns the pruned Markdown string. Supports `_run` (sync) and `_arun` (async).

### Cache

```python
from dompruner import get_cache

cache = get_cache()
print(cache.stats)   # {'hits': 12, 'misses': 3, 'evictions': 0}
cache.clear()
```

Default: `maxsize=256` (~1.5 MB), `ttl=300` seconds. Thundering herd protection via per-key `asyncio.Semaphore` + double-check pattern.

---

## Architecture

```
dompruner/
  __init__.py          — run_pipeline, sync_run, PipelineResult (public API)
  __main__.py          — CLI: python -m dompruner <url> [query] [--json]
  pipeline.py          — Orchestrator: fetch → detect → extract → BM25 → serialize
                         LRU+TTL cache + per-key Semaphore (thundering herd protection)
  fetcher.py           — Tiered HTTP fetch (httpx → UA rotation → Playwright)
  extractor.py         — L1→L2→L3 extraction cascade + extract_meta()
                         L1: FQN Router (CONTENT_TAGS selector + NOISE_TAGS prune)
                         L2: Heading Cluster (dev-doc detection, link density < 0.3)
                         L3: CETD Engine (text-density scoring)
  ssg.py               — __NEXT_DATA__ / Nuxt RSC tuple tree walker
  bm25.py              — BM25+ section filter (heading boost 2.5× + ancestor preservation)
  serializer.py        — FQNNode[] → Compact Markdown (tables, code, headings, lists)
  cache.py             — LRUTTLCache[V]: OrderedDict + asyncio.Lock + TTL eviction
  langchain/
    loader.py          — DomPrunerLoader (BaseLoader, single URL)
    batch_loader.py    — DomPrunerBatchLoader (BaseLoader, URL list, parallel)
    sitemap_loader.py  — DomPrunerSitemapLoader (BaseLoader, sitemap.xml recursive)
    retriever.py       — DomPrunerRetriever (BaseRetriever, for RetrievalQA)
    tool.py            — DomPrunerFetchTool (BaseTool, for agents)
```

**Faithful Python port:** the extraction logic (FQN Router, Heading Cluster, CETD, SSG RSC walker, BM25+ section filter) is a direct port of the [dompruner-mcp TypeScript implementation](https://github.com/dong7812/dompruner-mcp). All scoring constants, tag sets, and fallback thresholds match the original.

---

## Development

```bash
git clone https://github.com/dong7812/dompruner-py.git
cd dompruner-py
pip install -e ".[dev]"
pytest
```

Run the benchmark locally:

```bash
python bench.py
```

---

## Related

- **[dompruner-mcp](https://github.com/dong7812/dompruner-mcp)** — Node.js MCP server. Adds `dompruner_fetch` as an MCP tool to Claude Code, Claude Desktop, Cursor, Windsurf, and any MCP-compatible client. Zero install — `npx -y dompruner-mcp`.
- **[LangChain integrations overview](https://docs.langchain.com/oss/python/integrations/document_loaders)** — dompruner is listed as a third-party web loader. LangChain's current policy links out to maintainer repos rather than hosting integration docs directly.

---

## License

MIT
