import os

import pytest

from harness.config import ConfigError, load_config


def test_load_default_config():
    cfg = load_config()

    assert cfg.llm.mock is True
    assert cfg.llm.timeout == 120
    assert cfg.sandbox.enabled is True
    assert cfg.hitl.enabled is True
    assert cfg.logging.level == "INFO"
    assert cfg.open_design.enabled is False
    assert cfg.credential.service == "harness"


def test_config_mock_default_true():
    cfg = load_config()

    assert cfg.llm.mock is True


def test_load_dotenv_applies_env_vars(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "HARNESS_LLM_MOCK=true\nHARNESS_LLM_MODEL=gpt-4o-mini\nHARNESS_LOGGING_LEVEL=DEBUG\n",
        encoding="utf-8",
    )
    for var in ("HARNESS_LLM_MOCK", "HARNESS_LLM_MODEL", "HARNESS_LOGGING_LEVEL"):
        monkeypatch.delenv(var, raising=False)

    cfg = load_config(dotenv_path=str(env_file))

    assert cfg.llm.mock is True
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.logging.level == "DEBUG"

    for var in ("HARNESS_LLM_MOCK", "HARNESS_LLM_MODEL", "HARNESS_LOGGING_LEVEL"):
        os.environ.pop(var, None)


def test_load_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("HARNESS_LLM_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("HARNESS_LLM_MODEL", "from-env")

    cfg = load_config(dotenv_path=str(env_file))

    assert cfg.llm.model == "from-env"


def test_load_yaml_config(work_dir):
    cfg_file = work_dir / "config.yaml"
    cfg_file.write_text(
        "llm:\n  mock: true\n  model: gpt-4o-mini\nlogging:\n  level: DEBUG\n",
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_file))

    assert cfg.llm.mock is True
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.logging.level == "DEBUG"
    assert cfg.logging.file_path is None
    assert cfg.sandbox.enabled is True

    json_file = work_dir / "config.json"
    json_file.write_text('{"llm": {"mock": true}}', encoding="utf-8")
    cfg = load_config(str(json_file))
    assert cfg.llm.mock is True


def test_config_merge(work_dir):
    cfg_file = work_dir / "config.yaml"
    cfg_file.write_text(
        "llm:\n  mock: false\n  model: gpt-4o-mini\n  timeout: 60\nlogging:\n  level: INFO\n",
        encoding="utf-8",
    )

    cfg = load_config(
        str(cfg_file),
        env={
            "HARNESS_LLM_MOCK": "true",
            "HARNESS_LLM_BASE_URL": "",
            "HARNESS_LLM_CREDENTIAL_REF": "harness/openai",
            "HARNESS_LOGGING_LEVEL": "ERROR",
            "HARNESS_API_KEY": "sk-test",
        },
    )

    assert cfg.llm.mock is True
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.llm.timeout == 60
    assert cfg.llm.base_url is None
    assert cfg.llm.credential_ref == "harness/openai"
    assert cfg.logging.level == "ERROR"

    overridden = cfg.apply_overrides({"llm": {"mock": False}})
    assert overridden.llm.mock is False
    assert overridden.llm.model == "gpt-4o-mini"
    assert overridden.llm.timeout == 60
    assert overridden.logging.level == "ERROR"


def test_load_config_explicit_missing_path_raises(work_dir):
    with pytest.raises(ConfigError, match="not found"):
        load_config(str(work_dir / "does-not-exist.yaml"))


def test_config_webui_section(work_dir):
    cfg = load_config()
    assert cfg.webui.host == "127.0.0.1"
    assert cfg.webui.port == 8000

    cfg_file = work_dir / "config.yaml"
    cfg_file.write_text("webui:\n  host: 0.0.0.0\n  port: 9000\n", encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg.webui.host == "0.0.0.0"
    assert cfg.webui.port == 9000


def test_config_validation(work_dir):
    invalid_configs = [
        "llm:\n  mock: yes-please\n",
        "llm:\n  bogus_field: 1\n",
        "logging:\n  level: VERBOSE\n",
        "unknown_section:\n  a: 1\n",
        "llm:\n  timeout: abc\n",
        "llm:\n  mock: [unclosed\n",
        "sandbox:\n  network: public\n",
        "webui:\n  port: abc\n",
    ]
    for content in invalid_configs:
        cfg_file = work_dir / "config.yaml"
        cfg_file.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(str(cfg_file))
