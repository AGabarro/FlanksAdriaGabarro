import os
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from threading import Lock

from cachetools import TTLCache

DEFAULT_TTL_SECONDS = 60.0
DEFAULT_MAXSIZE = 256

_MISSING = object()


@dataclass(frozen=True, slots=True)
class CacheStats:
    hits: int
    misses: int
    size: int
    maxsize: int
    ttl_seconds: float


class SummaryCache:
    def __init__(
        self, maxsize: int = DEFAULT_MAXSIZE, ttl: float = DEFAULT_TTL_SECONDS
    ) -> None:
        self._cache: TTLCache[Hashable, object] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get_or_compute[T](self, key: Hashable, compute: Callable[[], T]) -> tuple[T, bool]:
        with self._lock:
            cached = self._cache.get(key, _MISSING)
            if cached is not _MISSING:
                self._hits += 1
                return cached, True  # type: ignore[return-value]
            self._misses += 1

        value = compute()

        with self._lock:
            self._cache[key] = value
        return value, False

    def invalidate(self) -> int:
        with self._lock:
            dropped = len(self._cache)
            self._cache.clear()
            return dropped

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                size=len(self._cache),
                maxsize=self._cache.maxsize,
                ttl_seconds=self._cache.ttl,
            )

    def reset(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = self._misses = 0


summary_cache = SummaryCache(
    ttl=float(os.getenv("SUMMARY_CACHE_TTL_SECONDS", DEFAULT_TTL_SECONDS))
)
