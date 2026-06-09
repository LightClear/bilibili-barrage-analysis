from src.session_store import MemorySessionStore, hash_secret


def test_memory_session_store_creates_and_reads_session():
    store = MemorySessionStore()

    store.create("token-a", "demo", "csrf-a", expires_at=200.0, now=100.0)
    record = store.get("token-a", now=120.0)

    assert record["account"] == "demo"
    assert record["csrf_token"] == "csrf-a"
    assert record["created_at"] == 100.0
    assert record["last_seen_at"] == 120.0


def test_memory_session_store_cleans_all_related_state():
    store = MemorySessionStore()
    store.create("token-a", "demo", "csrf-a", expires_at=200.0, now=100.0)
    store.set_identity_role("token-a", "api")

    assert store.cleanup_expired(now=201.0) == 1

    assert store.accounts == {}
    assert store.csrf_tokens == {}
    assert store.identity_roles == {}
    assert store.expires_at == {}
    assert store.created_at == {}
    assert store.last_seen_at == {}


def test_mysql_projection_hashes_tokens_without_raw_secrets():
    store = MemorySessionStore()
    store.create("token-a", "demo", "csrf-a", expires_at=4_000_000_000.0, now=100.0)
    store.set_identity_role("token-a", "admin")

    row = store.mysql_projection("token-a")

    assert row["session_token_hash"] == hash_secret("token-a")
    assert row["csrf_token_hash"] == hash_secret("csrf-a")
    assert row["account"] == "demo"
    assert row["identity_role"] == "admin"
    assert "token-a" not in row.values()
    assert "csrf-a" not in row.values()
