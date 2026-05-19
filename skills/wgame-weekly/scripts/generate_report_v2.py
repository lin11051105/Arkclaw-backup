#!/usr/bin/env python3
"""
Wgame 周会数据报告生成脚本 V2
自动从 DAP 获取数据并生成 Markdown 报告
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# KPI 指标配置
KPI_CONFIG = {
    "overall_roi_7": 6.8,
    "overall_actual_roi": 4.1,
    "android_actual_roi": 5.4,
    "ios_actual_roi": 3.6,
    "google_roi": 3.4,
    "facebook_roi": 2.8,
    "tiktok_roi": 4.0,
    "almedia_roi": 8.0,
}


def calculate_date_ranges():
    """计算日期范围"""
    today = datetime.utcnow()
    this_monday = today - timedelta(days=today.weekday())
    
    last_monday = this_monday - timedelta(days=7)
    last_sunday = last_monday + timedelta(days=6)
    
    week_before_monday = last_monday - timedelta(days=7)
    week_before_sunday = week_before_monday + timedelta(days=6)
    
    two_weeks_before_monday = week_before_monday - timedelta(days=7)
    two_weeks_before_sunday = week_before_monday + timedelta(days=6)
    
    return (
        last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d"),
        week_before_monday.strftime("%Y-%m-%d"), week_before_sunday.strftime("%Y-%m-%d"),
        two_weeks_before_monday.strftime("%Y-%m-%d"), two_weeks_before_sunday.strftime("%Y-%m-%d")
    )


def query_dap(report_id, start_date, end_date, table, platform=None):
    """查询 DAP 数据"""
    params = [f"report_id={report_id}", f"start_date={start_date}", f"end_date={end_date}", "tz=0", f"table={table}"]
    if platform:
        params.append(f"filter_platform={platform}")
    
    cmd = ["atlas-skillhub", "gateway", "call-tool", "--service", "dap", "--tool", "get_custom_report"] + params
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            response = json.loads(result.stdout)
            if "content" in response and len(response["content"]) > 0:
                text = response["content"][0].get("text", "")
                if text:
                    return json.loads(text)
            return response
        return None
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


def parse_table(data):
    """解析表格数据"""
    if not data or 'tables' not in data or not data['tables']:
        return [], []
    table = data['tables'][0]
    columns = [col['name'] for col in table.get('columns', [])]
    rows = table.get('data', [])
    return columns, rows


def get_val(row, columns, name, default=0):
    """获取列值"""
    try:
        idx = columns.index(name)
        return row[idx] if idx < len(row) and row[idx] is not None else default
    except ValueError:
        return default


def aggregate_store(columns, rows):
    """聚合 store 数据"""
    total_cost = total_install = 0
    android = ios = pc = {'cost': 0, 'install': 0, 'actual_roi': 0, 'retention_1': 0}
    
    for row in rows:
        platform = get_val(row, columns, '操作系统', '')
        cost = get_val(row, columns, '消耗数', 0)
        install = get_val(row, columns, '总新增账号数', 0)
        actual_roi = get_val(row, columns, 'Actual_ROI', 0)
        retention_1 = get_val(row, columns, '账号次留率', 0)
        
        total_cost += cost
        total_install += install
        
        data = {'cost': cost, 'install': install, 'actual_roi': actual_roi, 'retention_1': retention_1}
        if platform == 'Android':
            android = data
        elif platform == 'iOS':
            ios = data
        elif platform == 'PC':
            pc = data
    
    cpi = total_cost / total_install if total_install > 0 else 0
    weighted_roi = (android['cost'] * android['actual_roi'] + ios['cost'] * ios['actual_roi'] + pc['cost'] * pc['actual_roi']) / total_cost if total_cost > 0 else 0
    weighted_retention = (android['install'] * android['retention_1'] + ios['install'] * ios['retention_1'] + pc['install'] * pc['retention_1']) / total_install if total_install > 0 else 0
    
    return {
        'cost': total_cost, 'install': total_install, 'cpi': cpi,
        'actual_roi': weighted_roi, 'retention_1': weighted_retention,
        'android': android, 'ios': ios, 'pc': pc
    }


def process_country(columns, rows):
    """处理国家数据"""
    result = []
    for row in rows:
        result.append({
            'country': get_val(row, columns, '国家', ''),
            'cost': get_val(row, columns, '消耗数', 0),
            'install': get_val(row, columns, '总新增账号数', 0),
            'cpi': get_val(row, columns, '总新增成本', 0),
            'actual_roi': get_val(row, columns, 'Actual_ROI', 0),
        })
    return sorted(result, key=lambda x: x['cost'], reverse=True)


def process_channel(columns, rows):
    """处理渠道数据"""
    result = []
    for row in rows:
        result.append({
            'channel': get_val(row, columns, '渠道', ''),
            'cost': get_val(row, columns, '消耗数', 0),
            'install': get_val(row, columns, '总新增账号数', 0),
            'cpi': get_val(row, columns, '总新增成本', 0),
            'actual_roi': get_val(row, columns, 'Actual_ROI', 0),
            'retention_1': get_val(row, columns, '账号次留率', 0),
            'roi_1': get_val(row, columns, 'ROI_1', 0),
        })
    return sorted(result, key=lambda x: x['cost'], reverse=True)


def format_currency(value):
    if value is None or value == 0:
        return "$0"
    return f"${float(value):,.0f}"


def format_number(value):
    if value is None:
        return "0"
    return f"{int(float(value)):,}"


def format_percent(value):
    if value is None:
        return "0.00%"
    return f"{float(value):.2f}%"


def calc_change(current, previous):
    if previous is None or previous == 0 or current is None:
        return current or 0, 0, "↑"
    change = current - previous
    pct = (change / abs(previous)) * 100 if previous != 0 else 0
    return change, pct, "↑" if change >= 0 else "↓"


def check_kpi(actual, target):
    """检查 KPI 是否达标"""
    if actual is None or target is None:
        return "N/A"
    return "✓ 达标" if actual >= target else "✗ 未达标"


def generate_report():
    """生成报告"""
    dates = calculate_date_ranges()
    last_start, last_end, wb_start, wb_end, twb_start, twb_end = dates
    
    print(f"正在查询数据...")
    print(f"上周: {last_start} ~ {last_end}")
    print(f"上上周: {wb_start} ~ {wb_end}")
    
    # 查询数据
    print("查询汇总数据...")
    lw_data = query_dap(16621, last_start, last_end, "store")
    wb_data = query_dap(16621, wb_start, wb_end, "store")
    twb_data = query_dap(16621, twb_start, twb_end, "store")
    
    print("查询分国家数据...")
    android_country_data = query_dap(16621, last_start, last_end, "country", "android")
    ios_country_data = query_dap(16621, last_start, last_end, "country", "ios")
    
    print("查询分渠道数据...")
    android_channel_data = query_dap(16621, last_start, last_end, "media_src", "android")
    
    # 解析数据
    lw_cols, lw_rows = parse_table(lw_data) if lw_data else ([], [])
    wb_cols, wb_rows = parse_table(wb_data) if wb_data else ([], [])
    twb_cols, twb_rows = parse_table(twb_data) if twb_data else ([], [])
    
    # 聚合数据
    lw_summary = aggregate_store(lw_cols, lw_rows) if lw_rows else {}
    wb_summary = aggregate_store(wb_cols, wb_rows) if wb_rows else {}
    twb_summary = aggregate_store(twb_cols, twb_rows) if twb_rows else {}
    
    # 处理国家数据
    android_country_cols, android_country_rows = parse_table(android_country_data) if android_country_data else ([], [])
    ios_country_cols, ios_country_rows = parse_table(ios_country_data) if ios_country_data else ([], [])
    
    android_countries = process_country(android_country_cols, android_country_rows) if android_country_rows else []