"""Formatting of application events (`novps apps events`).

Event objects are the envelopes platform webhooks deliver:
{id, type, severity, occurred_at, project, app, resource, incident, data}
plus `incident_ongoing` in the event log. Labels mirror the dashboard
(web-app components/admin/[slug]/webhooks/events.ts).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

EVENT_LABELS: dict[str, str] = {
    "resource.healthcheck.failing": "Healthcheck failing",
    "resource.healthcheck.recovered": "Healthcheck recovered",
    "resource.down": "Down",
    "resource.degraded": "Degraded",
    "resource.up": "Up",
    "resource.restarted": "Restarted",
    "resource.oom_killed": "Out of memory",
    "resource.crash_loop": "Crash loop",
    "resource.crash_loop.recovered": "Crash loop resolved",
    "resource.image_pull_failed": "Image pull failed",
    "resource.image_pull_failed.recovered": "Image pull recovered",
    "resource.config_error": "Configuration error",
    "resource.config_error.recovered": "Configuration error resolved",
    "cronjob.run.failed": "Cron run failed",
    "cronjob.run.succeeded": "Cron run succeeded",
    "cronjob.run.long_running": "Cron run too long",
    "deployment.started": "Deployment started",
    "deployment.succeeded": "Deployment succeeded",
    "deployment.failed": "Deployment failed",
    "deployment.canceled": "Deployment canceled",
    "build.failed": "Build failed",
}

_RESTART_REASONS = {
    "liveness_failed": "Liveness probe failed",
    "error": "Container exited with an error",
    "completed": "Container exited",
    "unknown": "Container restarted",
}


def label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type)


def _is_recovery(event_type: str) -> bool:
    return event_type.endswith(".recovered") or event_type in {
        "resource.up",
        "deployment.succeeded",
        "cronjob.run.succeeded",
    }


def color(event: dict[str, Any]) -> str:
    """Rich colour for the event label."""
    event_type = event.get("type", "")
    if _is_recovery(event_type):
        return "green"
    severity = event.get("severity")
    if severity == "critical":
        return "red"
    if severity == "warning":
        return "yellow"
    return "white"


def format_seconds(seconds: float | int | None) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def summary(event: dict[str, Any]) -> str:
    """One-line description of an event."""
    d = event.get("data") or {}
    event_type = event.get("type", "")

    def s(key: str) -> str:
        value = d.get(key)
        return value if isinstance(value, str) else ""

    termination = d.get("termination") if isinstance(d.get("termination"), dict) else {}
    exit_code = termination.get("exit_code")
    exit_suffix = f" (exit code {exit_code})" if isinstance(exit_code, int) else ""
    duration = d.get("duration_seconds")

    if event_type in {
        "resource.healthcheck.failing",
        "resource.crash_loop",
        "resource.image_pull_failed",
        "resource.config_error",
    }:
        return s("message") or s("reason") or label(event_type)
    if event_type == "resource.down":
        return f"No replicas ready (0 of {d.get('desired', '?')})"
    if event_type == "resource.degraded":
        return f"{d.get('ready', '?')} of {d.get('desired', '?')} replicas ready"
    if event_type == "resource.restarted":
        count = d.get("restarts_in_window")
        extra = f" · {count} restarts" if isinstance(count, int) and count > 1 else ""
        return f"{_RESTART_REASONS.get(s('reason'), 'Restarted')}{exit_suffix}{extra}"
    if event_type == "resource.oom_killed":
        limit = s("memory_limit")
        return "Killed for exceeding the memory limit" + (f" of {limit}" if limit else "")
    if event_type == "cronjob.run.failed":
        return f"{s('job')}: {s('message') or s('reason')}{exit_suffix}"
    if event_type == "cronjob.run.succeeded":
        took = f" in {format_seconds(duration)}" if duration is not None else ""
        return f"{s('job')} finished{took}"
    if event_type == "cronjob.run.long_running":
        return f"{s('job')} has been running for {format_seconds(d.get('running_seconds'))}"
    if event_type == "deployment.failed":
        return s("fail_reason") or "Deployment failed"
    if event_type in {"deployment.started", "deployment.succeeded", "deployment.canceled"}:
        return s("trigger_reason") or label(event_type)
    if event_type == "build.failed":
        return f"The {s('step') or 'build'} step failed"
    if _is_recovery(event_type):
        return f"Recovered after {format_seconds(duration)}" if duration is not None else "Recovered"
    return ""


_FRACTION = re.compile(r"\.(\d+)")


def parse_time(value: str) -> datetime:
    """Parse an RFC 3339 timestamp into an aware datetime.

    Go emits up to 9 fractional digits; Python accepts at most 6.
    """
    value = _FRACTION.sub(lambda m: "." + m.group(1)[:6], value.replace("Z", "+00:00"), count=1)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resource_name(event: dict[str, Any]) -> str:
    return (event.get("resource") or {}).get("name") or "(app)"


def format_line(event: dict[str, Any], resource_width: int = 0) -> str:
    """Rich-markup line: time, label, resource, summary (+ ongoing marker)."""
    from rich.markup import escape

    ts = parse_time(event["occurred_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{label(event.get('type', '')):<22}"
    resource = f"{resource_name(event):<{resource_width}}"
    ongoing = " [dim](ongoing)[/dim]" if event.get("incident_ongoing") else ""
    return (
        f"[dim]{ts}[/dim]  [{color(event)}]{escape(text)}[/{color(event)}]  "
        f"[bold]{escape(resource)}[/bold]  {escape(summary(event))}{ongoing}"
    )
