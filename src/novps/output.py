from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def print_table(
    data: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    title: str | None = None,
    *,
    formatters: dict[str, Callable[[Any], str]] | None = None,
) -> None:
    """Print data as a Rich table.

    columns: list of (key, header) tuples.
    formatters: optional per-key value formatters (may return Rich markup).
    """
    formatters = formatters or {}
    table = Table(title=title)
    for _, header in columns:
        table.add_column(header)
    for row in data:
        cells = []
        for key, _ in columns:
            value = row.get(key, "")
            fmt = formatters.get(key)
            cells.append(fmt(value) if fmt else str(value))
        table.add_row(*cells)
    console.print(table)


def print_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2))


def output(
    data: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    title: str | None = None,
    *,
    as_json: bool = False,
    formatters: dict[str, Callable[[Any], str]] | None = None,
) -> None:
    if as_json:
        print_json(data)
    else:
        print_table(data, columns, title, formatters=formatters)
