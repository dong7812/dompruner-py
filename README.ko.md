# dompruner

English | [한국어](./README.ko.md)

> [dompruner-mcp](https://github.com/dong7812/dompruner-mcp)의 Python 포트 — LangChain, LlamaIndex, 직접 사용을 위한 DOM AST 정제.

LLM 에이전트가 웹 페이지를 가져오면, 필요 없는 수만 토큰의 raw HTML을 받게 됩니다 — 네비게이션, 광고, 스크립트, 푸터. dompruner는 DOM AST 파싱으로 이것들을 제거하고 **원본 콘텐츠를 그대로 모델에 전달**합니다. 중간 요약 모델도, API 키도, 벡터 데이터베이스도 필요 없습니다.

```
> docs.python.org/3/library/asyncio-task.html
> Raw HTML   44,315 토큰
> dompruner   1,275 토큰  (97.1% 절감)
```

---

## 설치

```bash
pip install dompruner
```

JavaScript 렌더링 페이지 지원 (선택 사항):

```bash
pip install "dompruner[playwright]" && playwright install chromium
```

---

## 사용법

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
print(f"{result.original_tokens:,} → {result.refined_tokens:,} 토큰 ({result.reduction_ratio:.1%})")
print(result.meta)  # {'title': '...', 'lang': 'en', 'description': '...', ...}
```

### LangChain

```python
from dompruner.langchain import DomPrunerLoader

docs = DomPrunerLoader(
    "https://fastapi.tiangolo.com/tutorial/body/",
    query="request body",   # BM25 섹션 필터 (선택 사항)
).load()
# docs[0].metadata 에 포함: source, render_type, reduction_ratio,
#   bm25_confidence, cached, title, description, lang, author, ...
```

→ **[LangChain 통합 가이드](./docs/langchain.ko.md)** — Loader, BatchLoader, SitemapLoader, Retriever, Tool

---

## 동작 원리

```
URL → fetch (httpx → UA 로테이션 → Playwright) → 렌더 타입 감지
       └─ SSG: __NEXT_DATA__ RSC 트리 탐색 → Markdown
       └─ SSR/CSR: DOM AST 파이프라인
                    L1 FQN Router → L2 Heading Cluster → L3 CETD Engine
                    → BM25+ 섹션 필터 → Compact Markdown
```

→ **[아키텍처 & 내부 구조](./docs/architecture.ko.md)**

---

## 관련 프로젝트

- **[dompruner-mcp](https://github.com/dong7812/dompruner-mcp)** — Claude Code, Claude Desktop, Cursor, Windsurf용 MCP 서버. 별도 설치 없이 `npx -y dompruner-mcp`.
- **[LangChain 통합 목록](https://docs.langchain.com/oss/python/integrations/document_loaders)** — 서드파티 웹 로더로 등재.

---

## 라이선스

MIT
