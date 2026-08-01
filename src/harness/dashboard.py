import click
import uvicorn

from harness.api import create_app
from harness.config import HarnessConfig


def run_dashboard(config: HarnessConfig) -> None:
    host = config.webui.host
    port = config.webui.port
    app = create_app()
    click.echo(f"AI Agent Harness Dashboard: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
