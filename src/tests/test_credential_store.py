import pytest

from harness.credential_store import CredentialStore, EnvBackend, MemoryBackend


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


def test_env_backend_reads_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_LLM_API_KEY", "sk-env-value")
    env_store = CredentialStore(backend=EnvBackend())

    assert env_store.get_key("llm", "api_key") == "sk-env-value"


def test_env_backend_delete_removes(monkeypatch):
    monkeypatch.setenv("HARNESS_LLM_API_KEY", "sk-env-value")
    env_store = CredentialStore(backend=EnvBackend())

    env_store.delete_key("llm", "api_key")

    assert env_store.get_key("llm", "api_key") is None


def test_env_backend_set_and_list():
    env_store = CredentialStore(backend=EnvBackend(env={}))

    env_store.set_key("llm", "api_key", "sk-env-value")

    assert env_store.get_key("llm", "api_key") == "sk-env-value"
    assert "api_key" in env_store.list_keys("llm")
