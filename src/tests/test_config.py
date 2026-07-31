import pytest

from harness.config import ConfigError, load_config


def test_load_default_config(work_dir):
    cfg = load_config(str(work_dir / "missing.yaml"))

    assert cfg.llm.mock is False
    assert cfg.llm.timeout == 120
    assert cfg.sandbox.enabled is True
    assert cfg.hitl.enabled is True
    assert cfg.logging.level == "INFO"
    assert cfg.open_design.enabled is False
    assert cfg.credential.service == "harness"


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
        "llm:\n  mock: false\n  model: gpt-4o\nlogging:\n  level: INFO\n",
        encoding="utf-8",
    )

    cfg = load_config(
        str(cfg_file),
        env={
            "HARNESS_LLM_MOCK": "true",
            "HARNESS_LOGGING_LEVEL": "ERROR",
            "HARNESS_API_KEY": "sk-test",
        },
    )

    assert cfg.llm.mock is True
    assert cfg.logging.level == "ERROR"

    overridden = cfg.apply_overrides({"llm": {"mock": False}})
    assert overridden.llm.mock is False
    assert overridden.logging.level == "ERROR"


def test_config_validation(work_dir):
    invalid_configs = [
        "llm:\n  mock: yes-please\n",
        "llm:\n  bogus_field: 1\n",
        "logging:\n  level: VERBOSE\n",
        "unknown_section:\n  a: 1\n",
        "llm:\n  timeout: abc\n",
        "llm:\n  mock: [unclosed\n",
        "sandbox:\n  network: public\n",
    ]
    for content in invalid_configs:
        cfg_file = work_dir / "config.yaml"
        cfg_file.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(str(cfg_file))
