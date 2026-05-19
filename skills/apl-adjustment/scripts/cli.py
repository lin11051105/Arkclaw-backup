#!/usr/bin/env python3
"""
Applovin Campaign Manager CLI

操作 Applovin Axon Campaign Management API
⚠️ 所有修改操作执行前需要用户确认！
"""

import argparse
import json
import os
import sys

from applovin_manager import ApplovinCampaignManager


def get_user_confirmation(operation_name: str, campaign_info: dict, 
                         extra_details: dict = None) -> bool:
    """获取用户确认（交互式）"""
    print("\n" + "=" * 60)
    print("⚠️  即将执行广告操作，请确认")
    print("=" * 60)
    print()
    print(f"📌 操作类型: {operation_name}")
    
    if campaign_info:
        print(f"📌 Campaign ID: {campaign_info.get('id')}")
        print(f"📌 Campaign 名称: {campaign_info.get('name', 'Unknown')}")
        print(f"📌 当前状态: {campaign_info.get('status', 'Unknown')}")
        print(f"📌 平台: {campaign_info.get('platform', 'Unknown')}")
        
        budget = campaign_info.get('budget', {})
        if budget and 'amount' in budget:
            print(f"📌 当前预算: ${budget['amount']:,.2f}")
        
        goal = campaign_info.get('goal', {})
        if goal and 'cpi' in goal:
            print(f"📌 当前 CPI 目标: ${goal['cpi']:.2f}")
    
    if extra_details:
        print()
        print("📋 变更详情:")
        for key, value in extra_details.items():
            print(f"   • {key}: {value}")
    
    print()
    print("=" * 60)
    print("请确认是否执行？")
    print('  ✅ 确认执行: 输入 "可以" / "确认" / "yes" / "ok"')
    print('  ❌ 取消操作: 输入其他任何内容')
    print("=" * 60)
    print()
    
    try:
        user_input = input("您的选择: ").strip().lower()
    except KeyboardInterrupt:
        print("\n❌ 操作已取消（用户中断）")
        return False
    
    confirm_keywords = ['可以', '确认', 'yes', 'ok', 'y', '是', '执行', '同意']
    
    if any(kw in user_input for kw in confirm_keywords):
        print("✅ 用户已确认，执行操作...")
        return True
    else:
        print("❌ 操作已取消")
        return False


def format_campaign(campaign: dict) -> str:
    """格式化 Campaign 信息"""
    lines = []
    lines.append(f"  ID: {campaign.get('id')}")
    lines.append(f"  名称: {campaign.get('name')}")
    lines.append(f"  状态: {campaign.get('status')}")
    lines.append(f"  平台: {campaign.get('platform')}")
    
    budget = campaign.get('budget', {})
    if budget:
        lines.append(f"  预算: ${budget.get('amount', 0):,.2f}")
    
    goal = campaign.get('goal', {})
    if goal and 'cpi' in goal:
        lines.append(f"  CPI 目标: ${goal['cpi']:.2f}")
    
    # 竞价策略
    bidding = campaign.get('bidding_strategy', '')
    if bidding:
        strategy_names = {
            'target_goal_with_cpi_billing': '目标 CPI 竞价',
            'auto_bidding_with_cpm_billing': '自动 CPM 竞价',
            'maximize_results_with_cpm_billing': '最大化结果 CPM 竞价'
        }
        lines.append(f"  竞价策略: {strategy_names.get(bidding, bidding)}")
    
    # 定向国家
    targeting = campaign.get('targeting', [])
    if targeting:
        countries = [t.get('country_code', '') for t in targeting]
        lines.append(f"  目标国家: {', '.join(countries)[:50]}...")
    
    lines.append(f"  开始日期: {campaign.get('start_date')}")
    lines.append(f"  结束日期: {campaign.get('end_date', 'N/A')}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Applovin Campaign Manager - 操作前需要确认",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
⚠️  安全提示：所有修改操作（暂停、恢复、调整预算、调整 CPI、修改国家、
    修改竞价策略、启用/禁用素材组）执行前需要用户确认！

只读操作（无需确认）:
  list                    列出所有 Campaigns
  get                     获取 Campaign 详情
  targeting               获取 Campaign 定向国家
  creatives               获取 Campaign 素材组

修改操作（需要确认）:
  pause                   暂停 Campaign
  resume                  恢复 Campaign
  update-budget           修改预算
  update-goal             修改 CPI 目标
  update-bidding          修改竞价策略
  add-countries           添加目标国家
  remove-countries        移除目标国家
  set-countries           设置目标国家（替换）
  enable-creative         启用素材组
  disable-creative        禁用素材组

示例:
  # 只读
  python3 cli.py list
  python3 cli.py get --campaign-id 12345
  python3 cli.py targeting --campaign-id 12345
  python3 cli.py creatives --campaign-id 12345

  # 修改（会提示确认）
  python3 cli.py pause --campaign-id 12345
  python3 cli.py update-budget --campaign-id 12345 --budget 5000
  python3 cli.py update-goal --campaign-id 12345 --cpi 2.5
  python3 cli.py update-bidding --campaign-id 12345 --strategy target_goal_with_cpi_billing
  python3 cli.py add-countries --campaign-id 12345 --countries US,JP,DE
  python3 cli.py remove-countries --campaign-id 12345 --countries FR,IT
  python3 cli.py enable-creative --creative-set-id 67890
        """
    )
    
    parser.add_argument("command", choices=[
        "list", "get", "pause", "resume", "update-budget", 
        "update-goal", "update-bidding", "targeting", 
        "add-countries", "remove-countries", "set-countries",
        "creatives", "enable-creative", "disable-creative"
    ], help="要执行的命令")
    
    parser.add_argument("--campaign-id", type=int, help="Campaign ID")
    parser.add_argument("--creative-set-id", type=int, help="素材组 ID")
    parser.add_argument("--budget", type=float, help="新预算金额")
    parser.add_argument("--cpi", type=float, help="CPI 目标")
    parser.add_argument("--strategy", type=str, help="竞价策略")
    parser.add_argument("--countries", type=str, help="国家代码，逗号分隔 (如: US,JP,DE)")
    parser.add_argument("--page", type=int, default=1, help="页码（默认 1）")
    parser.add_argument("--size", type=int, default=100, help="每页数量（默认 100）")
    
    args = parser.parse_args()
    
    # 获取凭证
    api_key = os.environ.get("APPLOVIN_API_KEY")
    account_id = os.environ.get("APPLOVIN_ACCOUNT_ID")
    
    if not api_key or not account_id:
        print("错误：未设置环境变量 APPLOVIN_API_KEY 或 APPLOVIN_ACCOUNT_ID")
        print("\n请设置环境变量：")
        print("  export APPLOVIN_API_KEY=your_api_key")
        print("  export APPLOVIN_ACCOUNT_ID=your_account_id")
        sys.exit(1)
    
    # 初始化管理器
    manager = ApplovinCampaignManager(api_key, account_id)
    
    # 执行命令
    if args.command == "list":
        print("正在获取 Campaign 列表...\n")
        campaigns = manager.list_campaigns(page=args.page, size=args.size)
        
        if not campaigns:
            print("没有找到 Campaigns")
            return
        
        print(f"找到 {len(campaigns)} 个 Campaigns:\n")
        for i, campaign in enumerate(campaigns, 1):
            print(f"[{i}] {campaign.get('name', 'Unknown')}")
            print(format_campaign(campaign))
    
    elif args.command == "get":
        if not args.campaign_id:
            print("错误：--campaign-id 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        print(format_campaign(campaign))
    
    elif args.command == "targeting":
        if not args.campaign_id:
            print("错误：--campaign-id 是必需的")
            sys.exit(1)
        
        targeting = manager.get_targeting(args.campaign_id)
        print(f"Campaign {args.campaign_id} 的定向国家:\n")
        for t in targeting:
            country = t.get('country_code', 'Unknown')
            regions = t.get('region_codes', [])
            if regions:
                print(f"  • {country} (地区: {', '.join(regions)})")
            else:
                print(f"  • {country}")
    
    elif args.command == "creatives":
        if not args.campaign_id:
            print("错误：--campaign-id 是必需的")
            sys.exit(1)
        
        creatives = manager.get_creative_sets_by_campaign(args.campaign_id)
        
        if not creatives or creatives.get('creative_set_count', 0) == 0:
            print(f"Campaign {args.campaign_id} 没有素材组")
            return
        
        print(f"Campaign {args.campaign_id} 的素材组:\n")
        print(f"素材组总数: {creatives.get('creative_set_count', 0)}\n")
        
        for campaign_id, sets in creatives.get('campaigns', {}).items():
            print(f"Campaign {campaign_id}:")
            for cs in sets:
                print(f"  • ID: {cs.get('id')}")
                print(f"    名称: {cs.get('name', 'Unknown')}")
                print(f"    状态: {cs.get('status', 'Unknown')}")
                print(f"    版本: {cs.get('version', 'Unknown')}")
                print()
    
    elif args.command == "pause":
        if not args.campaign_id:
            print("错误：--campaign-id 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        confirmed = get_user_confirmation("暂停 Campaign", campaign, {"操作后状态": "PAUSED"})
        if not confirmed:
            return
        
        result = manager.pause_campaign(args.campaign_id)
        print(f"✅ Campaign {args.campaign_id} 已暂停")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "resume":
        if not args.campaign_id:
            print("错误：--campaign-id 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        confirmed = get_user_confirmation("恢复 Campaign", campaign, {"操作后状态": "LIVE"})
        if not confirmed:
            return
        
        result = manager.resume_campaign(args.campaign_id)
        print(f"✅ Campaign {args.campaign_id} 已恢复")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "update-budget":
        if not args.campaign_id or args.budget is None:
            print("错误：--campaign-id 和 --budget 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        old_budget = campaign.get('budget', {}).get('amount', 0)
        confirmed = get_user_confirmation("修改 Campaign 预算", campaign, {
            "原预算": f"${old_budget:,.2f}",
            "新预算": f"${args.budget:,.2f}",
            "变化": f"${args.budget - old_budget:,.2f}"
        })
        if not confirmed:
            return
        
        result = manager.update_budget(args.campaign_id, args.budget)
        print(f"✅ Campaign {args.campaign_id} 预算已更新")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "update-goal":
        if not args.campaign_id or args.cpi is None:
            print("错误：--campaign-id 和 --cpi 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        old_cpi = campaign.get('goal', {}).get('cpi', 0)
        confirmed = get_user_confirmation("修改 CPI 目标", campaign, {
            "原 CPI": f"${old_cpi:.2f}",
            "新 CPI": f"${args.cpi:.2f}",
            "变化": f"${args.cpi - old_cpi:.2f}"
        })
        if not confirmed:
            return
        
        result = manager.update_cpi_goal(args.campaign_id, args.cpi)
        print(f"✅ Campaign {args.campaign_id} CPI 目标已更新")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "update-bidding":
        if not args.campaign_id or not args.strategy:
            print("错误：--campaign-id 和 --strategy 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        strategy_names = {
            'target_goal_with_cpi_billing': '目标 CPI 竞价',
            'auto_bidding_with_cpm_billing': '自动 CPM 竞价',
            'maximize_results_with_cpm_billing': '最大化结果 CPM 竞价'
        }
        
        current_strategy = campaign.get('bidding_strategy', 'Unknown')
        confirmed = get_user_confirmation("修改竞价策略", campaign, {
            "当前策略": strategy_names.get(current_strategy, current_strategy),
            "新策略": strategy_names.get(args.strategy, args.strategy)
        })
        if not confirmed:
            return
        
        result = manager.update_bidding_strategy(args.campaign_id, args.strategy)
        print(f"✅ Campaign {args.campaign_id} 竞价策略已更新")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "add-countries":
        if not args.campaign_id or not args.countries:
            print("错误：--campaign-id 和 --countries 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        country_list = [c.strip() for c in args.countries.split(',')]
        current_countries = [t.get('country_code') for t in campaign.get('targeting', [])]
        
        confirmed = get_user_confirmation("添加目标国家", campaign, {
            "当前国家": ', '.join(current_countries) if current_countries else '无',
            "新增国家": ', '.join(country_list),
            "操作后国家数": len(current_countries) + len(country_list)
        })
        if not confirmed:
            return
        
        result = manager.add_countries(args.campaign_id, country_list)
        print(f"✅ Campaign {args.campaign_id} 国家已添加")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "remove-countries":
        if not args.campaign_id or not args.countries:
            print("错误：--campaign-id 和 --countries 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        country_list = [c.strip() for c in args.countries.split(',')]
        current_countries = [t.get('country_code') for t in campaign.get('targeting', [])]
        
        confirmed = get_user_confirmation("移除目标国家", campaign, {
            "当前国家": ', '.join(current_countries) if current_countries else '无',
            "移除国家": ', '.join(country_list),
            "操作后国家数": len(current_countries) - len(country_list)
        })
        if not confirmed:
            return
        
        result = manager.remove_countries(args.campaign_id, country_list)
        print(f"✅ Campaign {args.campaign_id} 国家已移除")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "set-countries":
        if not args.campaign_id or not args.countries:
            print("错误：--campaign-id 和 --countries 是必需的")
            sys.exit(1)
        
        campaign = manager.get_campaign(args.campaign_id)
        if not campaign:
            print(f"错误：找不到 Campaign ID {args.campaign_id}")
            sys.exit(1)
        
        country_list = [c.strip() for c in args.countries.split(',')]
        current_countries = [t.get('country_code') for t in campaign.get('targeting', [])]
        
        confirmed = get_user_confirmation("设置目标国家（替换）", campaign, {
            "原国家": ', '.join(current_countries) if current_countries else '无',
            "新国家": ', '.join(country_list),
        })
        if not confirmed:
            return
        
        result = manager.set_countries(args.campaign_id, country_list)
        print(f"✅ Campaign {args.campaign_id} 国家已设置")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "enable-creative":
        if not args.creative_set_id:
            print("错误：--creative-set-id 是必需的")
            sys.exit(1)
        
        confirmed = get_user_confirmation("启用素材组", None, {
            "素材组 ID": args.creative_set_id,
            "操作后状态": "LIVE"
        })
        if not confirmed:
            return
        
        result = manager.enable_creative_set(args.creative_set_id)
        print(f"✅ 素材组 {args.creative_set_id} 已启用")
        print(f"   响应: {json.dumps(result, indent=2)}")
    
    elif args.command == "disable-creative":
        if not args.creative_set_id:
            print("错误：--creative-set-id 是必需的")
            sys.exit(1)
        
        confirmed = get_user_confirmation("禁用素材组", None, {
            "素材组 ID": args.creative_set_id,
            "操作后状态": "PAUSED"
        })
        if not confirmed:
            return
        
        result = manager.disable_creative_set(args.creative_set_id)
        print(f"✅ 素材组 {args.creative_set_id} 已禁用")
        print(f"   响应: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
