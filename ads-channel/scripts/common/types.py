"""跨渠道共享的类型和常量。"""

# 允许的实体状态（不含 DELETED，遵循 AGENTS.md 红线）
ALLOWED_STATUSES: frozenset[str] = frozenset({"PAUSED", "ACTIVE"})

# 支持的渠道
SUPPORTED_CHANNELS: frozenset[str] = frozenset({"facebook", "tiktok", "google"})

# 实体类型
ENTITY_TYPES: frozenset[str] = frozenset({"campaign", "adset", "ad"})
