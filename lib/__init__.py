"""ua_agent skill 共享库。

import 时自动加载 workspace/.env，使 dap_client / fetchers / feishu 等
直接读 os.environ 的模块在任意调用入口下都能拿到业务凭据。
"""
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)
