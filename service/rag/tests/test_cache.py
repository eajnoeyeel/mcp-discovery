import time
from unittest.mock import patch

from service.rag.cache import QueryCache


class TestQueryCache:
    def test_get_miss_returns_none(self):
        cache = QueryCache(ttl_seconds=300)
        assert cache.get("unknown_query") is None

    def test_put_and_get_hit(self):
        cache = QueryCache(ttl_seconds=300)
        cache.put("hello", {"results": [1, 2, 3]})
        assert cache.get("hello") == {"results": [1, 2, 3]}

    def test_expired_entry_returns_none(self):
        cache = QueryCache(ttl_seconds=1)
        cache.put("hello", {"data": "old"})
        with patch("time.time", return_value=time.time() + 2):
            assert cache.get("hello") is None

    def test_put_overwrites_existing(self):
        cache = QueryCache(ttl_seconds=300)
        cache.put("q", "v1")
        cache.put("q", "v2")
        assert cache.get("q") == "v2"

    def test_clear_removes_all(self):
        cache = QueryCache(ttl_seconds=300)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_size_returns_count(self):
        cache = QueryCache(ttl_seconds=300)
        assert cache.size == 0
        cache.put("a", 1)
        assert cache.size == 1
