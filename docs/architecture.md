# Architecture

## Pipeline Overview

```
URL
 └─▶ fetch_page()       — tiered fetch: direct → UA rotation → Playwright fallback
      │
      ├─▶ [SSG]  extract_ssg_markdown()
      │           walks __NEXT_DATA__ RSC tuple tree → clean Markdown
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

---

## Render Type Detection

| Type | Signal | Strategy |
|---|---|---|
| SSG | `__NEXT_DATA__`, `window.__NUXT__`, `window.page` | RSC tuple tree walk — DOM parse skipped |
| SSR | Body text density ≥ 2% | Full DOM AST pipeline (L1→L2→L3) |
| CSR | Body text density < 2% | DOM AST pipeline (partial content) + Playwright fallback |

---

## Tiered Fetch

| Level | Trigger | Method |
|---|---|---|
| L1 | Default | `httpx` direct fetch |
| L2 | 403 / 429 response | User-Agent rotation (3 browser strings) |
| L3 | CSR detected or L2 fails | `playwright` headless browser (optional) |

4xx/5xx responses other than 403/429 raise immediately — no unnecessary fallback for pages that genuinely don't exist.

---

## Extraction Cascade (L1 → L2 → L3)

Each layer runs only if the previous layer's output doesn't meet the coverage threshold (≥4 nodes, ≥200 chars total).

**L1 — FQN Router:** walks the full DOM, keeps semantic content tags (`p`, `h1–h5`, `li`, `pre`, `code`, `table`), prunes noise subtrees (`nav`, `footer`, `aside`, `script`, `form`, ...).

**L2 — Heading Cluster:** detects developer documentation structure. Requires ≥2 `h2–h4` headings with meaningful content (avg ≥400 chars/cluster) and link density < 0.3. Groups content under its nearest heading.

**L3 — CETD Engine:** text-density scoring over container elements (`article`, `main`, `section`, `div`). Selects the subtree with the highest `(text_len / tag_count) × (1 − link_ratio) × depth_penalty` score. Last resort fallback.

---

## BM25+ Section Filter

When `query` is provided **and** the extracted content exceeds 1,200 tokens **and** there are more than 2 sections, extracted sections are scored and ranked. Three adjustments over standard BM25:

- **Heading boost (2.5×)** — sections under a relevant heading rank higher
- **Depth decay (0.4)** — deeply nested nodes score lower than top-level content
- **Ancestor preservation** — parent headings of selected sections are always included for context

Sections are selected greedily until a 1,200-token budget is reached.

**Zero-score fallback:** if the query terms match nothing (BM25 max = 0), the full clean content is returned instead of an empty result. `bm25_confidence` is set to `0.0` in this case (as opposed to `None`, which means no query was provided).

---

## Session Cache

LRU + TTL in-process cache. Default: `maxsize=256`, `ttl=300s`.

- Shared across all pipeline calls in the same process — duplicate fetches within a LangChain chain cost zero network.
- Per-key `asyncio.Semaphore` prevents thundering herd: concurrent calls to the same URL serialize, with all waiters getting the cached result after the first completes.
- Cache key: `url + "\x00" + query`.

```python
from dompruner import get_cache

cache = get_cache()
print(cache.stats)  # {'hits': 12, 'misses': 3, 'evictions': 0}
cache.clear()
```

Design decision details: [docs/decisions/cache-strategy.md](./decisions/cache-strategy.md), [docs/decisions/thundering-herd.md](./decisions/thundering-herd.md)

---

## Module Map

```
dompruner/
  __init__.py          — run_pipeline, sync_run, PipelineResult (public API)
  __main__.py          — CLI: python -m dompruner <url> [query] [--json]
  pipeline.py          — Orchestrator: fetch → detect → extract → BM25 → serialize
                         LRU+TTL cache + per-key Semaphore
  fetcher.py           — Tiered HTTP fetch (httpx → UA rotation → Playwright)
  extractor.py         — L1→L2→L3 extraction cascade + extract_meta()
  ssg.py               — __NEXT_DATA__ / Nuxt RSC tuple tree walker
  bm25.py              — BM25+ section filter
  serializer.py        — FQNNode[] → Compact Markdown (tables, code, headings, lists)
  cache.py             — LRUTTLCache[V]: OrderedDict + asyncio.Lock + TTL eviction
  langchain/
    loader.py          — DomPrunerLoader (BaseLoader, single URL)
    batch_loader.py    — DomPrunerBatchLoader (BaseLoader, URL list, parallel)
    sitemap_loader.py  — DomPrunerSitemapLoader (BaseLoader, sitemap.xml recursive)
    retriever.py       — DomPrunerRetriever (BaseRetriever)
    tool.py            — DomPrunerFetchTool (BaseTool)
```

Faithful Python port of [dompruner-mcp](https://github.com/dong7812/dompruner-mcp). All scoring constants, tag sets, and fallback thresholds match the original TypeScript implementation.

---

## Research Backing

**Web page context is too large for LLM agents**
FocusAgent (Oct 2025) confirms web pages routinely exceed tens of thousands of tokens, saturating context limits and increasing cost. Their LLM-based retriever achieves 50%+ observation size reduction; dompruner achieves 97%+ via deterministic DOM AST — no intermediate model, no hallucination risk.
→ [FocusAgent (2025)](https://arxiv.org/abs/2510.03204)

**Relevant information in long contexts is systematically missed**
LLM accuracy degrades 30%+ when relevant content appears mid-context (U-shaped curve). Reducing from ~60K to ~1.6K tokens structurally eliminates this problem.
→ [Lost in the Middle — Liu et al., Stanford (2023)](https://arxiv.org/abs/2307.03172)

**BM25 is the strongest scalable retrieval default**
A 2026 scaling study shows BM25 overtaking agentic search at 10M corpus tokens by ~20 points while remaining Pareto-optimal.
→ [BM25 Wins at Scale (2026)](https://arxiv.org/abs/2607.26497)
