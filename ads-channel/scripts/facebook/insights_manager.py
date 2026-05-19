"""Facebook Ad Insights 查询。

从 Facebook Marketing API 获取 Ad/AdSet/Campaign 级效果数据（spend / impressions / clicks / CTR / CPI），
供 ads-channel CLI 及其他 Skill 通过 importlib 调用。
"""
from __future__ import annotations

from .client import MetaAdsClient

# Insights 请求字段
_INSIGHT_FIELDS = [
    "ad_id",
    "ad_name",
    "campaign_id",
    "campaign_name",
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "actions",
    "action_values",
]


def _extract_installs(actions: list[dict] | None) -> int:
    """从 actions 数组中提取 mobile_app_install 计数。"""
    if not actions:
        return 0
    for action in actions:
        if action.get("action_type") == "mobile_app_install":
            return int(action.get("value", 0))
    return 0


def _extract_revenue(action_values: list[dict] | None) -> float:
    """从 action_values 数组中提取 purchase 收入金额。

    action_values 格式: [{"action_type": "purchase", "value": "123.45"}, ...]
    也匹配 fb_mobile_purchase。
    """
    if not action_values:
        return 0.0
    for av in action_values:
        if av.get("action_type") in ("purchase", "fb_mobile_purchase"):
            return float(av.get("value", 0))
    return 0.0


def get_ad_insights(
    client: MetaAdsClient,
    date_start: str,
    date_end: str,
    time_increment: int | None = 1,
    level: str = "ad",
    include_inactive: bool = False,
) -> list[dict]:
    """查询账户下 Ad 级 Insights 数据。

    Args:
        client: MetaAdsClient 实例
        date_start: 开始日期 YYYY-MM-DD
        date_end: 结束日期 YYYY-MM-DD
        time_increment: 时间粒度（1=逐日，None=聚合整个区间）
        level: 查询级别（ad/adset/campaign/account）
        include_inactive: True 时不过滤 ACTIVE 状态，用于对账等需要全状态数据的场景

    Returns:
        [{"ad_id", "ad_name", "campaign_id", "campaign_name", "date",
          "spend", "impressions", "clicks", "ctr", "installs", "cpi",
          "revenue"}, ...]
        cpi 为 None 当 installs == 0。
    """
    params: dict = {
        "level": level,
        "time_range": {"since": date_start, "until": date_end},
    }
    if not include_inactive:
        params["filtering"] = [
            {"field": "ad.effective_status", "operator": "IN", "value": ["ACTIVE"]},
        ]
    if time_increment is not None:
        params["time_increment"] = time_increment

    raw_rows = client.account.get_insights(fields=_INSIGHT_FIELDS, params=params)

    results: list[dict] = []
    for row in raw_rows:
        spend = float(row.get("spend", 0))
        installs = _extract_installs(row.get("actions"))
        cpi = spend / installs if installs > 0 else None

        results.append({
            "ad_id": row.get("ad_id", ""),
            "ad_name": row.get("ad_name", ""),
            "campaign_id": row.get("campaign_id", ""),
            "campaign_name": row.get("campaign_name", ""),
            "date": row.get("date_start", ""),
            "spend": spend,
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "installs": installs,
            "cpi": cpi,
            "revenue": _extract_revenue(row.get("action_values")),
            "actions": row.get("actions", []),
        })

    return results
