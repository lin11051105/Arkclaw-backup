"""Shared enums for sentiment-daily-report.

Values follow report_schema.json so that downstream consumers can import
canonical string literals instead of repeating magic strings.
"""
from __future__ import annotations

from enum import Enum


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class RiskLevel(str, Enum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    STAR = "star"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TrendDirection(str, Enum):
    WORSENING = "worsening"
    STABLE = "stable"
    IMPROVING = "improving"
    RESOLVED = "resolved"


class TriggerType(str, Enum):
    """PRD 2.4 重大舆情警报触发分类。"""

    A_NEGATIVE_BURST = "A_creative_negative_burst"
    B_HIGH_ENGAGEMENT = "B_high_engagement_comment"
    C_NOT_IMPLEMENTED = "C_not_implemented"
