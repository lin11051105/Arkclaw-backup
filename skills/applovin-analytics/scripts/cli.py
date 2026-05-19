#!/usr/bin/env python3
"""
Applovin Analytics CLI
数据分析命令行工具
"""

import argparse
import json
import sys
import os
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from applovin_analytics import ApplovinAnalytics


def print_table(data: list, headers: list):
    """打印表格"""
    if not data:
        print("No data found.")
        return
    
    col_widths = {}
    for header in headers:
        col_widths[header] = len(header)
    
    for row in data:
        for header in headers:
            val = str(row.get(header, ""))
            col_widths[header] = max(col_widths[header], len(val))
    
    header_line = " | ".join(header.ljust(col_widths[header]) for header in headers)
    print(header_line)
    print("-" * len(header_line))
    
    for row in data:
        line = " | ".join(str(row.get(header, "")).ljust(col_widths[header]) for header in headers)
        print(line)


def cmd_query(args):
    """通用查询"""
    analytics = ApplovinAnalytics.from_env()
    
    filters = {}
    if args.platform:
        filters["platform"] = args.platform
    if args.country:
        filters["country"] = args.country
    if args.campaign_id:
        filters["campaign_id"] = args.campaign_id
    
    result = analytics.query(
        start=args.start,
        end=args.end,
        columns=args.columns,
        filters=filters if filters else None,
        sort={args.sort_by: args.sort_order} if args.sort_by else None,
        limit=args.limit
    )
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        data = analytics._extract_results(result)
        if data:
            headers = list(data[0].keys())[:8]
            print_table(data, headers)
            print(f"\nTotal: {len(data)} rows")


def cmd_campaigns(args):
    """查询 Campaign 数据"""
    analytics = ApplovinAnalytics.from_env()
    
    data = analytics.query_campaigns(
        start=args.start,
        end=args.end,
        columns=args.columns,
        platform=args.platform,
        campaign_id=args.campaign_id
    )
    
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        headers = ["campaign", "platform", "cost", "conversions", "roas_7d", "average_cpa"]
        headers = [h for h in headers if any(h in d for d in data)]
        print_table(data, headers if headers else list(data[0].keys())[:6] if data else [])
        print(f"\nTotal campaigns: {len(data)}")


def cmd_creatives(args):
    """查询素材组数据"""
    analytics = ApplovinAnalytics.from_env()
    
    data = analytics.query_creative_sets(
        start=args.start,
        end=args.end,
        columns=args.columns,
        campaign_id=args.campaign_id
    )
    
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        headers = ["creative_set", "campaign", "cost", "conversions", "roas_7d"]
        headers = [h for h in headers if any(h in d for d in data)]
        print_table(data, headers if headers else list(data[0].keys())[:6] if data else [])
        print(f"\nTotal creative sets: {len(data)}")


def cmd_countries(args):
    """查询分国家数据"""
    analytics = ApplovinAnalytics.from_env()
    
    data = analytics.query_by_country(
        start=args.start,
        end=args.end,
        columns=args.columns,
        campaign_id=args.campaign_id,
        platform=args.platform
    )
    
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        headers = ["campaign", "country", "cost", "conversions", "roas_7d"]
        headers = [h for h in headers if any(h in d for d in data)]
        print_table(data, headers if headers else list(data[0].keys())[:6] if data else [])
        print(f"\nTotal rows: {len(data)}")


def cmd_analyze(args):
    """分析数据（仅在用户询问时生成建议）"""
    analytics = ApplovinAnalytics.from_env()
    
    print("Fetching data...")
    
    data = analytics.query_campaigns(
        start=args.start,
        end=args.end,
        columns="full",
        platform=args.platform
    )
    
    if not data:
        print("No data found.")
        return
    
    # 执行多种分析
    analysis_results = {}
    
    if args.type == "all" or "roas" in args.type:
        print("\nAnalyzing ROAS...")
        analysis_results["low_roas"] = analytics.analyze(
            data, metric="roas_7d", threshold=args.roas_threshold, 
            operator="<", min_cost=args.min_cost
        )
    
    if args.type == "all" or "cpi" in args.type:
        print("\nAnalyzing CPI...")
        analysis_results["high_cpi"] = analytics.analyze(
            data, metric="average_cpa", threshold=args.cpi_threshold,
            operator=">", min_cost=args.min_cost
        )
    
    if args.type == "all" or "ir" in args.type:
        print("\nAnalyzing IR...")
        analysis_results["low_ir"] = analytics.analyze(
            data, metric="conversion_rate", threshold=args.ir_threshold,
            operator="<", min_cost=args.min_cost
        )
    
    if args.type == "all" or "cpp" in args.type:
        print("\nAnalyzing CPP...")
        analysis_results["high_cpp"] = analytics.analyze(
            data, metric="cpp_0d", threshold=args.cpp_threshold,
            operator=">", min_cost=args.min_cost
        )
    
    # 打印分析结果
    print("\n" + "=" * 60)
    print("ANALYSIS RESULTS")
    print("=" * 60)
    
    for analysis_type, items in analysis_results.items():
        print(f"\n{analysis_type}: {len(items)} items")
        for item in items[:5]:
            print(f"  - {item.get('campaign', 'N/A')}: {item['metric']}={item['value']:.4f}")
    
    # 如果用户要求生成建议
    if args.suggest:
        print("\n" + "=" * 60)
        print("SUGGESTIONS")
        print("=" * 60)
        
        suggestions = analytics.suggest(analysis_results)
        
        for suggestion in suggestions:
            print(f"\n{suggestion['name']} (ID: {suggestion['id']})")
            print(f"  Action: {suggestion['action']}")
            print(f"  Priority: {suggestion['priority']}")
            print(f"  Reason: {suggestion['reason']}")
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(suggestions, f, indent=2, ensure_ascii=False)
            print(f"\nSuggestions saved to: {args.output}")


def cmd_creative_analysis(args):
    """素材组4步分析"""
    import pickle
    analytics = ApplovinAnalytics.from_env()
    
    # 加载素材组日期 (支持 JSON 或 Pickle，或自动从 Management API 获取)
    set_dates = None
    if args.set_dates_file and os.path.exists(args.set_dates_file):
        if args.set_dates_file.endswith('.json'):
            with open(args.set_dates_file, 'r') as f:
                set_dates = json.load(f)
        elif args.set_dates_file.endswith('.pkl'):
            with open(args.set_dates_file, 'rb') as f:
                raw_data = pickle.load(f)
                set_dates = {k.strip(): v['date'] for k, v in raw_data.items()}
        else:
            try:
                with open(args.set_dates_file, 'r') as f:
                    set_dates = json.load(f)
            except:
                print(f"Warning: Could not load {args.set_dates_file}")
    
    print("=" * 100)
    print("CREATIVE SET ANALYSIS (4-Step Classification)")
    print("=" * 100)
    print(f"Campaign ID: {args.campaign_id}")
    print(f"Date Range: {args.start} to {args.end}")
    print(f"Volume Threshold: ${args.volume_threshold:,.2f}")
    print()
    
    # 执行分析
    result = analytics.analyze_creative_sets(
        campaign_id=args.campaign_id,
        start_date=args.start,
        end_date=args.end,
        volume_threshold=args.volume_threshold,
        set_dates=set_dates,
        today=datetime.now(),
        auto_fetch_dates=(set_dates is None)
    )
    
    if 'error' in result:
        print(f"Error: {result['error']}")
        return
    
    # 打印结果
    print(f"Campaign: {result['campaign_name']}")
    print(f"Campaign D28 ROAS: {result['campaign_roas_28d']:.2%}")
    print(f"Total Sets with Consumption: {result['total_sets']}")
    print()
    
    # 按消耗降序显示所有有消耗的素材组
    print("=" * 100)
    print("ALL CREATIVE SETS (with consumption, sorted by cost descending)")
    print("=" * 100)
    print()
    
    # 表头
    print(f"{'Rank':<6} {'Creative Set':<50} {'Status':<10} {'Created':<12} {'Cost':>12} {'IR':>8} {'CPI':>10} {'D0 ROAS':>10} {'D28 ROAS':>10} {'Category':<10} {'Action':<15}")
    print("-" * 180)
    
    all_sets = result.get('all_sets', [])
    pause_sets = []
    observe_sets = []
    normal_sets = []
    
    for i, s in enumerate(all_sets, 1):
        # 获取状态（需要从 Management API 获取，这里简化处理）
        status = "LIVE"  # 默认状态
        
        # 格式化输出
        name = s['creative_set'][:48] if len(s['creative_set']) > 48 else s['creative_set']
        created = s.get('created_date', 'unknown')[:10]
        cost = s['cost_7d']
        ir = s.get('conversion_rate', 0) * 100  # 转换为百分比
        cpi = s.get('average_cpa', 0)
        d0_roas = s.get('roas_0d', 0) * 100  # 转换为百分比
        d28_roas = s['roas_28d'] * 100  # 转换为百分比
        category = s.get('category', 'N/A')
        action = s.get('action', 'N/A')
        
        print(f"{i:<6} {name:<50} {status:<10} {created:<12} ${cost:>10,.2f} {ir:>7.2f}% ${cpi:>9.2f} {d0_roas:>9.2f}% {d28_roas:>9.2f}% {category:<10} {action:<15}")
        
        # 分类收集
        if action == '暂停投放':
            pause_sets.append(s)
        elif action == '继续观察':
            observe_sets.append(s)
        else:
            normal_sets.append(s)
    
    print()
    
    # 显示建议暂停的素材组
    if pause_sets:
        print("=" * 100)
        print(f"SETS TO PAUSE ({len(pause_sets)} sets)")
        print("=" * 100)
        print()
        for i, s in enumerate(pause_sets, 1):
            print(f"{i}. {s['creative_set']}")
            print(f"   Category: {s.get('category', 'N/A')}")
            print(f"   Created: {s.get('created_date', 'unknown')}")
            print(f"   Cost: ${s['cost_7d']:,.2f}")
            print(f"   IR: {s.get('conversion_rate', 0)*100:.2f}%")
            print(f"   CPI: ${s.get('average_cpa', 0):.2f}")
            print(f"   D0 ROAS: {s.get('roas_0d', 0)*100:.2f}%")
            print(f"   D28 ROAS: {s['roas_28d']*100:.2f}%")
            print(f"   Label: {s.get('label', 'N/A')}")
            print(f"   Action: {s['action']}")
            print()
    
    # 询问是否执行操作
    if pause_sets:
        print("=" * 100)
        print("EXECUTE ACTIONS")
        print("=" * 100)
        print()
        print(f"Ready to pause {len(pause_sets)} creative sets listed above.")
        print()
        print('Type "yes" to execute, or anything else to skip:')
        
        try:
            user_input = input("\nYour choice: ").strip().lower()
        except KeyboardInterrupt:
            print("\n\nOperation cancelled.")
            return
        
        if user_input in ['yes', 'y', '确认', '执行']:
            print("\nExecuting pause operations...")
            # TODO: Call apl-adjustment skill to pause creative sets
            print("(This feature requires integration with apl-adjustment skill)")
            print("\nTo manually pause these sets, run:")
            print("  cd /root/.openclaw/workspace/skills/apl-adjustment")
            for s in pause_sets:
                print(f"  python3 scripts/cli_full.py creative-set pause --creative-set-id {s.get('creative_set_id', 'N/A')}")
        else:
            print("\nOperation skipped. No changes made.")
    
    # 保存结果
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {args.output}")


def cmd_bid_analysis(args):
    """整体出价分析"""
    import json
    analytics = ApplovinAnalytics.from_env()
    
    # 加载 potential 数据（如果提供）
    potential_data = None
    if args.potential_file and os.path.exists(args.potential_file):
        with open(args.potential_file, 'r') as f:
            potential_data = json.load(f)
    
    # 执行分析
    result = analytics.analyze_campaign_bid_overall(
        campaign_id=args.campaign_id,
        start_date=args.start,
        end_date=args.end,
        potential_data=potential_data
    )
    
    if 'error' in result:
        print(f"Error: {result['error']}")
        return
    
    # 打印结果
    print(f"\n{'='*160}")
    print(f"Campaign: {result.get('campaign_id', 'N/A')}")
    print(f"Analysis Period: {result['analysis_period']}")
    print(f"Daily Budget: ${result.get('daily_budget', 0):,.0f}")
    print(f"{'='*160}")
    print()
    
    # 打印表格
    print(f"{'日期':<15} {'Budget':>12} {'Potential':>12} {'花超比例':>12} {'Spend':>12} {'实际花费比例':>14} {'备注':<60}")
    print('-'*160)
    
    for r in result['daily_analysis']:
        print(f"{r['date']:<15} ${r['budget']:>10,.0f} ${r['potential']:>10,.0f} {r['potential_budget_ratio']:>10.1f}% ${r['spend']:>10,.2f} {r['spend_budget_ratio']:>12.1f}% {r['remark']:<60}")
    
    # 汇总行
    print('-'*160)
    s = result['summary']
    print(f"{s['date']:<15} ${s['budget']:>10,.0f} ${s['potential']:>10,.0f} {s['potential_budget_ratio']:>10.1f}% ${s['spend']:>10,.2f} {s['spend_budget_ratio']:>12.1f}% {s['remark']:<60}")
    
    print()
    print('='*160)
    print('结论（基于汇总数据）：')
    print(f"  - 平均花超比例: {s['potential_budget_ratio']:.1f}%")
    print(f"  - 平均实际花费比例: {s['spend_budget_ratio']:.1f}%")
    print(f"  - 结论: {s['remark']}")
    print('='*160)
    
    # 保存结果
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {args.output}")


def main():
    parser = argparse.ArgumentParser(
        description="Applovin Analytics - Reporting API CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Query command
    query_parser = subparsers.add_parser("query", help="Generic query")
    query_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    query_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    query_parser.add_argument("--columns", default="basic", help="Column set or list")
    query_parser.add_argument("--platform", help="Platform filter")
    query_parser.add_argument("--country", help="Country filter")
    query_parser.add_argument("--campaign-id", help="Campaign ID filter")
    query_parser.add_argument("--sort-by", help="Sort by column")
    query_parser.add_argument("--sort-order", default="DESC", choices=["ASC", "DESC"])
    query_parser.add_argument("--limit", type=int, help="Limit results")
    query_parser.add_argument("--json", action="store_true", help="Output as JSON")
    query_parser.set_defaults(func=cmd_query)
    
    # Campaigns command
    camp_parser = subparsers.add_parser("campaigns", help="Query campaign data")
    camp_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    camp_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    camp_parser.add_argument("--columns", default="full", help="Column set")
    camp_parser.add_argument("--platform", help="Platform filter")
    camp_parser.add_argument("--campaign-id", help="Campaign ID filter")
    camp_parser.add_argument("--json", action="store_true", help="Output as JSON")
    camp_parser.set_defaults(func=cmd_campaigns)
    
    # Creatives command
    creative_parser = subparsers.add_parser("creatives", help="Query creative set data")
    creative_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    creative_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    creative_parser.add_argument("--columns", default="creative", help="Column set")
    creative_parser.add_argument("--campaign-id", help="Campaign ID filter")
    creative_parser.add_argument("--json", action="store_true", help="Output as JSON")
    creative_parser.set_defaults(func=cmd_creatives)
    
    # Countries command
    country_parser = subparsers.add_parser("countries", help="Query data by country")
    country_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    country_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    country_parser.add_argument("--columns", default="country", help="Column set")
    country_parser.add_argument("--platform", help="Platform filter")
    country_parser.add_argument("--campaign-id", help="Campaign ID filter")
    country_parser.add_argument("--json", action="store_true", help="Output as JSON")
    country_parser.set_defaults(func=cmd_countries)
    
    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze data")
    analyze_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    analyze_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    analyze_parser.add_argument("--type", default="all", 
                               choices=["all", "roas", "cpi", "ir", "cpp"],
                               help="Analysis type")
    analyze_parser.add_argument("--platform", help="Platform filter")
    analyze_parser.add_argument("--roas-threshold", type=float, default=0.1)
    analyze_parser.add_argument("--cpi-threshold", type=float, default=5.0)
    analyze_parser.add_argument("--ir-threshold", type=float, default=0.01)
    analyze_parser.add_argument("--cpp-threshold", type=float, default=50.0)
    analyze_parser.add_argument("--min-cost", type=float, default=100.0)
    analyze_parser.add_argument("--suggest", action="store_true", 
                               help="Generate adjustment suggestions")
    analyze_parser.add_argument("--output", "-o", help="Output file")
    analyze_parser.set_defaults(func=cmd_analyze)
    
    # Creative analysis command
    creative_analysis_parser = subparsers.add_parser(
        "creative-analysis", 
        help="4-step creative set analysis with volume threshold"
    )
    creative_analysis_parser.add_argument("--campaign-id", required=True, help="Campaign ID")
    creative_analysis_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    creative_analysis_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    creative_analysis_parser.add_argument("--volume-threshold", type=float, default=1000,
                                           help="Volume threshold for A/B classification (default: 1000)")
    creative_analysis_parser.add_argument("--set-dates-file", help="JSON file with creative set dates")
    creative_analysis_parser.add_argument("--output", help="Output file for results")
    creative_analysis_parser.set_defaults(func=cmd_creative_analysis)
    
    # Bid analysis command (overall)
    bid_parser = subparsers.add_parser(
        "bid-analysis",
        help="Campaign bid analysis (overall) - analyzes bid efficiency based on budget, spend, and potential"
    )
    bid_parser.add_argument("--campaign-id", required=True, help="Campaign ID")
    bid_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    bid_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    bid_parser.add_argument("--potential-file", help="JSON file with potential data from email")
    bid_parser.add_argument("--output", help="Output file for results")
    bid_parser.set_defaults(func=cmd_bid_analysis)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()