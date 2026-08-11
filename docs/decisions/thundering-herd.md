# Thundering Herd 방지 전략 Trade-off

**결정일:** 2026-08-11
**대상:** `run_pipeline()` 동시 요청 처리 (`dompruner/pipeline.py`)

---

## 문제

같은 URL에 N개 코루틴이 동시에 요청할 때, 모두 캐시 미스를 확인하고
N번의 실제 fetch를 시작하는 **Thundering herd** 현상이 발생한다.

```
코루틴 1: cache.get() → None → fetch 시작
코루틴 2: cache.get() → None → fetch 시작  ← 중복!
코루틴 3: cache.get() → None → fetch 시작  ← 중복!
...
```

부하 테스트 결과: 30개 동시 요청 → 30번 fetch 발생 (기대: 1번)

---

## 검토한 방식

### 방식 A: Single-flight (Future 공유)

```python
_inflight: dict[str, asyncio.Future] = {}

async def run_pipeline(url, query=""):
    if key in _inflight:
        return await _inflight[key]      # 진행 중인 Future 대기
    future = loop.create_future()
    _inflight[key] = future
    try:
        result = await _do_fetch()
        future.set_result(result)        # 대기 중인 전체에게 동시 전달
        return result
    finally:
        del _inflight[key]
```

| | 내용 |
|---|---|
| 장점 | fetch 1회 → N개 코루틴이 동시에 결과 수신, 처리량 최대 |
| 단점 | Future 생명주기 관리 복잡, 예외 전파 주의 필요, 코드 가독성 낮음 |
| 리스크 | future.set_exception() 누락 시 대기 코루틴이 영구 블록 |

### 방식 B: Per-key Semaphore + Double-check ✅ 채택

```python
_key_sems: dict[str, asyncio.Semaphore] = {}

async def run_pipeline(url, query=""):
    hit = _cache.get(url, query)        # 1. 빠른 경로
    if hit: return _as_cached(hit)

    async with _key_sems.setdefault(key, asyncio.Semaphore(1)):
        hit = _cache.get(url, query)    # 2. Double-check (락 안에서 재확인)
        if hit: return _as_cached(hit)
        result = await _do_fetch()
        await _cache.set(url, query, result)
        return result
```

| | 내용 |
|---|---|
| 장점 | 동작이 직관적, 예외 처리가 `async with`로 자동화, 코드 가독성 높음 |
| 단점 | 대기 코루틴들이 순차로 세마포어를 획득 → single-flight 대비 미세하게 느림 |
| 안전성 | `async with`가 예외 상황에서도 반드시 잠금 해제 보장 |

### 방식 B의 처리 순서 (30개 동시 요청 예시)

```
코루틴 1: sem 획득 → double-check 미스 → fetch → 캐시 저장 → sem 해제
코루틴 2: sem 획득 → double-check 히트 → 즉시 반환    ← 네트워크 없음
코루틴 3: sem 획득 → double-check 히트 → 즉시 반환    ← 네트워크 없음
...
```

fetch는 1회, 나머지 29개는 캐시 히트로 처리.

---

## 부하 테스트 결과

| 시나리오 | 결과 |
|---|---|
| 30개 동시 요청 / 같은 URL | fetch **1회**, 캐시 히트 **29회** ✅ |
| 20개 URL 배치 로드 (concurrency=5) | 4.8× 속도 향상, 동시 실행 상한 준수 ✅ |
| 300개 URL 캐시 (maxsize=256) | 엔트리 **256개** 유지, 메모리 증가 **548KB** ✅ |

---

## 채택 이유

dompruner-py는 단발 스크립트 / LangChain 체인에서 사용되는 라이브러리다.
동시 요청이 수백 개를 넘는 경우가 드물고, 코드 안전성이 처리량보다 중요하다.
Semaphore 방식의 미세한 성능 손실은 실사용 환경에서 무시 가능한 수준이다.

---

## 향후 고려 사항

고처리량이 필요한 환경(장기 실행 서버, 수백 개 동시 요청)으로 확장 시
Single-flight 방식으로 전환을 검토한다.

→ [GitHub Issue #1: Single-flight upgrade for high-throughput scenarios](https://github.com/dong7812/dompruner-py/issues/1)
