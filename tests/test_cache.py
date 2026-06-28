from jra_srb.cache import SQLiteTTLCache


def test_sqlite_ttl_cache_persists_values(tmp_path):
    path = tmp_path / "cache.sqlite"
    cache = SQLiteTTLCache(path)
    cache.set("key", {"value": 1}, ttl_seconds=60)

    restored = SQLiteTTLCache(path)

    assert restored.get("key") == {"value": 1}
