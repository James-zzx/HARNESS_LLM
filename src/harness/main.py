from dataclasses import asdict
from pathlib import Path
import sys

import click
import time
import yaml

from harness.cli import build_llm, config_to_yaml, to_orchestrator_task
from harness.config import ConfigError, HarnessConfig, load_config
from harness.credential_store import build_cred_cli
from harness.logger import setup_logging
from harness.open_design import ODDaemonError, ODNotFoundError, OpenDesignClient
from harness.runtime import build_runtime
from harness.task import TaskError, TaskParser


def _error(message: str) -> None:
    click.echo(f"error: {message}", err=True)
    raise click.exceptions.Exit(1)


@click.group(name="harness")
def cli() -> None:
    """AI Agent Harness - safely run coding agents with sandbox, governance, and audit."""


@cli.command("run")
@click.argument("task_path")
@click.option("--config", "config_path", default=None, help="Path to a harness config file.")
@click.option("--verbose", is_flag=True, default=False, help="Enable DEBUG logging.")
@click.option("--timeout", type=float, default=None, help="Override the task timeout (seconds).")
def run_command(task_path: str, config_path, verbose: bool, timeout) -> None:
    """Run a task definition (YAML) through the harness."""
    try:
        task = TaskParser.load(task_path)
    except TaskError as exc:
        _error(f"failed to load task: {exc}")
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        _error(f"failed to load config: {exc}")
    if timeout is not None:
        if timeout <= 0:
            _error(f"--timeout must be a positive number of seconds, got {timeout}")
        task.timeout = timeout
    setup_logging(
        level="DEBUG" if verbose else config.logging.level,
        format=config.logging.format,
        file_path=config.logging.file_path,
    )
    result = (
        build_runtime(
            config,
            hitl_input_stream=sys.stdin,
            hitl_output_stream=sys.stdout,
        )
        .build_orchestrator(llm=build_llm(config))
        .run(to_orchestrator_task(task))
    )
    click.echo(f"status={result.status} iterations={result.iterations} state={result.final_state}")
    if result.feedback:
        click.echo(result.feedback)
    if result.error:
        click.echo(f"error={result.error}", err=True)
    if result.status != "COMPLETED":
        raise click.exceptions.Exit(1)


def start_open_design_daemon(client: OpenDesignClient) -> str:
    """Start the Open Design daemon, verify it is healthy, and return its URL."""
    client.start_daemon()
    if not client.health_check():
        raise ODDaemonError("Open Design daemon failed its health check")
    return client.base_url


def stop_open_design_daemon(client: OpenDesignClient) -> None:
    client.stop_daemon()


def _wait_until_interrupt() -> None:
    while True:
        time.sleep(3600)


@cli.command("webui")
@click.option("--config", "config_path", default=None, help="Path to a harness config file.")
def webui_command(config_path) -> None:
    """Start the Open Design daemon and print its web UI URL."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        _error(f"failed to load config: {exc}")
    if not config.open_design.enabled:
        click.echo(
            "Open Design web UI is disabled: set open_design.enabled: true in "
            "your harness config to enable it."
        )
        return
    client = OpenDesignClient(config=config.open_design)
    try:
        url = start_open_design_daemon(client)
    except (ODNotFoundError, ODDaemonError) as exc:
        _error(str(exc))
    click.echo(f"Open Design web UI available at: {url}")
    click.echo("Press Ctrl+C to stop the daemon.")
    try:
        _wait_until_interrupt()
    except KeyboardInterrupt:
        pass
    finally:
        stop_open_design_daemon(client)
    click.echo("Open Design daemon stopped.")


@click.group("config")
def config_group() -> None:
    """Inspect the effective harness configuration."""


@config_group.command("show")
@click.option("--config", "config_path", default=None, help="Path to a harness config file.")
def config_show(config_path) -> None:
    """Print the effective configuration (defaults + file + env), redacting secrets."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        _error(f"failed to load config: {exc}")
    click.echo(config_to_yaml(config).rstrip())


@cli.command("init")
def init_command() -> None:
    """Create a default harness.yaml in the current directory."""
    path = Path("harness.yaml")
    if path.exists():
        _error(f"{path} already exists")
    header = (
        "# AI Agent Harness - default configuration\n"
        "#\n"
        "# API key configuration (choose one):\n"
        "#\n"
        "# 1) OS keyring (recommended for local use):\n"
        "#      python -m harness cred set harness openai\n"
        "#    then set:\n"
        "#      llm:\n"
        "#        credential_ref: harness/openai\n"
        "#      credential:\n"
        "#        backend: keyring\n"
        "#\n"
        "# 2) Environment / .env file (recommended for containers):\n"
        "#    set HARNESS_HARNESS_OPENAI=<your key> in .env or the environment,\n"
        "#    then set:\n"
        "#      llm:\n"
        "#        credential_ref: harness/openai\n"
        "#      credential:\n"
        "#        backend: env\n"
        "#\n"
        "# In mock mode (llm.mock: true) no key is needed - the harness runs\n"
        "# offline with a deterministic MockLLM.\n"
    )
    body = yaml.safe_dump(
        asdict(HarnessConfig()), sort_keys=False, default_flow_style=False
    )
    path.write_text(header + body, encoding="utf-8")
    click.echo(f"created {path}")


cli.add_command(config_group)
cli.add_command(build_cred_cli())
