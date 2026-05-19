"""Facebook 渠道配置 — 从 workspace/.env 读取 Facebook 凭据。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 向上查找 workspace/.env
_SCRIPT_DIR = Path(__file__).resolve().parent
_WORKSPACE_DIR = _SCRIPT_DIR.parent.parent.parent.parent  # facebook -> scripts -> ads-channel -> skills -> workspace
_ENV_PATH = _WORKSPACE_DIR / ".env"

load_dotenv(_ENV_PATH)


def _require(var: str) -> str:
    val = os.getenv(var)
    if not val:
        raise RuntimeError(
            f"环境变量 {var} 未设置。请在 {_ENV_PATH} 中配置。"
        )
    return val


SOCIAL_FB_TOKEN: str = _require("SOCIAL_FB_TOKEN")

# 账户 ID 自动补 act_ 前缀
_raw_account = os.getenv("META_AD_ACCOUNT_ID", "")
if _raw_account and not _raw_account.startswith("act_"):
    META_AD_ACCOUNT_ID = f"act_{_raw_account}"
else:
    META_AD_ACCOUNT_ID = _raw_account

# Business ID — DAP 素材上传的目标 Business（Lilith Games）
# env 未设置时回退到硬编码默认，保持向后兼容
META_BUSINESS_ID: str = os.getenv("META_BUSINESS_ID", "1589262821285499")

API_VERSION = "v24.0"
