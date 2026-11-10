from __future__ import annotations

import re
import shlex
from typing import Any

import typer
from rich.table import Table

from novps.client import get_client
from novps.commands.apps import _load_app_envs, _store_app_envs
from novps.commands.resources import _confirm_delete, _parse_env_pair
from novps.output import console, output, print_json

app = typer.Typer(no_args_is_help=True)

# Every command takes a TARGET: an application ID (its environment variables) or the name of a custom secret
# (variables that belong to no app, created in the dashboard or with `secrets set`). Names never look like a UUID.
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

TARGET_HELP = "Application ID, or the name of a custom secret."
FORMATS = ("table", "json", "env", "export", "value")

SECRET_COLUMNS = [
    ("id", "ID"),
    ("key", "Key"),
]


def _is_app(target: str) -> bool:
    return bool(_UUID.match(target))


def _print_entries(entries: list[dict[str, Any]], fmt: str, title: str, with_values: bool = True) -> None:
    """Print [{key, value}] in the chosen format."""
    if fmt == "json":
        print_json(entries)
    elif fmt == "env":
        for e in entries:
            typer.echo(f"{e.get('key')}={e.get('value', '')}")
    elif fmt == "export":
        for e in entries:
            typer.echo(f"export {e.get('key')}={shlex.quote(str(e.get('value', '')))}")
    elif fmt == "value":
        if len(entries) != 1:
            typer.echo("Error: --format value needs a single KEY.", err=True)
            raise typer.Exit(code=1)
        typer.echo(entries[0].get("value", ""))
    else:
        table = Table(title=title)
        table.add_column("Key")
        if with_values:
            table.add_column("Value")
        for e in entries:
            row = [e.get("key", "")]
            if with_values:
                row.append(str(e.get("value", "")))
            table.add_row(*row)
        console.print(table)


def _check_format(fmt: str, as_json: bool) -> str:
    if as_json:
        return "json"
    if fmt not in FORMATS:
        raise typer.BadParameter(f"--format must be one of: {', '.join(FORMATS)}")
    return fmt


@app.command("list")
def list_secrets(
    target: str | None = typer.Argument(None, help=f"{TARGET_HELP} Omit to list the custom secrets of the project."),
    resource_id: str | None = typer.Option(None, "--resource", "-r", help="Resource ID (for resource-level secrets)."),
    with_values: bool = typer.Option(False, "--with-values", help="Include secret values in the output."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
    project: str = typer.Option("default", "--project", "-p", help="Project alias."),
) -> None:
    """List secret keys of an application, a resource or a custom secret (no TARGET: all custom secrets)."""
    client = get_client(project)
    include_values = "true" if with_values else "false"

    if target is None:
        data = client.get("/secrets").get("data", [])
        rows = [{**s, "keys": ", ".join(s.get("keys") or [])} for s in data]
        output(rows, [("name", "Name"), ("description", "Description"), ("keys", "Keys"), ("updated_at", "Updated")],
               title="Custom secrets", as_json=json)
        if not data and not json:
            typer.echo("No custom secrets. Create one with: novps secrets set <name> KEY=VALUE")
        return

    if not _is_app(target):
        data = client.get(f"/secrets/{target}", params={"include_values": include_values}).get("data", {})
        if json:
            print_json(data)
            return
        _print_entries(data.get("secrets") or [], "table", f"Custom secret: {target}", with_values=with_values)
        return

    app_id = target
    if resource_id:
        resp = client.get(f"/apps/{app_id}/resources/{resource_id}/secrets?include_values={include_values}")
        data = resp.get("data", [])
        columns = SECRET_COLUMNS + ([("value", "Value")] if with_values else [])
        output(data, columns, title=f"Secrets (resource: {resource_id})", as_json=json)
    else:
        resp = client.get(f"/apps/{app_id}/secrets?include_values={include_values}")
        data = resp.get("data", {})

        if json:
            print_json(data)
            return

        global_secrets = data.get("global", [])
        if global_secrets:
            _print_entries(global_secrets, "table", "Global Secrets", with_values=with_values)

        resource_secrets = data.get("resources", {})
        for rid, secrets_list in resource_secrets.items():
            if secrets_list:
                _print_entries(secrets_list, "table", f"Resource: {rid}", with_values=with_values)

        if not global_secrets and not any(resource_secrets.values()):
            typer.echo("No secrets found.")


@app.command("get")
def get_secret(
    target: str = typer.Argument(help=TARGET_HELP),
    secret_key: str | None = typer.Argument(None, help="Secret key name (e.g. DATABASE_URL). Required for an application."),
    fmt: str = typer.Option("table", "--format", "-f", help="table, json, env (KEY=VALUE), export (for eval) or value (one KEY, the bare value)."),
    json: bool = typer.Option(False, "--json", help="Output as JSON (same as --format json)."),
    project: str = typer.Option("default", "--project", "-p", help="Project alias."),
) -> None:
    """Get secret values: one key of an application, or a custom secret (all keys, or one)."""
    fmt = _check_format(fmt, json)
    client = get_client(project)

    if _is_app(target):
        if not secret_key:
            typer.echo("Error: KEY is required for an application (list keys with: novps secrets list <app_id>).", err=True)
            raise typer.Exit(code=1)
        data = client.get(f"/apps/{target}/secrets/{secret_key}").get("data", {})
        if fmt == "json":
            print_json(data)
            return
        if fmt == "table":
            table = Table(title="Secret")
            table.add_column("Key")
            table.add_column("Value")
            table.add_column("Resource ID")
            table.add_row(data.get("key", ""), data.get("value", ""), data.get("resource_id") or "global")
            console.print(table)
            return
        _print_entries([data], fmt, "Secret")
        return

    if secret_key:
        data = client.get(f"/secrets/{target}/{secret_key}").get("data", {})
        _print_entries([data], fmt, f"Custom secret: {target}")
        return
    data = client.get(f"/secrets/{target}", params={"include_values": "true"}).get("data", {})
    _print_entries(data.get("secrets") or [], fmt, f"Custom secret: {target}")


@app.command("set")
def set_secret(
    target: str = typer.Argument(help=f"{TARGET_HELP} A custom secret that does not exist yet is created."),
    pairs: list[str] = typer.Argument(..., help="KEY=VALUE pairs (repeatable)."),
    description: str | None = typer.Option(None, "--description", help="Description of a custom secret."),
    no_deploy: bool = typer.Option(False, "--no-deploy", help="Application only: do not trigger a deployment."),
    project: str = typer.Option("default", "--project", "-p", help="Project alias."),
) -> None:
    """Set variables of an application (app-wide, shared by its resources) or of a custom secret; others are kept."""
    new_pairs = [_parse_env_pair(p) for p in pairs]
    client = get_client(project)

    if _is_app(target):
        new_keys = {k for k, _ in new_pairs}
        envs = [e for e in _load_app_envs(client, target) if e["key"] not in new_keys]
        envs += [{"key": k, "value": v} for k, v in new_pairs]
        _store_app_envs(client, target, envs, no_deploy=no_deploy)
        typer.echo(f"Application {target}: envs updated ({len(new_pairs)} changed).")
        return

    exists = any(s.get("name") == target for s in client.get("/secrets").get("data", []))
    values = {k: v for k, v in new_pairs}
    if exists:
        payload: dict[str, Any] = {"set": values}
        if description is not None:
            payload["description"] = description
        client.patch(f"/secrets/{target}", data=payload)
        typer.echo(f"Custom secret {target}: {len(values)} set.")
    else:
        client.post("/secrets", data={
            "name": target,
            "description": description or "",
            "secrets": [{"key": k, "value": v} for k, v in values.items()],
        })
        typer.echo(f"Custom secret {target} created with {len(values)} variables.")


@app.command("unset")
def unset_secret(
    target: str = typer.Argument(help=TARGET_HELP),
    keys: list[str] = typer.Argument(..., help="Keys to remove."),
    no_deploy: bool = typer.Option(False, "--no-deploy", help="Application only: do not trigger a deployment."),
    project: str = typer.Option("default", "--project", "-p", help="Project alias."),
) -> None:
    """Remove variables of an application (app-wide) or of a custom secret."""
    client = get_client(project)

    if _is_app(target):
        current = _load_app_envs(client, target)
        envs = [e for e in current if e["key"] not in keys]
        removed = len(current) - len(envs)
        if not removed:
            typer.echo(f"Application {target}: none of these keys are set.", err=True)
            raise typer.Exit(code=1)
        _store_app_envs(client, target, envs, no_deploy=no_deploy)
        typer.echo(f"Application {target}: envs updated ({removed} removed).")
        return

    current = client.get(f"/secrets/{target}").get("data", {}).get("secrets") or []
    removed = [k for k in keys if any(e.get("key") == k for e in current)]
    if not removed:
        typer.echo(f"Custom secret {target}: none of these keys are set.", err=True)
        raise typer.Exit(code=1)
    client.patch(f"/secrets/{target}", data={"unset": removed})
    typer.echo(f"Custom secret {target}: {len(removed)} removed.")


@app.command("delete")
def delete_secret(
    target: str = typer.Argument(help="Name of a custom secret."),
    force: bool = typer.Option(False, "--force", help="Skip the confirmation."),
    project: str = typer.Option("default", "--project", "-p", help="Project alias."),
) -> None:
    """Delete a custom secret (application variables go away with the application)."""
    if _is_app(target):
        typer.echo("Error: only custom secrets can be deleted; remove app variables with: novps secrets unset <app_id> KEY", err=True)
        raise typer.Exit(code=1)
    _confirm_delete(f"This will delete the custom secret {target}.", force=force)
    get_client(project).delete(f"/secrets/{target}")
    typer.echo(f"Custom secret {target} deleted.")
