import click


@click.group(name="harness")
def cli() -> None:
    """AI Agent Harness - safely run coding agents with sandbox, governance, and audit."""


if __name__ == "__main__":
    cli()
