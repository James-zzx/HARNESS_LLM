import json

from click.testing import CliRunner

from harness.credential_store import CredentialStore, MemoryBackend
from harness.main import cli
from harness.mock_llm import MockLLM
from harness.orchestrator import RunResult

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


def test_cli_run_rejects_nonpositive_timeout(tmp_path):
    task = tmp_path / "task.yaml"
    task.write_text("id: t1\nprompt: write hello\n", encoding="utf-8")
    config = tmp_path / "harness.yaml"
    config.write_text("llm:\n  mock: true\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["run", str(task), "--config", str(config), "--timeout", "0"]
    )

    assert result.exit_code != 0
    assert "timeout" in result.output.lower()
    assert "Traceback" not in result.output


def test_cli_webui_disabled_prints_message(tmp_path):
    config = tmp_path / "harness.yaml"
    config.write_text("open_design:\n  enabled: false\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["webui", "--config", str(config)])

    assert result.exit_code == 0
    assert "disabled" in result.output.lower()


def test_cli_webui_enabled_starts_daemon(tmp_path, monkeypatch):
    config = tmp_path / "harness.yaml"
    config.write_text("open_design:\n  enabled: true\n  port: 7456\n", encoding="utf-8")

    class _FakeODClient:
        base_url = "http://127.0.0.1:7456"

        def start_daemon(self):
            calls.append("start")

        def stop_daemon(self):
            calls.append("stop")

        def health_check(self):
            return True

    calls = []
    monkeypatch.setattr("harness.main.OpenDesignClient", lambda config: _FakeODClient())
    monkeypatch.setattr(
        "harness.main.time.sleep",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    result = CliRunner().invoke(cli, ["webui", "--config", str(config)])

    assert result.exit_code == 0
    assert "http://127.0.0.1:7456" in result.output
    assert calls == ["start", "stop"]


def test_cli_run_prints_rejection_feedback(tmp_path, monkeypatch):
    task = tmp_path / "task.yaml"
    task.write_text("id: t1\nprompt: dangerous\n", encoding="utf-8")
    config = tmp_path / "harness.yaml"
    config.write_text("llm:\n  mock: true\n", encoding="utf-8")

    class _FakeOrchestrator:
        def run(self, task):
            return RunResult(
                status="PAUSED",
                final_state="PAUSED",
                iterations=0,
                feedback='{"error": "action rejected by human-in-the-loop"}',
            )

    class _FakeRuntime:
        def build_orchestrator(self, llm, **kwargs):
            return _FakeOrchestrator()

    monkeypatch.setattr("harness.main.build_runtime", lambda config: _FakeRuntime())
    monkeypatch.setattr("harness.main.build_llm", lambda config: None)

    result = CliRunner().invoke(cli, ["run", str(task), "--config", str(config)])

    assert result.exit_code == 1
    assert "action rejected by human-in-the-loop" in result.output
