"""ads-channel CLI 入口。

OpenClaw Agent 通过 shell 调用此脚本执行 Meta Ads 操作。

用法（从项目根目录）:
    python workspace/skills/ads-channel/scripts/cli.py <command> [options]
"""

import argparse
import importlib.util
import json
import sys
import os
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


_client_mod = _load("facebook.client")
_campaign_mod = _load("facebook.campaign_manager")
_ad_mod = _load("facebook.ad_manager")
_insights_mod = _load("facebook.insights_manager")
_app_config_mod = _load("common.app_config")
_creative_mod = _load("facebook.creative_manager")

MetaAdsClient = _client_mod.MetaAdsClient
MetaAdsError = _client_mod.MetaAdsError
campaign_manager = _campaign_mod
ad_manager = _ad_mod
insights_manager = _insights_mod
app_config = _app_config_mod
creative_manager = _creative_mod


def _parse_json_params(raw: str) -> dict:
    """解析 --params JSON 字符串，返回 dict。非 dict 或无效 JSON 时报错退出。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"--params JSON 解析失败: {e}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print(json.dumps({"error": "--params 必须是 JSON 对象（dict），不能是数组或字符串"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    return data


def _build_params_from_args(args, field_map: dict[str, str]) -> dict:
    """从 argparse args 构建 params dict。field_map: {param_key: args_attr}。"""
    params = {}
    for param_key, attr_name in field_map.items():
        val = getattr(args, attr_name, None)
        if val is not None:
            params[param_key] = val
    return params


def cmd_account_info(args):
    client = MetaAdsClient()
    if args.all:
        accounts = client.list_ad_accounts(name_filter=args.name)
        print(json.dumps(accounts, ensure_ascii=False, indent=2))
    else:
        info = client.get_account_info()
        print(json.dumps(info, ensure_ascii=False, indent=2))


def cmd_list_campaigns(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    campaigns = campaign_manager.list_campaigns(client, limit=args.limit)
    print(json.dumps(campaigns, ensure_ascii=False, indent=2))


def cmd_list_adsets(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    adsets = campaign_manager.list_adsets(client, limit=args.limit, campaign_id=args.campaign_id)
    print(json.dumps(adsets, ensure_ascii=False, indent=2))


def cmd_list_ads(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    ads = campaign_manager.list_ads(
        client,
        limit=args.limit,
        adset_id=args.adset_id,
        campaign_id=args.campaign_id,
    )
    print(json.dumps(ads, ensure_ascii=False, indent=2))



def cmd_create_campaign(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    if args.params:
        params = _parse_json_params(args.params)
    else:
        params = _build_params_from_args(args, {
            "name": "name", "daily_budget": "budget",
            "objective": "objective", "status": "status",
        })
    result = campaign_manager.create_campaign(client, params)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_create_adset(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    if args.params:
        params = _parse_json_params(args.params)
    else:
        params = _build_params_from_args(args, {
            "campaign_id": "campaign_id", "name": "name",
            "daily_budget": "budget", "os": "os",
            "bid_strategy": "bid_strategy", "status": "status",
        })
        # countries: 逗号分隔转 list
        if args.countries:
            params["countries"] = [c.strip() for c in args.countries.split(",")]
        # promoted_object: --app-id + --store-url > --project
        if args.app_id and args.store_url:
            params["promoted_object"] = {
                "application_id": args.app_id,
                "object_store_url": args.store_url,
            }
        elif args.project:
            promoted_object = app_config.resolve_promoted_object(args.project, args.os)
            if not promoted_object:
                print(json.dumps(
                    {"error": f"apps.json 中未找到 {args.project}/{args.os} 配置，请用 list-apps 检查"},
                    ensure_ascii=False,
                ), file=sys.stderr)
                sys.exit(1)
            params["promoted_object"] = promoted_object

    result = campaign_manager.create_adset(client, params)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_create_ad(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    if args.params:
        params = _parse_json_params(args.params)
    else:
        params = _build_params_from_args(args, {
            "adset_id": "adset_id", "name": "name",
            "creative_id": "creative_id", "status": "status",
        })
    result = campaign_manager.create_ad(client, params)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_duplicate_adset(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    result = campaign_manager.duplicate_adset(
        client=client,
        source_adset_id=args.source_id,
        target_campaign_id=args.target_campaign,
        budget_override=args.budget,
        new_name=getattr(args, "name", None),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_resolve_app(args):
    result = app_config.resolve_promoted_object(args.project, args.os)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": f"未找到项目 {args.project} / {args.os} 的配置"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def cmd_list_apps(args):
    apps = app_config.load_app_config()
    print(json.dumps(apps, ensure_ascii=False, indent=2))


def cmd_get_promoted_object(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    results = campaign_manager.get_promoted_object_from_account(client, limit=args.limit)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_batch_update(args):
    """批量更新多个实体的参数（单个失败不影响其余）。"""
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    entity_ids = [e.strip() for e in args.entity_ids.split(",")]
    params = _parse_json_params(args.params)
    results = []
    for eid in entity_ids:
        try:
            r = campaign_manager.update_entity(
                client,
                entity_type=args.type,
                entity_id=eid,
                params=params,
            )
            results.append(r)
        except Exception as e:
            results.append({"entity_id": eid, "entity_type": args.type, "success": False, "error": str(e)})
    print(json.dumps(results, ensure_ascii=False, indent=2))


def _resolve_os_config(args):
    """从 --project + --os 解析 promoted_object 和 Facebook 配置。"""
    po = app_config.resolve_promoted_object(args.project, args.os)
    if not po:
        print(json.dumps(
            {"error": f"apps.json 中未找到 {args.project}/{args.os} 配置"},
            ensure_ascii=False,
        ), file=sys.stderr)
        sys.exit(1)
    app_cfg = app_config.load_app_config(args.project)
    fb = app_cfg.get("facebook", {})
    return po, fb


def _adapt_creative_for_os(client, creative_id: str, args) -> str:
    """根据 --os + --project 跨平台适配 creative，返回适配后的 creative_id。"""
    if not (args.os and args.project):
        return creative_id
    po, fb = _resolve_os_config(args)
    return creative_manager.ensure_creative_for_os(
        client,
        creative_id=creative_id,
        os_type=args.os,
        store_url=po["object_store_url"],
        page_id=fb.get("page_id", ""),
        instagram_actor_id=fb.get("instagram_actor_id", ""),
    )


def _is_adset_creation(args, params: dict) -> bool:
    """params 含 name + 有 OS/project 或 countries → 创建 AdSet。"""
    if "name" not in params:
        return False
    return bool(args.os and args.project) or "countries" in params or "promoted_object" in params


def _is_ad_creation(params: dict) -> bool:
    """params 含顶层 creative_id（非嵌套 creative dict）→ 创建 Ad。"""
    return "creative_id" in params and "creative" not in params


def cmd_update_entity(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    params = _parse_json_params(args.params) if args.params else {}

    # ── type=adset + 创建信号 → 为 Campaign 创建 AdSet ──
    if args.type == "adset" and _is_adset_creation(args, params):
        params["campaign_id"] = args.entity_id
        if args.project and args.os:
            po, _ = _resolve_os_config(args)
            params.setdefault("promoted_object", po)
            params.setdefault("os", args.os)
        result = campaign_manager.create_adset(client, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # ── type=ad + 创建信号 → 为 AdSet 创建 Ad ──
    if args.type == "ad" and _is_ad_creation(params):
        params["adset_id"] = args.entity_id
        creative_id = params.get("creative_id")
        if creative_id:
            params["creative_id"] = _adapt_creative_for_os(client, creative_id, args)
        result = campaign_manager.create_ad(client, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # ── 标准更新 ──
    if not params:
        print(json.dumps({"error": "update 操作需要 --params"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    if args.type == "ad" and args.os and args.project:
        creative_dict = params.get("creative", {})
        source_creative_id = creative_dict.get("creative_id")
        if source_creative_id:
            adapted_id = _adapt_creative_for_os(client, source_creative_id, args)
            if adapted_id != source_creative_id:
                params["creative"]["creative_id"] = adapted_id

    result = campaign_manager.update_entity(
        client,
        entity_type=args.type,
        entity_id=args.entity_id,
        params=params,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_get_insights(args):
    client = MetaAdsClient(account_id=args.account_id if args.account_id else None)
    result = insights_manager.get_ad_insights(
        client=client,
        date_start=args.date_start,
        date_end=args.date_end,
        time_increment=args.time_increment,
        level=args.level,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_get_status(args):
    client = MetaAdsClient()
    result = ad_manager.get_entity_status(
        client,
        entity_id=args.entity_id,
        entity_type=args.type,
    )
    # 拼 Ads Manager 直链，免得 Hermes 还得自己查 account_id
    act = client.account_id.lstrip("act_")
    if args.type == "campaign":
        result["campaign_url"] = (
            f"https://www.facebook.com/adsmanager/manage/campaigns"
            f"?act={act}&campaign_ids={args.entity_id}"
        )
    elif args.type == "adset":
        result["adset_url"] = (
            f"https://www.facebook.com/adsmanager/manage/adsets"
            f"?act={act}&adset_ids={args.entity_id}"
        )
    elif args.type == "ad":
        result["ad_url"] = (
            f"https://www.facebook.com/adsmanager/manage/ads"
            f"?act={act}&ad_ids={args.entity_id}"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="ads-channel Meta Ads CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # account-info
    p = sub.add_parser("account-info", help="查看广告账户信息")
    p.add_argument("--all", action="store_true", help="列出 token 下所有可访问的广告账户")
    p.add_argument("--name", default=None, help="配合 --all 使用，按账户名称过滤（模糊匹配，如 ROK）")

    # list-campaigns
    p = sub.add_parser("list-campaigns", help="列出 Campaign")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--account-id", default=None, help="指定账户 ID")

    # list-adsets
    p = sub.add_parser("list-adsets", help="列出 AdSet")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--campaign-id", default=None, help="按 Campaign ID 过滤")

    # list-ads
    p = sub.add_parser("list-ads", help="列出 Ad（含 creative_id）")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--adset-id", default=None, help="按 AdSet ID 过滤")
    p.add_argument("--campaign-id", default=None, help="按 Campaign ID 过滤")

    # create-campaign
    p = sub.add_parser("create-campaign", help="创建 Campaign (PAUSED)")
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--params", default=None, help="JSON 参数（优先于其他 --xxx 参数）")
    p.add_argument("--name", default=None)
    p.add_argument("--budget", type=float, default=None, help="日预算 (USD)")
    p.add_argument("--objective", default="OUTCOME_APP_PROMOTION")
    p.add_argument("--status", default="PAUSED")

    # create-adset
    p = sub.add_parser("create-adset", help="创建 AdSet")
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--params", default=None, help="JSON 参数（优先于其他 --xxx 参数）")
    p.add_argument("--campaign-id", default=None)
    p.add_argument("--name", default=None)
    p.add_argument("--budget", type=float, default=None, help="日预算 (USD)")
    p.add_argument("--countries", default=None, help="逗号分隔: US,CA,JP")
    p.add_argument("--os", default="iOS")
    p.add_argument("--bid-strategy", default="LOWEST_COST_WITHOUT_CAP")
    p.add_argument("--project", default=None, help="项目代号 (ROK/PTSLG/IGAME)，自动解析商店链接")
    p.add_argument("--app-id", default=None, help="手动指定 app ID（优先于 --project）")
    p.add_argument("--store-url", default=None, help="手动指定商店 URL（优先于 --project）")
    p.add_argument("--status", default="PAUSED")

    # create-ad
    p = sub.add_parser("create-ad", help="创建 Ad")
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--params", default=None, help="JSON 参数（优先于其他 --xxx 参数）")
    p.add_argument("--adset-id", default=None)
    p.add_argument("--name", default=None)
    p.add_argument("--creative-id", default=None)
    p.add_argument("--status", default="PAUSED")

    # duplicate-adset
    p = sub.add_parser("duplicate-adset", help="复制 AdSet 到目标 Campaign")
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--source-id", required=True)
    p.add_argument("--target-campaign", required=True)
    p.add_argument("--budget", type=float, default=None, help="覆盖预算 (USD)")
    p.add_argument("--name", default=None, help="新 adset 名称（默认: 源名称_dup）")

    # update-entity (通用参数更新 + 子实体创建)
    p = sub.add_parser("update-entity", help="更新/创建: --type adset 含 name+OS 创建 AdSet, --type ad 含 creative_id 创建 Ad, 其余为更新")
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--entity-id", required=True, help="目标实体 ID（更新时为实体本身，创建时为父实体）")
    p.add_argument("--type", required=True, choices=["campaign", "adset", "ad"])
    p.add_argument("--params", default=None, help='JSON 参数')
    p.add_argument("--os", default=None, choices=["iOS", "Android"],
                   help="目标 OS（自动适配 promoted_object 和 creative）")
    p.add_argument("--project", default=None,
                   help="项目代号（配合 --os 使用，读取 store URL）")

    # batch-update (批量更新)
    p = sub.add_parser("batch-update", help="批量更新多个同类实体的参数")
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--entity-ids", required=True, help="逗号分隔的 ID 列表")
    p.add_argument("--type", required=True, choices=["campaign", "adset", "ad"])
    p.add_argument("--params", required=True, help='JSON 参数，如 \'{"status": "PAUSED"}\'')

    # get-status
    p = sub.add_parser("get-status", help="查询实体状态")
    p.add_argument("--entity-id", required=True)
    p.add_argument("--type", required=True, choices=["campaign", "adset", "ad"])

    # resolve-app
    p = sub.add_parser("resolve-app", help="从 apps.json 解析 promoted_object")
    p.add_argument("--project", required=True, help="项目代号: ROK, PTSLG, IGAME")
    p.add_argument("--os", required=True, choices=["iOS", "Android"])

    # list-apps
    sub.add_parser("list-apps", help="列出 apps.json 中所有项目配置")

    # get-insights
    p = sub.add_parser("get-insights", help="查询 Ad/AdSet/Campaign 级 Insights 数据")
    p.add_argument("--account-id", default=None, help="指定账户 ID")
    p.add_argument("--date-start", required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--date-end", required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--time-increment", type=int, default=1, help="时间粒度（1=逐日，省略=聚合）")
    p.add_argument("--level", default="ad", choices=["ad", "adset", "campaign", "account"], help="查询级别")

    # get-promoted-object
    p = sub.add_parser("get-promoted-object", help="从账户现有 AdSet 反查 promoted_object")
    p.add_argument("--account-id", default=None, help="指定账户 ID，默认用 .env 中的")
    p.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    cmd_map = {
        "account-info": cmd_account_info,
        "list-campaigns": cmd_list_campaigns,
        "list-adsets": cmd_list_adsets,
        "list-ads": cmd_list_ads,
        "create-campaign": cmd_create_campaign,
        "create-adset": cmd_create_adset,
        "create-ad": cmd_create_ad,
        "duplicate-adset": cmd_duplicate_adset,
        "update-entity": cmd_update_entity,
        "batch-update": cmd_batch_update,
        "get-insights": cmd_get_insights,
        "get-status": cmd_get_status,
        "resolve-app": cmd_resolve_app,
        "list-apps": cmd_list_apps,
        "get-promoted-object": cmd_get_promoted_object,
    }

    try:
        cmd_map[args.command](args)
    except MetaAdsError as e:
        print(json.dumps({"error": str(e), "code": e.code, "subcode": e.subcode}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
