#!/usr/bin/env python3
"""
Applovin Campaign Manager CLI - 完整版

包含所有 API 功能
"""

import argparse
import json
import os
import sys
from typing import Dict, Any

from applovin_manager_full import ApplovinCampaignManager


def get_user_confirmation(operation_name: str, details: Dict[str, Any]) -> bool:
    """获取用户确认"""
    print("\n" + "=" * 60)
    print("⚠️  即将执行广告操作，请确认")
    print("=" * 60)
    print(f"\n📌 操作类型: {operation_name}")
    
    for key, value in details.items():
        print(f"📌 {key}: {value}")
    
    print("\n" + "=" * 60)
    print("请确认是否执行？")
    print('  ✅ 确认执行: 输入 "可以" / "确认" / "yes" / "ok"')
    print('  ❌ 取消操作: 输入其他任何内容')
    print("=" * 60)
    
    try:
        user_input = input("\n您的选择: ").strip().lower()
    except KeyboardInterrupt:
        print("\n❌ 操作已取消")
        return False
    
    confirm_keywords = ['可以', '确认', 'yes', 'ok', 'y', '是', '执行', '同意']
    if any(kw in user_input for kw in confirm_keywords):
        print("✅ 用户已确认")
        return True
    else:
        print("❌ 操作已取消")
        return False


def format_campaign(campaign: Dict) -> str:
    lines = [f"  ID: {campaign.get('id')}"]
    lines.append(f"  名称: {campaign.get('name')}")
    lines.append(f"  状态: {campaign.get('status')}")
    lines.append(f"  平台: {campaign.get('platform')}")
    
    budget = campaign.get('budget', {})
    if budget:
        if 'daily_budget_for_all_countries' in budget:
            lines.append(f"  全球预算: ${budget['daily_budget_for_all_countries']}")
        if 'country_budgets' in budget:
            lines.append(f"  国家级预算: {budget['country_budgets']}")
    
    goal = campaign.get('goal', {})
    if goal:
        lines.append(f"  目标类型: {goal.get('goal_type')}")
        lines.append(f"  目标值: {goal.get('goal_value_for_all_countries')}")
    
    lines.append(f"  竞价策略: {campaign.get('bidding_strategy')}")
    lines.append(f"  开始日期: {campaign.get('start_date')}")
    lines.append(f"  结束日期: {campaign.get('end_date', 'N/A')}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Applovin Campaign Manager - 完整版",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # Campaign 命令
    campaign_parser = subparsers.add_parser('campaign', help='Campaign 管理')
    campaign_sub = campaign_parser.add_subparsers(dest='campaign_cmd')
    
    # list
    list_cmd = campaign_sub.add_parser('list', help='列出 Campaigns')
    list_cmd.add_argument('--page', type=int, default=1)
    list_cmd.add_argument('--size', type=int, default=100)
    
    # get
    get_cmd = campaign_sub.add_parser('get', help='获取 Campaign 详情')
    get_cmd.add_argument('--campaign-id', type=int, required=True)
    
    # create
    create_cmd = campaign_sub.add_parser('create', help='创建 Campaign')
    create_cmd.add_argument('--name', required=True)
    create_cmd.add_argument('--platform', required=True, choices=['android', 'ios'])
    create_cmd.add_argument('--package-name', required=True)
    create_cmd.add_argument('--start-date', required=True)
    create_cmd.add_argument('--end-date', required=True)
    create_cmd.add_argument('--budget', type=float, required=True)
    create_cmd.add_argument('--goal-type', required=True)
    create_cmd.add_argument('--goal-value', type=float, required=True)
    create_cmd.add_argument('--countries', required=True, help='逗号分隔的国家代码')
    create_cmd.add_argument('--tracking-method', default='ADJUST')
    
    # pause/resume
    pause_cmd = campaign_sub.add_parser('pause', help='暂停 Campaign')
    pause_cmd.add_argument('--campaign-id', type=int, required=True)
    
    resume_cmd = campaign_sub.add_parser('resume', help='恢复 Campaign')
    resume_cmd.add_argument('--campaign-id', type=int, required=True)
    
    # budget
    budget_cmd = campaign_sub.add_parser('budget', help='修改预算')
    budget_sub = budget_cmd.add_subparsers(dest='budget_cmd')
    
    global_budget = budget_sub.add_parser('global', help='修改全球预算')
    global_budget.add_argument('--campaign-id', type=int, required=True)
    global_budget.add_argument('--amount', type=float, required=True)
    
    country_budget = budget_sub.add_parser('country', help='修改国家级预算')
    country_budget.add_argument('--campaign-id', type=int, required=True)
    country_budget.add_argument('--country', required=True)
    country_budget.add_argument('--amount', type=float, required=True)
    
    # goal
    goal_cmd = campaign_sub.add_parser('goal', help='修改目标')
    goal_cmd.add_argument('--campaign-id', type=int, required=True)
    goal_cmd.add_argument('--type', required=True, 
                       choices=['CPI', 'CPE', 'CPP', 'AD_ROAS', 'BLD_ROAS', 'CHK_ROAS'])
    goal_cmd.add_argument('--value', type=float, required=True)
    goal_cmd.add_argument('--country', help='可选：指定国家')
    
    # bidding
    bidding_cmd = campaign_sub.add_parser('bidding', help='修改竞价策略')
    bidding_cmd.add_argument('--campaign-id', type=int, required=True)
    bidding_cmd.add_argument('--strategy', required=True,
                            choices=['target_goal_with_cpi_billing',
                                    'auto_bidding_with_cpm_billing',
                                    'maximize_results_with_cpm_billing'])
    
    # targeting
    targeting_cmd = campaign_sub.add_parser('targeting', help='国家定向管理')
    targeting_sub = targeting_cmd.add_subparsers(dest='targeting_cmd')
    
    targeting_list = targeting_sub.add_parser('list', help='列出目标国家')
    targeting_list.add_argument('--campaign-id', type=int, required=True)
    
    targeting_add = targeting_sub.add_parser('add', help='添加国家')
    targeting_add.add_argument('--campaign-id', type=int, required=True)
    targeting_add.add_argument('--countries', required=True, help='逗号分隔')
    
    targeting_remove = targeting_sub.add_parser('remove', help='移除国家')
    targeting_remove.add_argument('--campaign-id', type=int, required=True)
    targeting_remove.add_argument('--countries', required=True, help='逗号分隔')
    
    targeting_set = targeting_sub.add_parser('set', help='设置国家（替换）')
    targeting_set.add_argument('--campaign-id', type=int, required=True)
    targeting_set.add_argument('--countries', required=True, help='逗号分隔')
    
    # Creative Set 命令
    creative_parser = subparsers.add_parser('creative', help='素材组管理')
    creative_sub = creative_parser.add_subparsers(dest='creative_cmd')
    
    # list
    creative_list = creative_sub.add_parser('list', help='列出素材组')
    creative_list.add_argument('--campaign-id', type=int)
    creative_list.add_argument('--page', type=int, default=1)
    creative_list.add_argument('--size', type=int, default=100)
    
    # get
    creative_get = creative_sub.add_parser('get', help='获取素材组详情')
    creative_get.add_argument('--creative-set-id', type=int, required=True)
    
    # create
    creative_create = creative_sub.add_parser('create', help='创建素材组')
    creative_create.add_argument('--name', required=True)
    creative_create.add_argument('--campaign-id', required=True)
    creative_create.add_argument('--assets', required=True, help='JSON 格式的资源列表')
    creative_create.add_argument('--countries', help='逗号分隔')
    creative_create.add_argument('--languages', help='逗号分隔')
    creative_create.add_argument('--status', default='LIVE', choices=['LIVE', 'PAUSED'])
    
    # update
    creative_update = creative_sub.add_parser('update', help='更新素材组')
    creative_update.add_argument('--creative-set-id', type=int, required=True)
    creative_update.add_argument('--name')
    creative_update.add_argument('--assets', help='JSON 格式')
    creative_update.add_argument('--status', choices=['LIVE', 'PAUSED'])
    
    # clone
    creative_clone = creative_sub.add_parser('clone', help='克隆素材组')
    creative_clone.add_argument('--creative-set-id', type=int, required=True)
    creative_clone.add_argument('--target-campaign-id', type=int, required=True)
    creative_clone.add_argument('--status', default='PAUSED', choices=['LIVE', 'PAUSED'])
    
    # enable/disable
    creative_enable = creative_sub.add_parser('enable', help='启用素材组')
    creative_enable.add_argument('--creative-set-id', type=int, required=True)
    
    creative_disable = creative_sub.add_parser('disable', help='禁用素材组')
    creative_disable.add_argument('--creative-set-id', type=int, required=True)
    
    # Asset 命令
    asset_parser = subparsers.add_parser('asset', help='资源管理')
    asset_sub = asset_parser.add_subparsers(dest='asset_cmd')
    
    # list
    asset_list = asset_sub.add_parser('list', help='列出资源')
    asset_list.add_argument('--page', type=int, default=1)
    asset_list.add_argument('--size', type=int, default=100)
    asset_list.add_argument('--type', choices=['image', 'html', 'video'])
    
    # upload
    asset_upload = asset_sub.add_parser('upload', help='上传资源')
    asset_upload.add_argument('--files', nargs='+', required=True, help='文件路径列表')
    
    # upload-result
    asset_result = asset_sub.add_parser('upload-result', help='查询上传结果')
    asset_result.add_argument('--upload-id', required=True)
    
    # upload-from-dap 命令
    upload_dap = asset_sub.add_parser('upload-from-dap', 
                                       help='从 DAP 素材库同步素材到 Applovin')
    upload_dap.add_argument('--game-id', type=int, required=True,
                           help='项目 ID (Wgame=10048)')
    upload_dap.add_argument('--type', default='video',
                           choices=['video', 'image', 'image_set', 'trial_play'],
                           help='素材类型 (默认: video)')
    upload_dap.add_argument('--language', help='语系 (en/cn/ja/ko/ru 等)')
    upload_dap.add_argument('--ratio', help='尺寸比例 (如 1080*1920)')
    upload_dap.add_argument('--material-class', 
                           help='素材大类 (AI/3D/剪辑/KOL/本地化)')
    upload_dap.add_argument('--start-date', required=True,
                           help='开始日期 (YYYY-MM-DD)')
    upload_dap.add_argument('--end-date', required=True,
                           help='结束日期 (YYYY-MM-DD)')
    upload_dap.add_argument('--page-size', type=int, default=1000,
                           help='每页查询数量 (默认: 1000)')
    upload_dap.add_argument('--local-dir', default='/tmp/apl_upload',
                           help='本地临时目录 (默认: /tmp/apl_upload)')
    upload_dap.add_argument('--skip-confirm', action='store_true',
                           help='跳过用户确认')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # 获取凭证
    api_key = os.environ.get("APPLOVIN_API_KEY")
    account_id = os.environ.get("APPLOVIN_ACCOUNT_ID")
    
    if not api_key or not account_id:
        print("错误：未设置环境变量 APPLOVIN_API_KEY 或 APPLOVIN_ACCOUNT_ID")
        sys.exit(1)
    
    manager = ApplovinCampaignManager(api_key, account_id)
    
    # 执行命令
    try:
        if args.command == 'campaign':
            handle_campaign_command(manager, args)
        elif args.command == 'creative':
            handle_creative_command(manager, args)
        elif args.command == 'asset':
            handle_asset_command(manager, args)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


def handle_campaign_command(manager: ApplovinCampaignManager, args):
    """处理 Campaign 命令"""
    
    if args.campaign_cmd == 'list':
        campaigns = manager.list_campaigns(page=args.page, size=args.size)
        print(f"找到 {len(campaigns)} 个 Campaigns:\n")
        for c in campaigns:
            print(format_campaign(c))
            print()
    
    elif args.campaign_cmd == 'get':
        campaign = manager.get_campaign(args.campaign_id)
        if campaign:
            print(format_campaign(campaign))
        else:
            print(f"找不到 Campaign {args.campaign_id}")
    
    elif args.campaign_cmd == 'create':
        if not get_user_confirmation("创建 Campaign", {
            "名称": args.name,
            "平台": args.platform,
            "预算": f"${args.budget}",
            "目标": f"{args.goal_type} = {args.goal_value}",
            "国家": args.countries
        }):
            return
        
        budget = {"daily_budget_for_all_countries": args.budget}
        goal = {
            "goal_type": args.goal_type,
            "goal_value_for_all_countries": args.goal_value
        }
        targeting = [{"country_code": c.strip()} for c in args.countries.split(',')]
        tracking = {"tracking_method": args.tracking_method}
        
        result = manager.create_campaign(
            name=args.name,
            platform=args.platform,
            package_name=args.package_name,
            start_date=args.start_date,
            end_date=args.end_date,
            budget=budget,
            goal=goal,
            targeting=targeting,
            tracking=tracking
        )
        print(f"✅ Campaign 创建成功: {json.dumps(result, indent=2)}")
    
    elif args.campaign_cmd == 'pause':
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"找不到 Campaign {args.campaign_id}")
            return
        
        if not get_user_confirmation("暂停 Campaign", {
            "ID": args.campaign_id,
            "名称": campaign.get('name'),
            "当前状态": campaign.get('status')
        }):
            return
        
        result = manager.pause_campaign(args.campaign_id)
        print(f"✅ Campaign 已暂停: {json.dumps(result, indent=2)}")
    
    elif args.campaign_cmd == 'resume':
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"找不到 Campaign {args.campaign_id}")
            return
        
        if not get_user_confirmation("恢复 Campaign", {
            "ID": args.campaign_id,
            "名称": campaign.get('name'),
            "当前状态": campaign.get('status')
        }):
            return
        
        result = manager.resume_campaign(args.campaign_id)
        print(f"✅ Campaign 已恢复: {json.dumps(result, indent=2)}")
    
    elif args.campaign_cmd == 'budget':
        if args.budget_cmd == 'global':
            campaign = manager.get_campaign(args.campaign_id)
            old_budget = campaign.get('budget', {}).get('daily_budget_for_all_countries', 0)
            
            if not get_user_confirmation("修改全球预算", {
                "Campaign ID": args.campaign_id,
                "原预算": f"${old_budget}",
                "新预算": f"${args.amount}"
            }):
                return
            
            result = manager.update_global_budget(args.campaign_id, args.amount)
            print(f"✅ 预算已更新: {json.dumps(result, indent=2)}")
        
        elif args.budget_cmd == 'country':
            if not get_user_confirmation("修改国家级预算", {
                "Campaign ID": args.campaign_id,
                "国家": args.country,
                "新预算": f"${args.amount}"
            }):
                return
            
            result = manager.update_country_budget(args.campaign_id, args.country, args.amount)
            print(f"✅ 国家级预算已更新: {json.dumps(result, indent=2)}")
    
    elif args.campaign_cmd == 'goal':
        campaign = manager.get_campaign(args.campaign_id)
        old_goal = campaign.get('goal', {})
        
        if not get_user_confirmation("修改目标", {
            "Campaign ID": args.campaign_id,
            "原目标类型": old_goal.get('goal_type'),
            "原目标值": old_goal.get('goal_value_for_all_countries'),
            "新目标类型": args.type,
            "新目标值": args.value,
            "国家": args.country or "全球"
        }):
            return
        
        result = manager.update_goal(args.campaign_id, args.type, args.value, args.country)
        print(f"✅ 目标已更新: {json.dumps(result, indent=2)}")
    
    elif args.campaign_cmd == 'bidding':
        campaign = manager.get_campaign(args.campaign_id)
        old_strategy = campaign.get('bidding_strategy')
        
        if not get_user_confirmation("修改竞价策略", {
            "Campaign ID": args.campaign_id,
            "原策略": old_strategy,
            "新策略": args.strategy
        }):
            return
        
        result = manager.update_bidding_strategy(args.campaign_id, args.strategy)
        print(f"✅ 竞价策略已更新: {json.dumps(result, indent=2)}")
    
    elif args.campaign_cmd == 'targeting':
        if args.targeting_cmd == 'list':
            targeting = manager.get_targeting(args.campaign_id)
            print(f"目标国家 ({len(targeting)} 个):")
            for t in targeting:
                country = t.get('country_code')
                regions = t.get('region_codes', [])
                if regions:
                    print(f"  • {country} (地区: {', '.join(regions)})")
                else:
                    print(f"  • {country}")
        
        elif args.targeting_cmd == 'add':
            countries = [c.strip() for c in args.countries.split(',')]
            campaign = manager.get_campaign(args.campaign_id)
            current = [t.get('country_code') for t in campaign.get('targeting', [])]
            
            if not get_user_confirmation("添加目标国家", {
                "Campaign ID": args.campaign_id,
                "当前国家": ', '.join(current) if current else '无',
                "新增国家": ', '.join(countries)
            }):
                return
            
            result = manager.add_countries(args.campaign_id, countries)
            print(f"✅ 国家已添加: {json.dumps(result, indent=2)}")
        
        elif args.targeting_cmd == 'remove':
            countries = [c.strip() for c in args.countries.split(',')]
            campaign = manager.get_campaign(args.campaign_id)
            current = [t.get('country_code') for t in campaign.get('targeting', [])]
            
            if not get_user_confirmation("移除目标国家", {
                "Campaign ID": args.campaign_id,
                "当前国家": ', '.join(current) if current else '无',
                "移除国家": ', '.join(countries)
            }):
                return
            
            result = manager.remove_countries(args.campaign_id, countries)
            print(f"✅ 国家已移除: {json.dumps(result, indent=2)}")
        
        elif args.targeting_cmd == 'set':
            countries = [c.strip() for c in args.countries.split(',')]
            campaign = manager.get_campaign(args.campaign_id)
            current = [t.get('country_code') for t in campaign.get('targeting', [])]
            
            if not get_user_confirmation("设置目标国家（替换）", {
                "Campaign ID": args.campaign_id,
                "原国家": ', '.join(current) if current else '无',
                "新国家": ', '.join(countries)
            }):
                return
            
            result = manager.set_countries(args.campaign_id, countries)
            print(f"✅ 国家已设置: {json.dumps(result, indent=2)}")


def handle_creative_command(manager: ApplovinCampaignManager, args):
    """处理素材组命令"""
    
    if args.creative_cmd == 'list':
        if args.campaign_id:
            result = manager.get_creative_sets_by_campaign(args.campaign_id)
            print(f"Campaign {args.campaign_id} 的素材组:")
            print(json.dumps(result, indent=2))
        else:
            sets = manager.list_creative_sets(page=args.page, size=args.size)
            print(f"找到 {len(sets)} 个素材组:")
            for s in sets:
                print(f"  • ID: {s.get('id')}, 名称: {s.get('name')}, 状态: {s.get('status')}")
    
    elif args.creative_cmd == 'get':
        creative = manager.get_creative_set(args.creative_set_id)
        if creative:
            print(json.dumps(creative, indent=2))
        else:
            print(f"找不到素材组 {args.creative_set_id}")
    
    elif args.creative_cmd == 'create':
        assets = json.loads(args.assets)
        countries = args.countries.split(',') if args.countries else None
        languages = args.languages.split(',') if args.languages else None
        
        if not get_user_confirmation("创建素材组", {
            "名称": args.name,
            "Campaign ID": args.campaign_id,
            "资源数": len(assets),
            "国家": countries or "全部",
            "语言": languages or "全部",
            "状态": args.status
        }):
            return
        
        result = manager.create_creative_set(
            name=args.name,
            campaign_id=args.campaign_id,
            assets=assets,
            countries=countries,
            languages=languages,
            status=args.status
        )
        print(f"✅ 素材组创建成功: {json.dumps(result, indent=2)}")
    
    elif args.creative_cmd == 'update':
        updates = {}
        if args.name:
            updates['name'] = args.name
        if args.assets:
            updates['assets'] = json.loads(args.assets)
        if args.status:
            updates['status'] = args.status
        
        if not get_user_confirmation("更新素材组", {
            "素材组 ID": args.creative_set_id,
            "更新内容": updates
        }):
            return
        
        result = manager.update_creative_set(args.creative_set_id, **updates)
        print(f"✅ 素材组已更新: {json.dumps(result, indent=2)}")
    
    elif args.creative_cmd == 'clone':
        if not get_user_confirmation("克隆素材组", {
            "源素材组 ID": args.creative_set_id,
            "目标 Campaign ID": args.target_campaign_id,
            "新状态": args.status
        }):
            return
        
        result = manager.clone_creative_set(
            args.creative_set_id,
            args.target_campaign_id,
            args.status
        )
        print(f"✅ 素材组已克隆: {json.dumps(result, indent=2)}")
    
    elif args.creative_cmd == 'enable':
        if not get_user_confirmation("启用素材组", {
            "素材组 ID": args.creative_set_id
        }):
            return
        
        result = manager.enable_creative_set(args.creative_set_id)
        print(f"✅ 素材组已启用: {json.dumps(result, indent=2)}")
    
    elif args.creative_cmd == 'disable':
        if not get_user_confirmation("禁用素材组", {
            "素材组 ID": args.creative_set_id
        }):
            return
        
        result = manager.disable_creative_set(args.creative_set_id)
        print(f"✅ 素材组已禁用: {json.dumps(result, indent=2)}")


def handle_asset_command(manager: ApplovinCampaignManager, args):
    """处理资源命令"""
    
    if args.asset_cmd == 'list':
        assets = manager.list_assets(
            page=args.page,
            size=args.size,
            resource_type=args.type
        )
        print(f"找到 {len(assets)} 个资源:")
        for a in assets:
            print(f"  • ID: {a.get('id')}, 名称: {a.get('name')}, "
                  f"类型: {a.get('asset_type')}, 状态: {a.get('status')}")
    
    elif args.asset_cmd == 'upload':
        if not get_user_confirmation("上传资源", {
            "文件数": len(args.files),
            "文件": args.files
        }):
            return
        
        result = manager.upload_assets(args.files)
        print(f"✅ 资源上传请求已提交: {json.dumps(result, indent=2)}")
        print(f"   请使用 upload-result --upload-id {result.get('upload_id')} 查询结果")
    
    elif args.asset_cmd == 'upload-result':
        result = manager.get_upload_result(args.upload_id)
        print(json.dumps(result, indent=2))
    
    elif args.asset_cmd == 'upload-from-dap':
        # 调用 upload_from_dap.py 脚本
        import subprocess
        
        cmd = [
            "python3", 
            os.path.join(os.path.dirname(__file__), "upload_from_dap.py"),
            "--game-id", str(args.game_id),
            "--type", args.type,
            "--start-date", args.start_date,
            "--end-date", args.end_date,
            "--page-size", str(args.page_size),
            "--local-dir", args.local_dir
        ]
        
        if args.language:
            cmd.extend(["--language", args.language])
        if args.ratio:
            cmd.extend(["--ratio", args.ratio])
        if args.material_class:
            cmd.extend(["--material-class", args.material_class])
        if args.skip_confirm:
            cmd.append("--skip-confirm")
        
        print(f"执行命令: {' '.join(cmd)}")
        subprocess.run(cmd)


if __name__ == "__main__":
    main()