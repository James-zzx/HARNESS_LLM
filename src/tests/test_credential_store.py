import pytest

from harness.credential_store import CredentialStore, MemoryBackend


@pytest.fixture
def store():
    return CredentialStore(backend=MemoryBackend())


def test_set_and_get(store):
    store.set_key("test-service", "api_key", "sk-abc123")
    assert store.get_key("test-service", "api_key") == "sk-abc123"


def test_delete(store):
    store.set_key("test-service", "api_key", "sk-abc123")
    store.delete_key("test-service", "api_key")
    assert store.get_key("test-service", "api_key") is None


def test_list_hides_plaintext(store):
    store.set_key("test-service", "api_key", "sk-super-secret-value")
    store.set_key("test-service", "model", "gpt-4o-mini")
    keys = store.list_keys("test-service")
    assert "api_key" in keys
    assert "model" in keys
    assert "sk-super-secret-value" not in keys
    assert "gpt-4o-mini" not in keys


def test_key_not_found(store):
    assert store.get_key("test-service", "no-such-key") is None
