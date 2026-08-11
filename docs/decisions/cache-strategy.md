# Cache Strategy Trade-off

**결정일:** 2026-08-11
**대상:** dompruner-py 인메모리 캐시 (`dompruner/cache.py`)

---

## 배경

동일 세션에서 같은 URL을 반복 fetch할 때 불필요한 네트워크 요청이 발생한다.
LangChain 파이프라인, 사이트맵 로더, 배치 로더에서 중복 fetch가 특히 빈번하다.

---

## 검토한 방식 3가지

### 방식 A: 2-tier 캐시 (L1 메모리 + L2 디스크)

```
L1 (메모리) miss → L2 (디스크) 조회 → L2 miss → 실제 fetch
```

| | 내용 |
|---|---|
| 장점 | 프로세스 재시작 후에도 캐시 유지, 대용량 캐시 가능 |
| 단점 | 파일 I/O 오버헤드, 직렬화/역직렬화 비용, 파일 잠금 복잡도 |
| 기각 이유 | dompruner-py는 라이브러리로 단발성 스크립트에서 사용됨. 세션이 짧아 L2에 써도 다음 세션에서 히트할 확률이 낮음. 웹 콘텐츠는 빠르게 변해 디스크 캐시가 금방 stale해짐 |
| 적합한 경우 | 장기 실행 데몬, 재시작 후 워밍업 비용을 줄여야 할 때 |

### 방식 B: Memory Pool

```
사전 할당된 고정 크기 블록에서 슬롯을 점유/반납
```

| | 내용 |
|---|---|
| 장점 | 메모리 단편화 없음, 할당 속도 예측 가능 |
| 단점 | Python CPython이 이미 내부 allocator를 가짐. 애플리케이션 레벨 pool이 실질적 제어 불가. 캐시 엔트리(markdown 문자열) 크기가 URL마다 달라 균일 슬롯 설계 불가 |
| 기각 이유 | Python에서는 CPython allocator가 pool 역할을 이미 수행. `mmap`/`bytearray`로 구현 시 직렬화 오버헤드가 이점을 상쇄 |
| 적합한 경우 | C/C++/Rust 시스템, 고정 크기 데이터, 초고빈도 할당 |

### 방식 C: LRU + TTL 인메모리 캐시 ✅ 채택

```
OrderedDict 기반 LRU + 만료 시각(monotonic clock) 비교
```

| | 내용 |
|---|---|
| 장점 | 추가 의존성 없음, maxsize로 메모리 상한 보장, asyncio.Lock으로 비동기 안전, 구현 단순 |
| 단점 | 프로세스 재시작 시 캐시 소실, lazy eviction(접근 없으면 만료 엔트리가 메모리에 잔류) |
| 채택 이유 | dompruner-py 사용 패턴(단발 스크립트, 세션 내 중복 제거)에 정확히 맞음 |

---

## 채택된 설계의 메모리 관리 상세

### 문제 1: 무제한 성장 (Unbounded growth)
- **해결:** `maxsize` 상한 + LRU 퇴거
- **수치:** maxsize=256 × 평균 6KB = **~1.5MB 상한**
- **동작:** `OrderedDict.popitem(last=False)` — 가장 오래 사용되지 않은 항목 제거

### 문제 2: Lazy expiry (만료 후 메모리 잔류)
- **해결:** `get()` 및 `set()` 시점에 `evict_expired()` 호출
- **한계:** 완전한 즉시 정리가 아닌 access 기반 정리. 장기간 미접근 만료 엔트리는 잔류 가능
- **허용 이유:** 단발 스크립트에서는 프로세스 종료가 GC 역할을 대신함

### 문제 3: 비동기 동시성 (Race condition)
- **해결:** `asyncio.Lock`으로 write 직렬화
- **read는 락 없음:** Python GIL이 dict read를 atomic하게 보장

### 문제 4: 캐시 키 충돌
- **해결:** `(url, query)` 복합 키
- **구분자:** `\x00` (URL/query에 등장하지 않는 null byte)

---

## 메모리 사용 추정

| maxsize | 평균 엔트리 크기 | 최대 메모리 |
|:---:|:---:|:---:|
| 64 | ~6KB | ~0.4MB |
| 256 (기본값) | ~6KB | ~1.5MB |
| 1024 | ~6KB | ~6MB |

---

## 향후 고려 사항

- **장기 실행 서버로 전환 시:** `diskcache` 또는 Redis 기반 L2 추가
- **메모리 민감 환경:** `maxsize` 축소 또는 `ttl=0`으로 캐시 비활성화
- **캐시 워밍업:** 자주 쓰는 URL 목록을 `DomPrunerBatchLoader`로 사전 fetch
