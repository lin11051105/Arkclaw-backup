"""Atlas AI Gateway HTTP client (统一 auth source).

Lilith 内部的 atlas-ai-gateway 是 MCP over JSON-RPC over HTTPS：

    POST {gateway_url}/mcp-servers/{service}
    Authorization: Bearer {access_token from ~/.atlas-ai-gateway-oauth.json}
    Body: {"jsonrpc":"2.0","id":N,"method":"tools/call",
           "params":{"name":"<tool>","arguments":{...}}}

Token 由 atlas-skillhub 的 OAuth 流颁发到 ``~/.atlas-ai-gateway-oauth.json``：
    {
      "access_token": "...",
      "token_type": "Bearer",
      "expires_in": 2591999,
      "expires_at": "2026-06-10T02:31:50Z",
      "gateway_url": "https://atlas-ai-gateway.lilithgames.com"
    }

恢复指引：token 过期 / 文件缺失时跑 ``atlas-skillhub gateway login``。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

_DEFAULT_OAUTH_PATH = Path.home() / ".atlas-ai-gateway-oauth.json"
_EXPIRY_BUFFER = timedelta(minutes=5)
_DEFAULT_TIMEOUT = 30.0
_RECOVER_HINT = "请跑 `atlas-skillhub gateway login` 重新授权。"

_rpc_id_lock = threading.Lock()
_rpc_id = 0


class AtlasGatewayError(Exception):
    """atlas-ai-gateway 返回了 JSON-RPC error 段或非 2xx 状态码（非 401）。"""


class AtlasOAuthFileMissingError(AtlasGatewayError):
    """~/.atlas-ai-gateway-oauth.json 文件不存在。"""


class AtlasTokenExpiredError(AtlasGatewayError):
    """access_token 已过期 / 即将过期 / 被服务端拒绝（401）。"""


def _next_id() -> int:
    global _rpc_id
    with _rpc_id_lock:
        _rpc_id += 1
        return _rpc_id


def _load_oauth(*, path: Path | None = None) -> dict[str, Any]:
    """读 OAuth 配置 + 过期检查。

    Args:
        path: 覆盖默认 ``~/.atlas-ai-gateway-oauth.json``，便于测试。

    Raises:
        AtlasOAuthFileMissingError: 文件不存在。
        AtlasTokenExpiredError: 已过期 / 5 分钟内即将过期。
    """
    p = Path(path) if path else _DEFAULT_OAUTH_PATH
    if not p.exists():
        raise AtlasOAuthFileMissingError(
            f"{p} 不存在。{_RECOVER_HINT}"
        )
    data = json.loads(p.read_text())
    exp_str = data.get("expires_at")
    if exp_str:
        exp = datetime.strptime(exp_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if exp <= now + _EXPIRY_BUFFER:
            raise AtlasTokenExpiredError(
                f"atlas-ai-gateway token 过期于 {exp_str}（当前 {now.isoformat()}）。{_RECOVER_HINT}"
            )
    return data


def _gateway_url(oauth: dict[str, Any]) -> str:
    """env override 优先；否则用 oauth json 里的 gateway_url。"""
    override = os.environ.get("ATLAS_GATEWAY_URL", "").strip()
    base = override or oauth.get("gateway_url", "").rstrip("/")
    if not base:
        raise AtlasGatewayError("no gateway_url in oauth json and ATLAS_GATEWAY_URL not set")
    return base.rstrip("/")


def call_tool(
    *,
    service: str,
    tool: str,
    arguments: dict[str, Any],
    oauth_path: Path | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Any:
    """走 atlas-ai-gateway 调一个 MCP 工具，返回内层（已 unwrap）的数据。

    Args:
        service: MCP service 名（``"dap"`` / ``"web2feishu"`` ...）
        tool: tool 名（``"get_custom_report"`` / ``"query_material_report"`` ...）
        arguments: tool 入参 dict。
        oauth_path: 覆盖默认 OAuth 文件路径。
        timeout: HTTP 超时秒。

    Returns:
        MCP 工具的内层数据。多数 DAP 工具返回 ``{"tables":[...]}`` 或 ``{"data":[...]}``；
        本函数已经 unwrap MCP 信封 ``result.content[0].text`` 那层。

    Raises:
        AtlasOAuthFileMissingError, AtlasTokenExpiredError, AtlasGatewayError
    """
    oauth = _load_oauth(path=oauth_path)
    url = f"{_gateway_url(oauth)}/mcp-servers/{service}"
    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {oauth['access_token']}",
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)

    if resp.status_code == 401:
        raise AtlasTokenExpiredError(
            f"atlas-ai-gateway 返回 401（token 失效）。{_RECOVER_HINT}"
        )
    if resp.status_code != 200:
        raise AtlasGatewayError(
            f"atlas-ai-gateway HTTP {resp.status_code}: {resp.text[:300]}"
        )

    body = resp.json()
    if "error" in body and body["error"]:
        err = body["error"]
        msg = err.get("message", "unknown") if isinstance(err, dict) else str(err)
        raise AtlasGatewayError(f"JSON-RPC error: {msg}")

    result = body.get("result", {})
    content = result.get("content", []) if isinstance(result, dict) else []
    if content and isinstance(content[0], dict) and content[0].get("type") == "text":
        text = content[0].get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return result
