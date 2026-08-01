import json

from click.testing import CliRunner

from harness.credential_store import CredentialStore, MemoryBackend
from harness.main import cli
from harness.mock_llm import MockLLM

DONE = json.dumps({"done": True})


def test_cli_run(tmp_path, monkeypatch):
    task = tmp_path / "task.yaml"
    task.write_text("id: t1\nprompt: write hello\nmax_iterations: 3\n", encoding="utf-8")
    config = tmp_path / "harness.yaml"
    config.write_text("llm:\n  mock: true\n", encoding="utf-8")

    monkeypatch.setattr("harness.main.build_llm", lambda cfg: MockLLM([DONE]))
    result = CliRunner().invoke(cli, ["run", str(task), "--config", str(config)])

    assert result.exit_code == 0
    assert "COMPLETED" in result.output


def test_cli_config_show(tmp_path):
    config = tmp_path / "harness.yaml"
    config.write_text(
        "llm:\n  model: gpt-4o-9999\n  credential_ref: harness/openai\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["config", "show", "--config", str(config)])

    assert result.exit_code == 0
    assert "gpt-4o-9999" in result.output
    assert "harness/openai" not in result.output


def test_cli_cred_set(monkeypatch):
    store = CredentialStore(backend=MemoryBackend())
    prompts = []

    def fake_getpass(prompt):
        prompts.append(prompt)
        return "sk-super-secret"

    monkeypatch.setattr("harness.credential_store.CredentialStore", lambda: store)
    monkeypatch.setattr("getpass.getpass", fake_getpass)
    result = CliRunner().invoke(cli, ["cred", "set", "svc", "api_key"])

    assert result.exit_code == 0
    assert store.get_key("svc", "api_key") == "sk-super-secret"
    assert prompts == ["Enter value for 'api_key': "]


def test_cli_missing_file():
    result = CliRunner().invoke(cli, ["run", "no-such-task.yaml"])

    assert result.exit_code != 0
