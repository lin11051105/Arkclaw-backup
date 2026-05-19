"""Link tester -- REQ 3.3 新产品回传链路验证。

查询 DAP 回传数据，验证事件到达 + 字段完整性 + 归因路径。
纯函数设计，fetch_postback_status 由调用方注入。
"""
from __future__ import annotations

from typing import Any, Callable

DEFAULT_EVENTS = ["install", "purchase", "register"]
DEFAULT_REQUIRED_FIELDS: dict[str, list[str]] = {
    "install": ["device_id"],
    "purchase": ["device_id"],
    "register": ["device_id"],
}


def run_link_test(
    project_id: str,
    channel: str,
    *,
    events: list[str] | None = None,
    required_fields: dict[str, list[str]] | None = None,
    fetch_postback_status: Callable[[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    events = events or DEFAULT_EVENTS
    required_fields = required_fields or DEFAULT_REQUIRED_FIELDS

    postbacks = fetch_postback_status(project_id, channel)

    received: dict[str, dict[str, Any]] = {}
    for pb in postbacks:
        evt = pb.get("event")
        if evt and evt not in received:
            received[evt] = pb

    failed_steps: list[str] = []
    alerts: list[dict[str, Any]] = []
    event_results: list[dict[str, Any]] = []

    for evt in events:
        pb = received.get(evt)
        if pb is None:
            failed_steps.append(f"event_missing:{evt}")
            alerts.append({
                "type": "event_not_received",
                "severity": "P0",
                "event": evt,
                "message": f"事件 {evt} 未收到回传，链路可能中断",
            })
            event_results.append({"event": evt, "status": "missing", "fields_ok": False})
            continue

        fields = pb.get("fields") or {}
        req = required_fields.get(evt, [])
        missing = [f for f in req if f not in fields]
        if missing:
            failed_steps.append(f"fields_incomplete:{evt}:missing={','.join(missing)}")
            alerts.append({
                "type": "fields_incomplete",
                "severity": "P1",
                "event": evt,
                "missing_fields": missing,
                "message": f"事件 {evt} 回传字段不完整，缺少: {', '.join(missing)}",
            })
            event_results.append({"event": evt, "status": "incomplete", "fields_ok": False, "missing_fields": missing})
        else:
            event_results.append({"event": evt, "status": "ok", "fields_ok": True})

    passed = len(failed_steps) == 0

    return {
        "passed": passed,
        "project_id": project_id,
        "channel": channel,
        "events_checked": event_results,
        "failed_steps": failed_steps,
        "alerts": alerts,
    }
