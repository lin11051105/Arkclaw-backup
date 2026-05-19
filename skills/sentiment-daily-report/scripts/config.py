"""Sentiment-daily-report configuration.

仅依赖 4 个 ENV：
  - SOCIAL_FB_TOKEN       (FB 评论拉取，复用 ads-channel)
  - META_AD_ACCOUNT_ID    (FB 账户 ID，复用 ads-channel)
  - FEISHU_APP_ID         (飞书发布，复用 lib.feishu)
  - FEISHU_APP_SECRET     (飞书发布，复用 lib.feishu)

输出路径统一落 workspace/memory/，与项目 memory 体系对齐。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

# ── 4 个允许的环境变量（PRD 红线）────────────────────────────
REQUIRED_ENV_VARS: Final[frozenset[str]] = frozenset(
    {
        "SOCIAL_FB_TOKEN",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "META_AD_ACCOUNT_ID",
    }
)

# ── 路径常量 ──────────────────────────────────────────────────
_SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
_SKILL_DIR: Final[Path] = _SCRIPT_DIR.parent
_WORKSPACE_DIR: Final[Path] = _SKILL_DIR.parent.parent

#: 持续跟踪 JSON 状态目录（PRD 第四模块）
TRACKING_DIR: Path = _WORKSPACE_DIR / "memory" / "sentiment-tracking"

#: 日报快照目录（每日 18:00 一份 YYYY-MM-DD-pgame.json）
REPORTS_DIR: Path = _WORKSPACE_DIR / "memory" / "sentiment-reports"

#: 资源/模板/契约目录
SCHEMAS_DIR: Final[Path] = _SKILL_DIR / "schemas"
FIXTURES_DIR: Final[Path] = _SKILL_DIR / "fixtures"
TEMPLATES_DIR: Final[Path] = _SKILL_DIR / "templates"

# ── 业务阈值（从 thresholds.json 读取）─────────────────────────


_THRESHOLDS_CACHE: dict | None = None


def load_sentiment_thresholds() -> dict:
    """从 thresholds.json 读取 sentiment_daily_report 节（进程级缓存）。"""
    global _THRESHOLDS_CACHE
    if _THRESHOLDS_CACHE is None:
        path = _WORKSPACE_DIR / "config" / "thresholds.json"
        all_t = json.loads(path.read_text(encoding="utf-8"))
        _THRESHOLDS_CACHE = all_t.get("sentiment_daily_report", {})
    return _THRESHOLDS_CACHE

# ── Theme 白名单（IC3 fix）──────────────────────────────────
#
# LLM 自由生成的 theme 字段会污染聚合（同义词分散、拼写差异、模型幻觉）。
# 我们把 module 2 输出收敛到一个固定 enum：
#   - 前 9 个对应 sentiment_classifier prompt 内枚举的标准 bucket；
#   - graphics_complaint 来自 fixtures（已是历史使用值，保留向后兼容）；
#   - unclassified / other 是兜底：缺失值→unclassified，未知→other。
#
# Schema (schemas/report_schema.json) 必须用同一套 enum 验收契约。
CANONICAL_THEMES: Final[frozenset[str]] = frozenset(
    {
        # Praise
        "graphics_praise",
        "gameplay_praise",
        "general_praise",
        # Question
        "download_question",
        "gameplay_question",
        # Complaint
        "ad_overpromise",
        "value_misalign",
        "technical_issue",
        "general_complaint",
        "graphics_complaint",
        # Sensitive
        "political_sensitive",
        # Fallbacks
        "unclassified",
        "other",
    }
)

#: 默认产品（一期仅支持 Pgame）
DEFAULT_PRODUCT: Final[str] = "Pgame"

#: 默认渠道（一期仅 Facebook，待扩展 TikTok/UAC）
DEFAULT_CHANNEL: Final[str] = "facebook"
