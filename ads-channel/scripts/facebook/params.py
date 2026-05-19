"""Facebook 广告创建参数 TypedDict 定义。

所有 create 函数接收对应的 TypedDict 字典。
金额字段统一用 USD（float），内部自动转 cents。
"""
from __future__ import annotations

from typing import TypedDict


# ─── Campaign ─────────────────────────────────────────────────────────

class CampaignCreateParams(TypedDict, total=False):
    """Campaign 创建参数。必填: name。"""
    name: str
    objective: str
    daily_budget: float
    lifetime_budget: float
    status: str
    bid_strategy: str
    special_ad_categories: list[str]
    spend_cap: float
    start_time: str
    stop_time: str
    is_skadnetwork_attribution: bool
    is_adset_budget_sharing_enabled: bool
    smart_promotion_type: str


CAMPAIGN_DEFAULTS: CampaignCreateParams = {
    "objective": "OUTCOME_APP_PROMOTION",
    "status": "PAUSED",
    "special_ad_categories": [],
}


# ─── AdSet ────────────────────────────────────────────────────────────

class AdSetCreateParams(TypedDict, total=False):
    """AdSet 创建参数。必填: name, campaign_id。"""
    name: str
    campaign_id: str
    daily_budget: float
    lifetime_budget: float
    status: str
    bid_strategy: str
    bid_amount: float
    bid_constraints: dict
    billing_event: str
    optimization_goal: str
    promoted_object: dict
    attribution_spec: list[dict]
    destination_type: str
    start_time: str
    end_time: str
    is_dynamic_creative: bool
    # targeting 相关（由 _build_targeting 消费，不直接传 API）
    countries: list[str]
    os: str
    audience_type: str
    publisher_platforms: list[str]
    age_min: int
    age_max: int
    genders: list[int]
    locales: list[int]
    interests: list[dict]
    custom_audiences: list[dict]
    excluded_custom_audiences: list[dict]
    app_install_state: str


ADSET_DEFAULTS: AdSetCreateParams = {
    "status": "PAUSED",
    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    "billing_event": "IMPRESSIONS",
    "optimization_goal": "APP_INSTALLS",
    "audience_type": "Broad",
}


# ─── Ad ───────────────────────────────────────────────────────────────

class AdCreateParams(TypedDict, total=False):
    """Ad 创建参数。必填: name, adset_id, creative_id。"""
    name: str
    adset_id: str
    creative_id: str
    status: str
    tracking_specs: list[dict]
    conversion_domain: str


AD_DEFAULTS: AdCreateParams = {
    "status": "PAUSED",
}


# ─── 工具函数 ─────────────────────────────────────────────────────────

def _usd_to_cents(usd: float) -> int:
    """USD 元转 cents（×100，四舍五入取整）。"""
    return int(round(usd * 100))


def _cents_to_usd(cents) -> float | None:
    """cents 转 USD 元。None 输入返回 None。"""
    if cents is None:
        return None
    return int(cents) / 100


USD_FIELDS: frozenset[str] = frozenset({
    "daily_budget",
    "lifetime_budget",
    "spend_cap",
    "bid_amount",
})

def validate_usd_fields(params: dict) -> None:
    """校验金额字段并输出确认信息。

    打印每个金额字段的 USD 值和转换后的 cents 值，
    供 Agent 在 stdout 中看到并确认金额是否符合预期。
    """
    import sys
    for field in USD_FIELDS:
        val = params.get(field)
        if val is None:
            continue
        cents = int(round(val * 100))
        print(
            f"[CONFIRM] {field}: ${val:.2f} USD (= {cents} cents)",
            file=sys.stderr,
        )
