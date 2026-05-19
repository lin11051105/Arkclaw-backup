"""Sentiment + theme classification.

Two paths:
1. **passthrough**: comments already carry ``sentiment``/``theme`` keys
   (used by fixture-driven flows and unit tests). No external calls.
2. **claude-cli subprocess**: shell out to the local ``claude`` binary
   with a structured prompt + JSON-only response. Used in production.

Always emits a stable result shape: each comment gets ``sentiment`` ∈
{positive, neutral, negative} and ``theme`` ∈ ``config.CANONICAL_THEMES``
(unknown values bucket to ``other``, missing → ``unclassified``).

Diagnostics
-----------
``classify(..., diagnostics=<dict>)`` accepts an optional dict that the
classifier mutates with::

    {"is_degraded": bool, "reasons": [<reason_code>, ...], "events": int}

reason_code ∈ {"timeout", "non_zero_returncode", "json_decode_error"}.
Callers (cli.py) attach this dict to ``report.meta.degradation_flag`` so
downstream consumers know the row labels are partially fallback values.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Iterable

from . import config

_log = logging.getLogger(__name__)

# Diagnostic reason codes — exported for tests / downstream consumers
_REASON_TIMEOUT = "timeout"
_REASON_NON_ZERO_RETURNCODE = "non_zero_returncode"
_REASON_JSON_DECODE_ERROR = "json_decode_error"

# ── Prompt template (kept local to avoid YAML dependency) ────
_PROMPT_HEADER = """\
You are a strict JSON classifier for Facebook ad comments. For each comment,
return EXACTLY this JSON shape (no prose):

{"id": <id>, "sentiment": "positive"|"neutral"|"negative", "theme": <short_snake_case>, "zh": "<Chinese translation or empty>"}

Rules for "zh" field:
  - If the comment is already in Chinese → "zh": ""
  - Otherwise → translate the comment into concise Chinese (one sentence)

Themes MUST be drawn from this closed list (anything else will be rejected):
  - graphics_praise, gameplay_praise, general_praise
  - download_question, gameplay_question
  - ad_overpromise, value_misalign, technical_issue, general_complaint
  - graphics_complaint
  - political_sensitive  (political, religious, or values-related sensitive content)
  - other          (use only when none of the above fit)

Output ONE JSON object per line (JSONL). No commentary.
"""


def _normalize_theme(value: Any) -> str:
    """Collapse a free-form theme string onto ``config.CANONICAL_THEMES``.

    - ``None`` / empty / whitespace → ``"unclassified"``
    - canonical bucket (case-insensitive) → lowercased canonical form
    - unknown / hallucinated bucket → ``"other"``

    Pure: never raises, never mutates input.
    """
    if value is None:
        return "unclassified"
    if not isinstance(value, str):
        # Defensive: schema only accepts string but be safe with bad input
        return "other"
    stripped = value.strip().lower()
    if not stripped:
        return "unclassified"
    if stripped in config.CANONICAL_THEMES:
        return stripped
    return "other"


def needs_classification(comments: Iterable[dict[str, Any]]) -> bool:
    """True iff any comment lacks sentiment/theme."""
    return any(
        c.get("sentiment") is None or c.get("theme") is None for c in comments
    )


def _passthrough(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fixture-mode: comments already classified — copy + normalize theme."""
    out = []
    for c in comments:
        sentiment = c.get("sentiment") or "neutral"
        theme = _normalize_theme(c.get("theme"))
        out.append({**c, "sentiment": sentiment, "theme": theme})
    return out


def _build_prompt(batch: list[dict[str, Any]]) -> str:
    lines = [
        json.dumps(
            {"id": c["id"], "language": c.get("language", "other"), "text": c.get("text", "")},
            ensure_ascii=False,
        )
        for c in batch
    ]
    return _PROMPT_HEADER + "\n" + "\n".join(lines) + "\n"


def _record_degradation(
    diagnostics: dict[str, Any] | None,
    reason: str,
) -> None:
    """Mutate ``diagnostics`` to flag a fallback event.

    No-op when ``diagnostics is None`` so the call sites stay tidy.
    """
    if diagnostics is None:
        return
    diagnostics["is_degraded"] = True
    diagnostics.setdefault("reasons", [])
    if reason not in diagnostics["reasons"]:
        diagnostics["reasons"].append(reason)
    diagnostics["events"] = int(diagnostics.get("events", 0)) + 1


def _classify_via_claude(
    batch: list[dict[str, Any]],
    *,
    timeout: int = 60,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    """Run claude CLI in non-interactive mode, parse JSONL response.

    Prompt is delivered via **stdin** (``input=``), NOT argv:
    - argv has an OS-level ARG_MAX limit (~128 KB on Linux); a 25-comment
      batch easily blows past that with multibyte text.
    - argv leaks the prompt body into ``ps`` and audit logs.

    Returns:
        Mapping of comment_id → {sentiment, theme}. Comments that fail to
        parse are dropped (caller falls back to defaults). Each fallback
        path also records a reason into ``diagnostics`` (when provided).
    """
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError(
            "claude CLI not found in PATH. Install Claude Code or expose "
            "the binary before running classification."
        )

    prompt = _build_prompt(batch)
    env = {**os.environ}

    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [cli, "-p", "-", "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _log.warning(
            "claude CLI timed out after %ds (batch=%d); falling back to neutral",
            timeout,
            len(batch),
        )
        _record_degradation(diagnostics, _REASON_TIMEOUT)
        return {}

    if proc.returncode != 0:
        _log.warning(
            "claude CLI exited with non-zero code %s (batch=%d): %s",
            proc.returncode,
            len(batch),
            (proc.stderr or "")[:200],
        )
        _record_degradation(diagnostics, _REASON_NON_ZERO_RETURNCODE)
        return {}

    out: dict[str, dict[str, str]] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("```"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        cid = obj.get("id")
        if not cid:
            continue
        entry: dict[str, str] = {
            "sentiment": obj.get("sentiment", "neutral"),
            "theme": _normalize_theme(obj.get("theme")),
        }
        zh = obj.get("zh", "")
        if zh and isinstance(zh, str) and zh.strip():
            entry["zh"] = zh.strip()
        out[str(cid)] = entry
    return out


def classify(
    comments: list[dict[str, Any]],
    *,
    use_claude: bool = True,
    batch_size: int = 25,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Classify comments, returning a NEW list.

    - If ALL comments already carry sentiment+theme → passthrough.
    - Otherwise (and ``use_claude=True``) → batched claude CLI call.
    - On any classifier failure, missing labels default to neutral/unclassified.

    ``diagnostics`` (optional): mutable dict the caller passes in. After this
    call returns, it carries ``is_degraded``/``reasons``/``events``. Pass
    ``None`` (default) when you don't care.
    """
    # Initialize diagnostics envelope when caller opted in
    if diagnostics is not None:
        diagnostics.setdefault("is_degraded", False)
        diagnostics.setdefault("reasons", [])
        diagnostics.setdefault("events", 0)

    if not needs_classification(comments):
        return _passthrough(comments)

    if not use_claude:
        return _passthrough(comments)

    enriched: list[dict[str, Any]] = []
    for start in range(0, len(comments), batch_size):
        batch = comments[start : start + batch_size]
        # Only send unclassified ones to the LLM
        unclassified = [
            c for c in batch
            if c.get("sentiment") is None or c.get("theme") is None
        ]
        labels = (
            _classify_via_claude(unclassified, diagnostics=diagnostics)
            if unclassified
            else {}
        )
        for c in batch:
            cid = c["id"]
            if c.get("sentiment") and c.get("theme"):
                enriched.append(
                    {**c, "theme": _normalize_theme(c["theme"])}
                )
                continue
            label = labels.get(cid, {})
            row = {
                **c,
                "sentiment": c.get("sentiment") or label.get("sentiment", "neutral"),
                "theme": _normalize_theme(
                    c.get("theme") or label.get("theme")
                ),
            }
            if label.get("zh"):
                row["zh"] = label["zh"]
            enriched.append(row)
    return enriched
