"""Command-line entry point. Thin: parse args, call core, render."""

import sys

import typer
from rich.console import Console

from flaky_anything import __version__
from flaky_anything.errors import FlakyAnythingError

app = typer.Typer(help="Find flaky tests, explain why they fail, and prove the fix.")


@app.callback()
def main() -> None:
    """flaky-anything."""


@app.command("version")
def version_cmd() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def _stub(name: str) -> None:
    def cmd() -> None:
        typer.echo(f"{name}: not implemented", err=True)
        raise typer.Exit(2)

    # ponytail: generated stubs; each gets a real function with its own args when implemented
    app.command(name, help=f"{name.capitalize()} (not implemented yet).")(cmd)


for _name in ("hunt", "diagnose", "repro", "fix", "verify", "report"):
    _stub(_name)


def run() -> None:
    """Console-script entry point: run the app, render expected errors without a traceback."""
    try:
        app()
    except FlakyAnythingError as e:
        err = Console(stderr=True)
        err.print(f"[bold red]error:[/] {e.message}", highlight=False)
        if e.hint:
            err.print(f"[yellow]hint:[/] {e.hint}", highlight=False)
        sys.exit(1)
