from jra_srb.cache import SQLiteTTLCache


def test_sqlite_ttl_cache_persists_values(tmp_path):
    path = tmp_path / "cache.sqlite"
    cache = SQLiteTTLCache(path)
    cache.set("key", {"value": 1}, ttl_seconds=60)

    restored = SQLiteTTLCache(path)

    assert restored.get("key") == {"value": 1}


def test_sqlite_ttl_cache_can_return_expired_stale_value(tmp_path):
    path = tmp_path / "cache.sqlite"
    cache = SQLiteTTLCache(path)
    cache.set("key", {"value": 1}, ttl_seconds=-1)

    result = cache.get_with_status("key", allow_expired=True)

    assert result.hit is True
    assert result.expired is True
    assert result.value == {"value": 1}


def test_sqlite_ttl_cache_get_keeps_existing_expiry_behavior(tmp_path):
    path = tmp_path / "cache.sqlite"
    cache = SQLiteTTLCache(path)
    cache.set("key", {"value": 1}, ttl_seconds=-1)

    assert cache.get("key") is None
