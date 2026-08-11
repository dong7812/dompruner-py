# dompruner

English | [한국어](./README.ko.md)

> DOM AST web loader for LLM pipelines — strips nav/ads/scripts via DOM AST parsing and delivers original content, token-efficient, to your model.

When an LLM agent fetches a web page, it receives tens of thousands of raw HTML tokens it doesn't need — navigation, ads, scripts, footers. dompruner strips all of that via DOM AST parsing and passes the **original content, unchanged, directly to the model**. No intermediate summarization model, no API key, no vector database.

```
> docs.python.org/3/library/asyncio-task.html  (query: "create_task")
> Raw HTML   44,315 tokens
> dompruner   1,275 tokens  (97.1% reduction, BM25 section filter applied)
```

---

## Install

```bash
pip install dompruner
```

For JavaScript-rendered pages (optional):

```bash
pip install "dompruner[playwright]" && playwright install chromium
```

---

## Usage

### CLI

```bash
python -m dompruner https://docs.python.org/3/library/asyncio-task.html
python -m dompruner https://docs.python.org/3/library/asyncio-task.html "create_task"
python -m dompruner https://docs.python.org/3/library/asyncio-task.html --json
```

### Python

```python
import asyncio
from dompruner import run_pipeline

result = asyncio.run(run_pipeline(
    "https://docs.python.org/3/library/asyncio-task.html",
    query="create_task",
))
print(result.markdown)
print(f"{result.original_tokens:,} → {result.refined_tokens:,} tokens ({result.reduction_ratio:.1%})")
print(result.meta)  # {'title': '...', 'lang': 'en', 'description': '...', ...}
```

### LangChain

```python
from dompruner.langchain import DomPrunerLoader

docs = DomPrunerLoader(
    "https://fastapi.tiangolo.com/tutorial/body/",
    query="request body",
).load()
# docs[0].metadata includes: source, render_type, reduction_ratio,
#   bm25_confidence, cached, title, description, lang, author, ...
```

→ **[Full LangChain integration guide](./docs/langchain.md)** — Loader, BatchLoader, SitemapLoader, Retriever, Tool

---

## How It Works

```
URL → fetch (httpx → UA rotation → Playwright) → render type detection
       └─ SSG: __NEXT_DATA__ RSC tree walk → Markdown
       └─ SSR/CSR: DOM AST pipeline
                    L1 FQN Router → L2 Heading Cluster → L3 CETD Engine
                    → BM25+ Section Filter → Compact Markdown
```

→ **[Architecture & internals](./docs/architecture.md)**

---

## Related

- **[dompruner-mcp](https://github.com/dong7812/dompruner-mcp)** — MCP server for Claude Code, Claude Desktop, Cursor, Windsurf. Zero install — `npx -y dompruner-mcp`.
- **[LangChain integrations](https://docs.langchain.com/oss/python/integrations/document_loaders)** — listed as a third-party web loader.

---

## License

MIT
