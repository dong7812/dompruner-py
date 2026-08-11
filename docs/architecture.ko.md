# 아키텍처

## 파이프라인 개요

```
URL
 └─▶ fetch_page()       — 단계별 fetch: 직접 → UA 로테이션 → Playwright 폴백
      │
      ├─▶ [SSG]  extract_ssg_markdown()
      │           __NEXT_DATA__ RSC 튜플 트리 탐색 → Markdown
      │           DOM 파싱 생략
      │
      └─▶ [SSR/CSR]  BeautifulSoup DOM 트리  (1회 파싱 — 콘텐츠 + 메타 공유)
                └─▶ FQN Router (L1)        p / h1–h5 / li / pre / code / table 유지
                     │                     nav / footer / aside / form 제거
                     └─▶ Heading Cluster (L2)  개발 문서 구조 감지
                          └─▶ CETD Engine (L3)  텍스트 밀도 스코어링 폴백
                               └─▶ BM25+ 섹션 필터  쿼리 기반 랭킹
                                    └─▶ Compact Markdown  ──▶  LLM 컨텍스트
```

---

## 렌더 타입 감지

| 타입 | 감지 신호 | 처리 전략 |
|---|---|---|
| SSG | `__NEXT_DATA__`, `window.__NUXT__`, `window.page` | RSC 튜플 트리 탐색 — DOM 파싱 생략 |
| SSR | 본문 텍스트 밀도 ≥ 2% | 전체 DOM AST 파이프라인 (L1→L2→L3) |
| CSR | 본문 텍스트 밀도 < 2% | DOM AST 파이프라인 + Playwright 폴백 |

---

## 단계별 Fetch

| 단계 | 트리거 | 방법 |
|---|---|---|
| L1 | 기본 | `httpx` 직접 요청 |
| L2 | 403 / 429 응답 | User-Agent 로테이션 (브라우저 UA 3종) |
| L3 | CSR 감지 또는 L2 실패 | `playwright` 헤드리스 브라우저 (선택 설치) |

403/429 이외의 4xx/5xx는 즉시 에러로 전파합니다 — 존재하지 않는 페이지에 불필요한 폴백 시도를 하지 않습니다.

---

## 추출 캐스케이드 (L1 → L2 → L3)

각 레이어는 이전 레이어의 출력이 커버리지 기준(노드 4개 이상, 총 200자 이상)을 충족하지 못할 때만 실행됩니다.

**L1 — FQN Router:** 전체 DOM을 탐색하여 시맨틱 콘텐츠 태그(`p`, `h1–h5`, `li`, `pre`, `code`, `table`)를 유지하고 노이즈 서브트리(`nav`, `footer`, `aside`, `script`, `form` 등)를 제거합니다.

**L2 — Heading Cluster:** 개발 문서 구조를 감지합니다. `h2–h4` 헤딩이 2개 이상이고, 클러스터당 평균 400자 이상, 링크 밀도 0.3 미만인 경우에만 활성화됩니다. 콘텐츠를 가장 가까운 헤딩 아래로 그룹화합니다.

**L3 — CETD Engine:** 컨테이너 요소(`article`, `main`, `section`, `div`) 전체에 텍스트 밀도 스코어를 부여합니다. `(텍스트 길이 / 태그 수) × (1 − 링크 비율) × 깊이 패널티`가 가장 높은 서브트리를 선택합니다. 마지막 폴백입니다.

---

## BM25+ 섹션 필터

`query`가 주어지고, 추출된 콘텐츠가 **1,200 토큰을 초과**하며, **섹션이 2개를 넘을 때** 섹션을 점수화하여 랭킹합니다. 표준 BM25에서 세 가지를 조정합니다:

- **헤딩 부스트 (2.5×)** — 관련 헤딩 아래 섹션이 더 높은 점수를 받습니다
- **깊이 감쇠 (0.4)** — 깊이 중첩된 노드는 최상위 콘텐츠보다 낮은 점수를 받습니다
- **조상 헤딩 보존** — 선택된 섹션의 부모 헤딩은 항상 컨텍스트 유지를 위해 포함됩니다

1,200 토큰 예산에 맞게 섹션을 탐욕적으로 선택합니다.

**제로 스코어 폴백:** 쿼리 키워드가 문서 어디에도 매칭되지 않으면(BM25 최대값 = 0), 빈 결과 대신 정제된 전체 콘텐츠를 반환합니다. 이 경우 `bm25_confidence`는 `0.0`으로 설정됩니다(`None`은 query 자체가 없었을 때의 값과 구분됩니다).

---

## 세션 캐시

LRU + TTL 인메모리 캐시. 기본값: `maxsize=256`, `ttl=300초`.

- 같은 프로세스 내 모든 파이프라인 호출이 공유 — LangChain 체인 내 중복 fetch는 네트워크 비용이 0입니다.
- per-key `asyncio.Semaphore`로 thundering herd 방지: 동일 URL에 대한 동시 호출은 직렬화되며, 대기 중인 모든 코루틴은 첫 번째가 완료된 후 캐시 결과를 받습니다.
- 캐시 키: `url + "\x00" + query`.

```python
from dompruner import get_cache

cache = get_cache()
print(cache.stats)  # {'hits': 12, 'misses': 3, 'evictions': 0}
cache.clear()
```

설계 결정 상세: [docs/decisions/cache-strategy.md](./decisions/cache-strategy.md), [docs/decisions/thundering-herd.md](./decisions/thundering-herd.md)

---

## 모듈 구조

```
dompruner/
  __init__.py          — run_pipeline, sync_run, PipelineResult (공개 API)
  __main__.py          — CLI: python -m dompruner <url> [query] [--json]
  pipeline.py          — 오케스트레이터: fetch → 감지 → 추출 → BM25 → 직렬화
                         LRU+TTL 캐시 + per-key Semaphore
  fetcher.py           — 단계별 HTTP fetch (httpx → UA 로테이션 → Playwright)
  extractor.py         — L1→L2→L3 추출 캐스케이드 + extract_meta()
  ssg.py               — __NEXT_DATA__ / Nuxt RSC 튜플 트리 탐색기
  bm25.py              — BM25+ 섹션 필터
  serializer.py        — FQNNode[] → Compact Markdown (테이블, 코드, 헤딩, 목록)
  cache.py             — LRUTTLCache[V]: OrderedDict + asyncio.Lock + TTL 만료
  langchain/
    loader.py          — DomPrunerLoader (BaseLoader, 단일 URL)
    batch_loader.py    — DomPrunerBatchLoader (BaseLoader, URL 목록, 병렬)
    sitemap_loader.py  — DomPrunerSitemapLoader (BaseLoader, sitemap.xml 재귀)
    retriever.py       — DomPrunerRetriever (BaseRetriever)
    tool.py            — DomPrunerFetchTool (BaseTool)
```

[dompruner-mcp](https://github.com/dong7812/dompruner-mcp) TypeScript 구현체의 충실한 Python 포트입니다. 모든 스코어링 상수, 태그 집합, 폴백 임계값이 원본과 일치합니다.

---

## 연구 배경

**웹 페이지 컨텍스트는 LLM 에이전트에게 너무 큽니다**
FocusAgent (2025년 10월)는 웹 페이지가 수만 토큰을 초과하여 컨텍스트 한계를 포화시키고 비용을 증가시킨다는 것을 확인했습니다. 그들의 LLM 기반 리트리버는 관찰 크기를 50%+ 줄이는 반면, dompruner는 결정론적 DOM AST로 97%+를 달성합니다 — 중간 모델 없음, 전처리 단계에서의 환각 위험 없음.
→ [FocusAgent (2025)](https://arxiv.org/abs/2510.03204)

**긴 컨텍스트에서 관련 정보는 체계적으로 누락됩니다**
관련 콘텐츠가 긴 컨텍스트 중간에 위치할 때 LLM 정확도가 30%+ 저하됩니다 (U자형 곡선). ~60K에서 ~1.6K 토큰으로 줄이면 이 문제가 구조적으로 해소됩니다.
→ [Lost in the Middle — Liu et al., Stanford (2023)](https://arxiv.org/abs/2307.03172)

**BM25는 확장 가능한 가장 강력한 기본 검색 방법입니다**
2026년 스케일링 연구에 따르면 BM25가 1,000만 코퍼스 토큰에서 에이전틱 검색보다 ~20포인트 앞서며 파레토 최적을 유지합니다.
→ [BM25 Wins at Scale (2026)](https://arxiv.org/abs/2607.26497)
