"""Command-line entry point. Thin: parse args, call core, render."""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from flaky_anything import __version__
from flaky_anything import hunt as hunt_mod
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.knobs.registry import DEFAULT as DEFAULT_KNOBS
from flaky_anything.selection import default_python, find_root

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


def _more(items: Sequence[object]) -> str:
    return f" +{len(items) - 1}" if len(items) > 1 else ""


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%" if x >= 0.1 else f"{100 * x:.1f}%"


def render_hunt(report: hunt_mod.HuntReport, console: Console) -> None:
    findings = [*report.flaky, *report.broken]
    if not findings:
        console.print(f"No flaky tests found in {report.trials} trials.")
    else:
        table = Table(title="Flaky tests", title_justify="left")
        columns = ("test", "verdict", "failed", "fail rate (95% CI)", "signature", "failing config")
        for col in columns:
            table.add_column(col)
        for f in findings:
            top = f.signatures[0] if f.signatures else None
            table.add_row(
                f.nodeid,
                f.verdict,
                f"{f.failed}/{f.passed + f.failed}",
                f"{_pct(f.failure_rate)} ({_pct(f.rate_low)}-{_pct(f.rate_high)})",
                f"{top.exc_type} {top.id[:8]}{_more(f.signatures)}" if top else "-",
                f.failing_config_ids[0] + _more(f.failing_config_ids),
            )
        console.print(table)
        console.print("Rates are over the sampled configs the hunt ran, not a CI failure rate.")
    console.print(
        f"{report.trials} trials, {report.tests_selected} tests, seed {report.seed}, "
        f"knobs {','.join(report.knobs)}."
    )
    if report.budget_spent:
        console.print("[yellow]Budget spent:[/] tests not listed may still be flaky.")
    if report.flaky:
        console.print(f"Next: flaky-anything diagnose {report.flaky[0].nodeid}")


@app.command("hunt")
def hunt_cmd(
    paths: Annotated[list[str] | None, typer.Argument(help="Dirs, files or node ids.")] = None,
    from_junit: Annotated[
        list[Path] | None, typer.Option("--from-junit", help="CI JUnit XML reports.")
    ] = None,
    knobs: Annotated[str, typer.Option(help="Knobs to perturb.")] = DEFAULT_KNOBS,
    budget: Annotated[str, typer.Option(help="Wall-clock budget, e.g. 90s, 10m.")] = "10m",
    max_trials: Annotated[int | None, typer.Option(help="Stop after N trials.")] = None,
    seed: Annotated[int, typer.Option(help="Seed; same seed, same hunt.")] = 0,
    jobs: Annotated[int, typer.Option(help="Trials to run in parallel.")] = 1,
    python: Annotated[
        str | None, typer.Option(help="Interpreter of the project (default: its .venv).")
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Find flaky tests by running them under perturbed order, seeds, clock and time zone."""
    root, rel = find_root(paths or [])
    with Console(stderr=True).status(f"hunting in {root} ..."):
        report = hunt_mod.hunt(
            root,
            rel,
            junit=from_junit or [],
            knobs=knobs,
            seed=seed,
            budget=hunt_mod.Budget(max_trials, hunt_mod.parse_duration(budget)),
            jobs=jobs,
            python=python or default_python(root),
        )
    if json_out:
        typer.echo(report.model_dump_json(indent=2))
    else:
        render_hunt(report, Console())


for _name in ("diagnose", "repro", "fix", "verify", "report"):
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
