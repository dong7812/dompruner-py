"""In-process LRU+TTL cache for pipeline results.

## 메모리 관리 설계 원칙

### 문제 1: 무제한 성장 (Unbounded growth)
  증상: URL을 계속 캐시하면 장기 실행 프로세스에서 OOM 발생 가능
  해결: maxsize 상한 + LRU(Least Recently Used) 퇴거
        → 가장 오래 사용되지 않은 엔트리를 먼저 제거
        → maxsize=256 기준 256 × ~6KB = ~1.5MB 상한 보장

### 문제 2: Lazy expiry (만료 후에도 메모리 잔류)
  증상: TTL이 지나도 접근이 없으면 만료 엔트리가 메모리에 남아있음
  해결: get() 시점 + set() 시점에 만료 엔트리 정리(evict_expired)
        → 완전한 즉시 정리는 아니지만 access 패턴 기반으로 충분히 제어 가능

### 문제 3: 비동기 동시성 (Race condition)
  증상: 여러 코루틴이 동시에 같은 키를 write할 때 중복 fetch 발생
  해결: asyncio.Lock으로 write 직렬화
        → read는 락 없이 허용 (dict read는 Python GIL로 안전)

### 문제 4: 캐시 키 충돌
  증상: URL이 같아도 query가 다르면 다른 결과 → URL만 키로 쓰면 덮어씌워짐
  해결: (url, query) 튜플을 복합 키로 사용

### 메모리 사용 추정
  평균 정제 결과: ~6KB (1,643 tokens × 4 bytes/token)
  maxsize=256:  256 × 6KB ≈ 1.5MB  ← 기본값
  maxsize=1024: 1024 × 6KB ≈ 6MB
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, TypeVar

V = TypeVar("V")


@dataclass
class _Entry(Generic[V]):
    value: V
    expires_at: float  # time.monotonic() 기준


class LRUTTLCache(Generic[V]):
    """LRU 퇴거 + TTL 만료를 결합한 비동기 안전 캐시.

    Args:
        maxsize: 최대 엔트리 수. 초과 시 가장 오래 사용되지 않은 항목 제거.
        ttl: 엔트리 유효 시간 (초). 0이면 캐시 비활성화.
    """

    def __init__(self, maxsize: int = 256, ttl: float = 300.0) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._store: OrderedDict[str, _Entry[V]] = OrderedDict()
        self._lock = asyncio.Lock()

    def _make_key(self, url: str, query: str) -> str:
        # query를 포함한 복합 키 — 같은 URL이라도 query가 다르면 별도 엔트리
        return f"{url}\x00{query}"

    def _is_alive(self, entry: _Entry[V]) -> bool:
        return time.monotonic() < entry.expires_at

    def _evict_expired(self) -> None:
        """만료된 엔트리를 제거한다. 락 없이 호출 가능 (단일 스레드 컨텍스트)."""
        dead = [k for k, e in self._store.items() if not self._is_alive(e)]
        for k in dead:
            del self._store[k]

    def get(self, url: str, query: str) -> V | None:
        """캐시에서 값을 읽는다. 만료됐거나 없으면 None 반환."""
        if self.ttl <= 0:
            return None
        key = self._make_key(url, query)
        entry = self._store.get(key)
        if entry is None:
            return None
        if not self._is_alive(entry):
            # 만료된 엔트리 즉시 제거
            del self._store[key]
            return None
        # LRU 갱신: 접근된 키를 맨 뒤로 이동
        self._store.move_to_end(key)
        return entry.value

    async def set(self, url: str, query: str, value: V) -> None:
        """값을 캐시에 저장한다. maxsize 초과 시 LRU 퇴거 후 저장."""
        if self.ttl <= 0:
            return
        key = self._make_key(url, query)
        async with self._lock:
            # 만료 엔트리 정리 (set 시점에 한 번씩 수행)
            self._evict_expired()
            # 이미 존재하면 갱신
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = _Entry(value=value, expires_at=time.monotonic() + self.ttl)
                return
            # maxsize 초과 시 가장 오래된 (LRU) 엔트리 제거
            while len(self._store) >= self.maxsize:
                self._store.popitem(last=False)
            self._store[key] = _Entry(value=value, expires_at=time.monotonic() + self.ttl)

    def clear(self) -> None:
        """캐시 전체 비우기."""
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def stats(self) -> dict[str, int]:
        now = time.monotonic()
        alive = sum(1 for e in self._store.values() if now < e.expires_at)
        return {"total": len(self._store), "alive": alive, "expired": len(self._store) - alive}
