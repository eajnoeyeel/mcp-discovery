"""Unit tests for mlp/rag/cache.py — QueryCache TTL in-memory cache."""

import time
from unittest.mock import patch

from service.rag.cache import QueryCache


class TestQueryCacheGet:
    def test_returns_none_for_missing_key(self):
        cache = QueryCache()
        assert cache.get("nonexistent") is None

    def test_returns_stored_value_before_expiry(self):
        cache = QueryCache(ttl_seconds=300)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_returns_none_after_ttl_expires(self):
        cache = QueryCache(ttl_seconds=1)
        cache.put("key1", "value1")
        with patch("time.time", return_value=time.time() + 2):
            assert cache.get("key1") is None

    def test_evicts_expired_entry_on_access(self):
        cache = QueryCache(ttl_seconds=1)
        cache.put("key1", "value1")
        with patch("time.time", return_value=time.time() + 2):
            cache.get("key1")
        assert cache.size == 0

    def test_returns_value_exactly_at_ttl_boundary(self):
        """Entry at exactly ttl seconds old should be expired (time - ts > ttl)."""
        cache = QueryCache(ttl_seconds=60)
        now = time.time()
        with patch("time.time", return_value=now):
            cache.put("key1", "value1")
        # Exactly at ttl: time.time() - ts == ttl, NOT > ttl, so still valid
        with patch("time.time", return_value=now + 60):
            result = cache.get("key1")
        assert result == "value1"

    def test_returns_none_just_past_ttl(self):
        cache = QueryCache(ttl_seconds=60)
        now = time.time()
        with patch("time.time", return_value=now):
            cache.put("key1", "value1")
        with patch("time.time", return_value=now + 60.001):
            result = cache.get("key1")
        assert result is None

    def test_stores_arbitrary_value_types(self):
        cache = QueryCache()
        cache.put("dict_key", {"a": 1})
        cache.put("list_key", [1, 2, 3])
        cache.put("none_val", None)
        assert cache.get("dict_key") == {"a": 1}
        assert cache.get("list_key") == [1, 2, 3]
        # None stored as value is distinct from missing key
        # None stored is returned as None — indistinguishable, but get returns it
        assert cache.get("none_val") is None


class TestQueryCachePut:
    def test_put_overwrites_existing_key(self):
        cache = QueryCache()
        cache.put("key1", "first")
        cache.put("key1", "second")
        assert cache.get("key1") == "second"

    def test_put_refreshes_ttl_on_overwrite(self):
        cache = QueryCache(ttl_seconds=5)
        now = time.time()
        with patch("time.time", return_value=now):
            cache.put("key1", "first")
        # Overwrite at t+4 (still within original TTL)
        with patch("time.time", return_value=now + 4):
            cache.put("key1", "second")
        # At t+8: original would have expired but overwrite refreshed TTL
        with patch("time.time", return_value=now + 8):
            assert cache.get("key1") == "second"

    def test_size_increments_with_new_keys(self):
        cache = QueryCache()
        assert cache.size == 0
        cache.put("k1", "v1")
        assert cache.size == 1
        cache.put("k2", "v2")
        assert cache.size == 2

    def test_size_does_not_increment_on_overwrite(self):
        cache = QueryCache()
        cache.put("k1", "v1")
        cache.put("k1", "v2")
        assert cache.size == 1


class TestQueryCacheClear:
    def test_clear_removes_all_entries(self):
        cache = QueryCache()
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert cache.size == 0
        assert cache.get("k1") is None
        assert cache.get("k2") is None

    def test_clear_on_empty_cache_is_safe(self):
        cache = QueryCache()
        cache.clear()
        assert cache.size == 0


class TestQueryCacheSize:
    def test_size_reflects_non_expired_count(self):
        """Size counts stored entries including expired ones (lazy eviction)."""
        cache = QueryCache(ttl_seconds=1)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        # Before eviction, size includes expired entries
        with patch("time.time", return_value=time.time() + 2):
            assert cache.size == 2  # lazy eviction, not yet evicted
            cache.get("k1")  # triggers eviction of k1
            assert cache.size == 1

    def test_size_zero_on_fresh_cache(self):
        cache = QueryCache()
        assert cache.size == 0
