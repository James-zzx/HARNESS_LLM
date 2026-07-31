from dataclasses import asdict
from pathlib import Path

import click
import yaml

from harness.cli import build_llm, config_to_yaml, to_orchestrator_task
from harness.config import ConfigError, HarnessConfig, load_config
from harness.credential_store import build_cred_cli
from harness.logger import setup_logging
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
        task.timeout = timeout
    setup_logging(
        level="DEBUG" if verbose else config.logging.level,
        format=config.logging.format,
        file_path=config.logging.file_path,
    )
    result = build_runtime(config).build_orchestrator(llm=build_llm(config)).run(
        to_orchestrator_task(task)
    )
    click.echo(f"status={result.status} iterations={result.iterations} state={result.final_state}")
    if result.error:
        click.echo(f"error={result.error}", err=True)
    if result.status != "COMPLETED":
        raise click.exceptions.Exit(1)


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
    path.write_text(
        yaml.safe_dump(asdict(HarnessConfig()), sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    click.echo(f"created {path}")


cli.add_command(config_group)
cli.add_command(build_cred_cli())
