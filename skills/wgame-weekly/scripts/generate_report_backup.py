#!/usr/bin/env python3
"""
Wgame 周会数据报告生成脚本
自动从 DAP 获取数据并生成 Markdown 报告

重要规则：
1. 必须使用 DAP 自定义报表 #16621
2. 分国家/分渠道数据只查询上周（前一周），不是前两周之和
3. 不要包含总充值流水和DAU
4. 不要包含总结与建议部分
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional


# KPI 指标配置
KPI_CONFIG = {
    "overall_roi_7": 6.8,  # 上上周整体 ROI_7
    "overall_actual_roi": 4.1,  # 上周整体 Actual_ROI
    "android_actual_roi": 5.4,  # Android Actual_ROI
    "ios_actual_roi": 3.6,  # iOS Actual_ROI
    "google_roi": 3.4,  # Google Actual_ROI
    "facebook_roi": 2.8,  # Facebook Actual_ROI
    "tiktok_roi": 4.0,  # Tiktok Actual_ROI
    "almedia_roi": 8.0,  # Almedia Actual_ROI
}


def calculate_date_ranges() -> Tuple[str, str, str, str, str, str]:
    """计算上周、上上周、上上上周的日期范围（UTC+0）"""
    today = datetime.utcnow()
    
    # 本周一（用于推算上周）
    this_monday = today - timedelta(days=today.weekday())
    
    # 上周（本周一往前推7天）
    last_monday = this_monday - timedelta(days=7)
    last_sunday = last_monday + timedelta(days=6)
    
    # 上上周（上周一往前推7天）
    week_before_monday = last_monday - timedelta(days=7)
    week_before_sunday = week_before_monday + timedelta(days=6)
    
    # 上上上周（上上周一往前推7天）
    two_weeks_before_monday = week_before_monday - timedelta(days=7)
    two_weeks_before_sunday = week_before_monday + timedelta(days=6)
    
    return (
        last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d"),
        week_before_monday.strftime("%Y-%m-%d"), week_before_sunday.strftime("%Y-%m-%d"),
        two_weeks_before_monday.strftime("%Y-%m-%d"), two_weeks_before_sunday.strftime("%Y-%m-%d")
    )


def query_dap_data(report_id: int, start_date: str, end_date: str, table: str, platform: str = None) -> Optional[Dict]:
    """查询 DAP 数据 - 使用 atlas-skillhub"""
    params = [
        f"report_id={report_id}",
        f"start_date={start_date}",
        f"end_date={end_date}",
        "tz=0",
        f"table={table}"
    ]
    if platform:
        params.append(f"filter_platform={platform}")
    
    cmd = [
        "atlas-skillhub", "gateway", "call-tool",
        "--service", "dap",
        "--tool", "get_custom_report"
    ] + params
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, shell=False)
        if result.returncode == 0:
            response = json.loads(result.stdout)
            if "content" in response and len(response["content"]) > 0:
                text_content = response["content"][0].get("text", "")
                if text_content:
                    return json.loads(text_content)
            return response
        else:
            print(f"Error querying DAP: {result.stderr}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Exception querying DAP: {e}", file=sys.stderr)
        return None


def parse_dap_table(data: Dict) -> Tuple[List[str], List[List]]:
    """解析 DAP 返回的表格数据
    返回: (columns, rows)
    """
    if not data or 'tables' not in data or not data['tables']:
        return [], []
    
    table = data['tables'][0]
    columns = [col['name'] for col in table.get('columns', [])]
    rows = table.get('data', [])
    
    return columns, rows


def format_currency(value) -> str:
    """格式化货币"""
    if value is None or value == 0:
        return "$0"
    return f"${float(value):,.0f}"


def format_number(value) -> str:
    """格式化数字"""
    if value is None:
        return "0"
    return f"{int(float(value)):,}"


def format_percent(value) -> str:
    """格式化百分比"""
    if value is None:
        return "0.00%"
    return f"{float(value):.2f}%"


def calculate_change(current, previous) -> Tuple[float, float, str]:
    """计算变化值和变化百分比"""
    if previous is None or previous == 0 or current is None:
        return current or 0, 0, "↑"
    
    current_f = float(current)
    previous_f = float(previous)
    change_abs = current_f - previous_f
    change_pct = (change_abs / abs(previous_f)) * 100 if previous_f != 0 else 0
    direction = "↑" if change_abs >= 0 else "↓"
    
    return change_abs, change_pct, direction


def get_column_index(columns: List[str], name: str) -> int:
    """获取列索引"""
    try:
        return columns.index(name)
    except ValueError:
        return -1


def get_value(row: List, columns: List[str], col_name: str, default=0):
    """从行中获取指定列的值"""
    idx = get_column_index(columns, col_name)
    if idx >= 0 and idx < len(row):
        val = row[idx]
        return val if val is not None else default
    return default


def aggregate_store_data(columns: List[str], rows: List[List]) -> Dict:
    """聚合 store 表数据（按平台分组后汇总）"""
    total_cost = 0
    total_install = 0
    
    android_cost = 0
    android_install = 0
    android_actual_roi = 0
    android_retention_1 = 0
    
    ios_cost = 0
    ios_install = 0
    ios_actual_roi = 0
    ios_retention_1 = 0
    
    pc_cost = 0
    pc_install = 0
    pc_actual_roi = 0
    pc_retention_1 = 0
    
    for row in rows:
        platform = get_value(row, columns, '操作系统', '')
        cost = get_value(row, columns, '消耗数', 0)
        install = get_value(row, columns, '总新增账号数', 0)
        actual_roi = get_value(row, columns, 'Actual_ROI', 0)
        retention_1 = get_value(row, columns, '账号次留率', 0)
        
        total_cost += cost
        total_install += install
        
        if platform == 'Android':
            android_cost = cost
            android_install = install
            android_actual_roi = actual_roi
            android_retention_1 = retention_1
        elif platform == 'iOS':
            ios_cost = cost
            ios_install = install
            ios_actual_roi = actual_roi
            ios_retention_1 = retention_1
        elif platform == 'PC':
            pc_cost = cost
            pc_install = install
            pc_actual_roi = actual_roi
            pc_retention_1 = retention_1
    
    cpi = total_cost / total_install if total_install > 0 else 0
    
    # 计算加权平均 Actual_ROI
    total_actual_roi = (android_cost * android_actual_roi + ios_cost * ios_actual_roi + pc_cost * pc_actual_roi) / total_cost if total_cost > 0 else 0
    
    return {
        'cost': total_cost,
        'install': total_install,
        'cpi': cpi,
        'actual_roi': total_actual_roi,
        'retention_1': (android_install * android_retention_1 + ios_install * ios_retention_1 + pc_install * pc_retention_1) / total_install if total_install > 0 else 0,
        'android_cost': android_cost,
        'android_install': android_install,
        'android_actual_roi': android_actual_roi,
        'android_retention_1': android_retention_1,
        'ios_cost': ios_cost,
        'ios_install': ios_install,
        'ios_actual_roi': ios_actual_roi,
        'ios_retention_1': ios_retention_1,
        'pc_cost': pc_cost,
        'pc_install': pc_install,
        'pc_actual_roi': pc_actual_roi,
        'pc_retention_1': pc_retention_1,
    }


def process_country_data(columns: List[str], rows: List[List]) -> List[Dict]:
    """处理国家数据"""
    result = []
    for row in rows:
        result.append({
            'country': get_value(row, columns, '国家', ''),
            'cost': get_value(row, columns, '消耗数', 0),
            'install': get_value(row, columns, '总新增账号数', 0),
            'cpi': get_value(row, columns, '总新增成本', 0),
            'actual_roi': get_value(row, columns, 'Actual_ROI', 0),
            'retention_1': get_value(row, columns, '账号次留率', 0),
        })
    return result


def process_channel_data(columns: List[str], rows: List[List]) -> List[Dict]:
    """处理渠道数据"""
    result = []
    for row in