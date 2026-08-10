"""stoa-engine CLI (Typer).

    stoa-engine export   --input <json> --template posture|performance|all --out <dir>
    stoa-engine gaps     --input <json> --template posture|performance|all
    stoa-engine validate --input <json>
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import adapters, pipeline

app = typer.Typer(add_completion=False, help="Stoa Risk Underwriting Engine")
console = Console()

TEMPLATE_CHOICES = "posture | performance | all"


def _check_template(template: str) -> None:
    avail = set(adapters.available_templates()) | {"all"}
    if template not in avail:
        console.print(f"[red]Unknown template '{template}'.[/red] Available: {sorted(avail)}")
        raise typer.Exit(code=2)


@app.command()
def export(
    input: Path = typer.Option(..., "--input", "-i", exists=True, readable=True, help="Submission JSON"),
    template: str = typer.Option("all", "--template", "-t", help=TEMPLATE_CHOICES),
    out: Path = typer.Option(..., "--out", "-o", help="Output packet directory"),
) -> None:
    """Render an underwriting packet (PDF(s), XLSX, evidence manifest)."""
    _check_template(template)
    result = pipeline.export(str(input), template, str(out))
    if result["sample_data"]:
        console.print("[bold red]SAMPLE — FICTIONAL DATA — NOT FOR SUBMISSION[/bold red]")
    console.print(f"[green]Packet written to[/green] {result['out_dir']}")
    for f in result["files"]:
        console.print(f"  · {f}")
    _print_gaps(result["gaps"])


@app.command()
def gaps(
    input: Path = typer.Option(..., "--input", "-i", exists=True, readable=True),
    template: str = typer.Option("all", "--template", "-t", help=TEMPLATE_CHOICES),
) -> None:
    """Print the gap report (declared + adapter completeness) to the console."""
    _check_template(template)
    submission = pipeline.load_json(str(input))
    templates = pipeline._templates_for(template)
    collected = []
    for tpl in templates:
        collected.extend(g.model_dump() for g in pipeline.collect_gaps(submission, tpl))
    _print_gaps(collected)


@app.command()
def validate(
    input: Path = typer.Option(..., "--input", "-i", exists=True, readable=True),
) -> None:
    """Validate a submission against the Pydantic schema."""
    try:
        sub = pipeline.validate(str(input))
    except Exception as exc:  # noqa: BLE001 — surface any validation error to the user
        console.print(f"[red]Invalid submission:[/red] {exc}")
        raise typer.Exit(code=1)
    console.print(
        f"[green]Valid.[/green] {len(sub.systems)} system(s): "
        + ", ".join(s.agent_id for s in sub.systems)
    )


def _print_gaps(gaps: list[dict]) -> None:
    if not gaps:
        console.print("[green]No gaps — every required field resolved.[/green]")
        return
    table = Table(title="Gap report", show_lines=False)
    table.add_column("Template", style="cyan")
    table.add_column("Field", style="white")
    table.add_column("Owner", style="magenta")
    table.add_column("Description")
    for g in gaps:
        table.add_row(g["template"], g["field_id"], g["owner"], g["description"])
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
