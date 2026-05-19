"""飞书 API 工具：文档创建 + 消息发送。

环境变量（从 ~/.hermes/.env 或 workspace/.env 加载）：
  FEISHU_APP_ID       — 飞书应用 App ID
  FEISHU_APP_SECRET   — 飞书应用 App Secret

库用法：
  from workspace.lib.feishu import FeishuClient

  client = FeishuClient(chat_id="uatest")  # 群名或 oc_xxx 均可
  doc = client.create_document("报告标题", blocks)
  client.send_doc_link("报告标题", doc["url"])
  client.send_text("报告已生成")

CLI 用法（直接发消息到飞书群）：
  python workspace/skills/lib/feishu.py send-text --chat-id <群名或oc_xxx> --text "消息内容"
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

_log = logging.getLogger(__name__)

_FEISHU_BASE = "https://open.feishu.cn/open-apis"
_TOKEN_CACHE: dict = {"token": "", "expires_at": 0.0}


def _get_tenant_token(app_id: str, app_secret: str) -> str:
    """获取 tenant_access_token，带内存缓存（2 小时有效）。"""
    now = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] > now + 60:
        return _TOKEN_CACHE["token"]

    resp = requests.post(
        f"{_FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data.get('msg')}")

    token = data["tenant_access_token"]
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + data.get("expire", 7200)
    return token


def _col_label(index: int) -> str:
    """Convert 0-based column index to Excel-style label (A, B, ..., Z, AA, AB, ...)."""
    label = ""
    idx = index
    while True:
        label = chr(ord("A") + idx % 26) + label
        idx = idx // 26 - 1
        if idx < 0:
            break
    return label


def _table_to_text_block(headers: list[str], rows: list[list]) -> list[dict]:
    """Render table as aligned text blocks when Sheet creation fails."""
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    def _fmt_row(cells: list) -> str:
        return " | ".join(
            str(c).ljust(col_widths[i]) if i < len(col_widths) else str(c)
            for i, c in enumerate(cells)
        )

    lines = [_fmt_row(headers), "-" * (sum(col_widths) + 3 * len(headers))]
    for row in rows:
        lines.append(_fmt_row(row))

    return [
        {"block_type": 2, "text": {
            "elements": [{"text_run": {"content": line}}], "style": {},
        }}
        for line in lines
    ]


class FeishuClient:
    """飞书 API 客户端。"""

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        chat_id: str | None = None,
    ):
        self.app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
        # Priority: explicit param > FEISHU_CHAT_ID (set by cron scheduler per job)
        raw_id = chat_id or os.environ.get("FEISHU_CHAT_ID", "")
        # If raw_id is a group name (not oc_xxx), resolve it via the Feishu API
        self.chat_id = self._resolve_chat_id(raw_id) if raw_id else raw_id

        if not self.app_id or not self.app_secret:
            raise RuntimeError(
                "FEISHU_APP_ID 和 FEISHU_APP_SECRET 必须设置"
            )

    def _resolve_chat_id(self, id_or_name: str) -> str:
        """将群名解析为 oc_xxx 格式的 chat_id。

        如果传入的已是 oc_xxx 格式，直接返回。
        否则调用 Feishu /im/v1/chats API，在机器人所在群里按名称查找。
        只有机器人已加入的群才会出现在列表中，确保找到的 chat_id 可以发消息。
        """
        if not id_or_name or id_or_name.startswith("oc_"):
            return id_or_name
        try:
            found = self.find_chat_by_name(id_or_name)
            if found:
                return found
        except Exception:
            pass
        return id_or_name

    def _token(self) -> str:
        return _get_tenant_token(self.app_id, self.app_secret)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    # ── 群列表 ────────────────────────────────────────────────

    def find_chat_by_name(self, name: str) -> Optional[str]:
        """通过群名查找机器人所在群的 chat_id。

        调用 GET /open-apis/im/v1/chats 遍历所有机器人已加入的群，
        按名称（大小写不敏感）精确匹配。

        Args:
            name: 飞书群名称，如 "UA 投放运营"

        Returns:
            chat_id（oc_xxx 格式），找不到则返回 None；存在多个同名群时返回第一个
        """
        query = name.strip().lower()
        matches: list[dict] = []
        page_token = None
        while True:
            params: dict = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token

            resp = requests.get(
                f"{_FEISHU_BASE}/im/v1/chats",
                headers=self._headers(),
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"获取群列表失败: {data.get('msg')}")

            items = data.get("data", {}).get("items", [])
            for item in items:
                if item.get("name", "").strip().lower() == query:
                    matches.append(item)

            page_info = data.get("data", {})
            if not page_info.get("has_more"):
                break
            page_token = page_info.get("page_token")

        if not matches:
            return None
        return matches[0].get("chat_id")

    # ── 文档创建 ──────────────────────────────────────────────

    def create_document(self, title: str, content_blocks: list[dict]) -> dict:
        """Create a Feishu document with structured content blocks.

        Args:
            title: Document title
            content_blocks: List of block dicts, each with 'block_type' and content.
                block_type 2 = text paragraph
                block_type 3 = heading1
                block_type 4 = heading2
                block_type 5 = heading3

        Returns:
            {"document_id": "xxx", "url": "https://lilith.feishu.cn/docx/xxx"}
        """
        headers = {**self._headers(), "Content-Type": "application/json"}

        # Create empty doc
        resp = requests.post(
            f"{_FEISHU_BASE}/docx/v1/documents",
            headers=headers,
            json={"title": title},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"创建飞书文档失败: {data.get('msg')}")

        doc_id = data["data"]["document"]["document_id"]

        # Write blocks in order, inserting sheets inline where tables appear
        _BATCH_SIZE = 50
        text_batch = []

        def _flush_text_batch():
            if not text_batch:
                return
            for i in range(0, len(text_batch), _BATCH_SIZE):
                batch = text_batch[i : i + _BATCH_SIZE]
                resp = requests.post(
                    f"{_FEISHU_BASE}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    headers=headers,
                    json={"children": batch, "index": -1},
                    timeout=30,
                )
                resp.raise_for_status()
                block_data = resp.json()
                if block_data.get("code") != 0:
                    raise RuntimeError(f"写入飞书文档内容失败: {block_data.get('msg')}")
            text_batch.clear()

        for block in content_blocks:
            if block.get("_table_data"):
                _flush_text_batch()
                try:
                    self.create_sheet_in_doc(doc_id, block["_table_data"]["headers"], block["_table_data"]["rows"])
                except Exception as exc:
                    _log.warning(
                        "Sheet creation failed for doc %s: %s — inserting text fallback",
                        doc_id, exc,
                    )
                    text_batch.extend(_table_to_text_block(
                        block["_table_data"]["headers"],
                        block["_table_data"]["rows"],
                    ))
            else:
                text_batch.append(block)

        _flush_text_batch()

        # Set document permission: org-wide readable
        try:
            requests.patch(
                f"{_FEISHU_BASE}/drive/v1/permissions/{doc_id}/public",
                headers=headers,
                params={"type": "docx"},
                json={
                    "external_access_entity": "open",
                    "security_entity": "anyone_can_view",
                    "link_share_entity": "tenant_readable",
                },
                timeout=10,
            )
        except Exception:
            pass

        url = f"https://lilith.feishu.cn/docx/{doc_id}"
        return {"document_id": doc_id, "url": url}

    def create_sheet_in_doc(
        self,
        doc_id: str,
        headers: list[str],
        rows: list[list],
    ) -> str | None:
        """Embed a Sheet (spreadsheet) in a Feishu document and write data.

        Args:
            doc_id: The document to embed the sheet in.
            headers: Column header names.
            rows: Data rows (list of lists, same length as headers).

        Returns:
            The spreadsheet token, or None on failure.
        """
        api_headers = {**self._headers(), "Content-Type": "application/json"}
        row_count = len(rows) + 1
        col_count = len(headers)
        _MAX_INIT = 9

        resp = requests.post(
            f"{_FEISHU_BASE}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            headers=api_headers,
            json={"children": [{"block_type": 30, "sheet": {
                "row_size": min(row_count, _MAX_INIT),
                "column_size": min(col_count, _MAX_INIT),
            }}]},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code != 200 or data.get("code") != 0:
            raise RuntimeError(
                f"Sheet 块创建失败: status={resp.status_code} code={data.get('code')} msg={data.get('msg')}"
            )

        sheet_token_full = data["data"]["children"][0]["sheet"]["token"]
        parts = sheet_token_full.rsplit("_", 1)
        spreadsheet_token, sheet_id = parts[0], (parts[1] if len(parts) > 1 else "")

        values = [headers] + rows
        col_letter = _col_label(col_count - 1)
        range_str = f"{sheet_id}!A1:{col_letter}{row_count}"

        resp2 = requests.put(
            f"{_FEISHU_BASE.replace('/open-apis', '')}/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values",
            headers=api_headers,
            json={"valueRange": {"range": range_str, "values": values}},
            timeout=10,
        )
        r2_data = resp2.json()
        if resp2.status_code != 200 or r2_data.get("code") != 0:
            raise RuntimeError(
                f"写入 Sheet 数据失败: status={resp2.status_code} code={r2_data.get('code')} msg={r2_data.get('msg')}"
            )

        _WIDE_COLUMNS = {"具体评论", "触发条件"}
        _DEFAULT_WIDTH = 100
        _WIDE_MULTIPLIER = 3
        for i, h in enumerate(headers):
            if h in _WIDE_COLUMNS:
                try:
                    width_resp = requests.put(
                        f"{_FEISHU_BASE.replace('/open-apis', '')}/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                        headers=api_headers,
                        json={
                            "dimension": {
                                "sheetId": sheet_id,
                                "majorDimension": "COLUMNS",
                                "startIndex": i + 1,
                                "endIndex": i + 1,
                            },
                            "dimensionProperties": {
                                "fixedSize": _DEFAULT_WIDTH * _WIDE_MULTIPLIER,
                            },
                        },
                        timeout=10,
                    )
                    width_data = width_resp.json()
                    if width_resp.status_code != 200 or width_data.get("code") != 0:
                        _log.warning(
                            "设置列宽失败 (col %d, header=%r): status=%s code=%s msg=%s",
                            i, h, width_resp.status_code, width_data.get("code"), width_data.get("msg"),
                        )
                except Exception as exc:
                    _log.warning("设置列宽异常 (col %d): %s", i, exc)

        return spreadsheet_token

    def send_doc_link(self, title: str, doc_url: str, *, chat_id: str | None = None) -> dict:
        """Send a text message with document link to chat."""
        return self.send_text(f"\U0001f4c4 {title}\n\n完整报告: {doc_url}", chat_id=chat_id)

    # ── 消息发送 ──────────────────────────────────────────────

    def send_text(
        self,
        text: str,
        *,
        chat_id: str | None = None,
    ) -> dict:
        """发送文本消息到群聊。"""
        return self._send_message(
            chat_id=chat_id,
            msg_type="text",
            content=json.dumps({"text": text}),
        )

    def _send_message(
        self,
        *,
        chat_id: str | None,
        msg_type: str,
        content: str,
    ) -> dict:
        cid = chat_id or self.chat_id
        if not cid:
            raise RuntimeError("未指定 chat_id：对话中请传 --chat-id <群名>，cron 任务请在 HEARTBEAT.md 的 prompt 中指定群 ID")

        resp = requests.post(
            f"{_FEISHU_BASE}/im/v1/messages",
            headers=self._headers(),
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": cid,
                "msg_type": msg_type,
                "content": content,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书消息发送失败: {data.get('msg')}")
        return data.get("data", {})


# ── 报告 → 飞书文档 blocks 转换 ──────────────────────────────

def report_to_doc_blocks(
    report_data: dict,
    *,
    title: str = "",
    render_fn: "Callable[[dict], str] | None" = None,
) -> list[dict]:
    """Convert a report dict to Feishu document blocks.

    If ``render_fn`` is provided, call it to get formatted Markdown text and
    convert headings/paragraphs to typed Feishu blocks.  Otherwise fall back
    to a JSON dump (legacy behaviour).

    Args:
        report_data: The report dict to convert.
        title: Optional document title (informational).
        render_fn: Optional callable ``(dict) -> str`` that returns rendered
            Markdown text for the report.
    """
    if render_fn is not None:
        rendered = render_fn(report_data)
        return _markdown_to_blocks(rendered)

    rendered = _llm_render_report(report_data)
    return _markdown_to_blocks(rendered)


def _llm_render_report(report_data: dict) -> str:
    """Use claude CLI to convert JSON report to readable Markdown.

    Falls back to basic formatting if claude is unavailable.
    """
    import shutil
    import subprocess

    json_str = json.dumps(report_data, ensure_ascii=False, indent=2)

    cli = shutil.which("claude")
    if not cli:
        return _basic_render_report(report_data)

    prompt = (
        "将以下 JSON 报告转换为可读的中文 Markdown 文档。要求：\n"
        "1. 用 # / ## / ### 做标题层级\n"
        "2. 数据用表格呈现\n"
        "3. 关键指标突出展示\n"
        "4. 不要输出代码块，直接输出 Markdown\n"
        "5. 只输出 Markdown 内容，不要解释\n\n"
        f"```json\n{json_str}\n```"
    )

    try:
        proc = subprocess.run(
            [cli, "-p", "-", "--output-format", "text"],
            input=prompt, capture_output=True, text=True,
            timeout=30, check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass

    return _basic_render_report(report_data)


def _basic_render_report(report_data: dict) -> str:
    """Minimal structured rendering when LLM is unavailable."""
    lines = []
    meta = report_data.get("meta", {})
    if meta:
        lines.append(f"# {meta.get('product', '')} 报告")
        for k in ("channel", "window_start", "window_end", "generated_at"):
            if k in meta:
                lines.append(f"- {k}: {meta[k]}")
        lines.append("")

    for key, value in report_data.items():
        if key == "meta":
            continue
        lines.append(f"## {key}")
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    headers = list(v[0].keys())
                    lines.append("| " + " | ".join(headers) + " |")
                    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                    for row in v:
                        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
                else:
                    lines.append(f"- {k}: {v}")
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            headers = list(value[0].keys())
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in value:
                lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
        else:
            lines.append(str(value))
        lines.append("")

    return "\n".join(lines)


def _markdown_to_blocks(text: str) -> list[dict]:
    """Convert rendered Markdown text to Feishu doc blocks.

    Recognises headings (# / ## / ###), Markdown tables (| col | col |),
    and regular text. Tables are rendered as code blocks for alignment.
    """
    blocks: list[dict] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        # Detect Markdown table: consecutive lines starting with |
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                if not all(c in "-| :" for c in row):
                    table_lines.append(row)
                i += 1
            if table_lines:
                headers, rows = _parse_markdown_table(table_lines)
                blocks.append({"_table_data": {"headers": headers, "rows": rows}})
            continue

        if stripped.startswith("### "):
            blocks.append({"block_type": 5, "heading3": {
                "elements": [{"text_run": {"content": stripped[4:]}}], "style": {},
            }})
        elif stripped.startswith("## "):
            blocks.append({"block_type": 4, "heading2": {
                "elements": [{"text_run": {"content": stripped[3:]}}], "style": {},
            }})
        elif stripped.startswith("# "):
            blocks.append({"block_type": 3, "heading1": {
                "elements": [{"text_run": {"content": stripped[2:]}}], "style": {},
            }})
        else:
            blocks.append({"block_type": 2, "text": {
                "elements": [{"text_run": {"content": stripped}}], "style": {},
            }})
        i += 1
    return blocks


_EMOJI_MAP = {
    "red": "\U0001f534 red",
    "yellow": "\U0001f7e1 yellow",
    "green": "\U0001f7e2 green",
    "star": "⭐ star",
}


_CELL_NEWLINE_PLACEHOLDER = "⏎"


def _parse_markdown_table(table_lines: list[str]) -> tuple[list[str], list[list]]:
    """Parse Markdown table lines into headers and data rows with emoji mapping."""
    all_rows = []
    for line in table_lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        all_rows.append(cells)

    if not all_rows:
        return [], []

    headers = all_rows[0]
    rows = []
    for row in all_rows[1:]:
        mapped = []
        for cell in row:
            cell = cell.replace(_CELL_NEWLINE_PLACEHOLDER, "\n")
            mapped.append(_EMOJI_MAP.get(cell, cell))
        rows.append(mapped)

    return headers, rows


# ── 报告持久化 + 飞书文档创建 ─────────────────────────────────

def save_and_upload_report(
    report_data: dict,
    report_name: str,
    date: str,
    *,
    output_dir: str | Path,
    chat_id: str | None = None,
    render_fn: "Callable[[dict], str] | None" = None,
) -> tuple[str | None, str | None]:
    """Create Feishu document from report data.

    Returns:
        (doc_url, error_msg) — doc_url is None if creation failed.
    """
    try:
        feishu = FeishuClient(chat_id=chat_id)
        title = f"{report_name} 报告 · {date}"
        blocks = report_to_doc_blocks(report_data, title=title, render_fn=render_fn)
        doc_info = feishu.create_document(title, blocks)
        return doc_info["url"], None
    except Exception as e:
        return None, str(e)


# ── CLI 入口 ──────────────────────────────────────────────────

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="飞书 CLI — 发消息到群聊")
    parser.add_argument("--chat-id", required=True, help="飞书群 chat_id（oc_xxx）或群名")
    sub = parser.add_subparsers(dest="command", required=True)

    p_text = sub.add_parser("send-text", help="发送文本消息到群")
    p_text.add_argument("--text", required=True, help="消息文本")

    args = parser.parse_args()
    client = FeishuClient(chat_id=args.chat_id)

    if args.command == "send-text":
        client.send_text(args.text)
        print(json.dumps({"ok": True}, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
