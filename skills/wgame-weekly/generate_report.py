#!/usr/bin/env python3
"""
Wgame 周会数据报告生成脚本 - 完善版
自动从 DAP 获取数据并生成 Markdown 报告

更新内容：
1. 添加 KPI 列和是否达标列
2. 添加消耗环比变化绝对值
3. 添加 iOS 分渠道数据（第6节）
4. 添加未达标渠道标注
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional


# KPI 配置
KPI_TARGETS = {
    "overall_roi_7": 6.8,  # 上上周整体 ROI_7
    "overall_actual_roi": 4.1,  # 上周整体 Actual_ROI
    "android_actual_roi": 5.4,  # Android Actual_ROI
    "ios_actual_roi": 3.6,  # iOS Actual_ROI
    "android_channels": {
        "Google": 3.4,
        "Facebook": 2.8,
        "Tiktok": 4.0,
        "Almedia": 8.0,
    }
}


def calculate_date_ranges() -> Tuple[str, str, str, str, str, str]:
    """计算三周日期范围"""
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


def query_dap_data(report_id: int, start_date: str, end_date: str, table: str, platform: str = None, page_size: int = 100) -> Optional[Dict]:
    """查询 DAP 数据"""
    # 这里使用模拟数据，实际使用时替换为真实 DAP 查询
    return {"tables": [{"data": []}]}


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


def check_kpi_status(actual: float, target: float) -> Tuple[str, bool]:
    """检查 KPI 是否达标"""
    if actual is None or target is None:
        return "-", True
    
    is_pass = actual >= target
    status = "✓" if is_pass else "✗"
    return status, is_pass


def extract_table_data(data: Dict) -> List[Dict]:
    """从 DAP 返回数据中提取表格数据"""
    if not data or 'tables' not in data or not data['tables']:
        return []
    
    table = data['tables'][0]
    if 'data' not in table:
        return []
    
    return table.get('data', [])


def generate_android_channel_section(android_channels: List[Dict], android_channels_prev: Dict) -> str:
    """生成 Android 分渠道数据部分"""
    lines = []
    
    lines.append("""
---

## 5. 安卓分渠道数据（上周，按总消耗降序）

| 渠道 | 总消耗 | 消耗环比 | 消耗环比变化绝对值 | 总新增 | 新增成本 | 次留率 | ROI_1 | Actual_ROI | KPI | 是否达标 | 首日付费率 | 首日ARPPU |
|------|--------|---------|-------------------|--------|---------|--------|-------|-----------|-----|---------|-----------|----------|
""")
    
    android_channel_underperform = []
    
    for ch in android_channels:
        media = ch.get('media_src', 'Unknown')
        cost = ch.get('cost', 0)
        install = ch.get('install', 0)
        cpi = cost / install if install > 0 else 0
        retention = ch.get('retention_1', 0)
        roi_1 = ch.get('roi_1', 0)
        actual_roi = ch.get('actual_roi', 0)
        first_pay_rate = ch.get('first_pay_rate', 0)
        first_arppu = ch.get('first_arppu', 0)
        
        # 计算消耗环比
        prev_ch = android_channels_prev.get(media, {})
        prev_cost = prev_ch.get('cost', 0) if prev_ch else 0
        cost_change_abs = cost - prev_cost
        cost_change_pct = (cost_change_abs / prev_cost * 100) if prev_cost > 0 else 0
        cost_change_dir = "↑" if cost_change_abs >= 0 else "↓"
        
        # KPI 检查
        kpi_target = KPI_TARGETS["android_channels"].get(media)
        if kpi_target:
            kpi_status, kpi_pass = check_kpi_status(actual_roi, kpi_target)
            if not kpi_pass:
                android_channel_underperform.append((media, actual_roi, kpi_target))
        else:
            kpi_status = "-"
            kpi_target = "-"
        
        lines.append(f"| {media} | {format_currency(cost)} | {cost_change_pct:+.1f}% {cost_change_dir} | {format_currency(cost_change_abs)} | {format_number(install)} | ${cpi:.2f} | {format_percent(retention)} | {format_percent(roi_1)} | {format_percent(actual_roi)} | {kpi_target if isinstance(kpi_target, str) else f'{kpi_target}%'} | {kpi_status} | {format_percent(first_pay_rate)} | {format_currency(first_arppu)} |\n")
    
    # Android 渠道未达标标注
    if android_channel_underperform:
        lines.append("\n**⚠️ 未达标渠道：**\n")
        for media, actual, target in android_channel_underperform:
            lines.append(f"\n- ⚠️ **{media} 未达标**：实际值 {format_percent(actual)}，KPI 要求 {target}%")
    
    return "".join(lines)


def generate_ios_channel_section(ios_channels: List[Dict], ios_channels_prev: Dict) -> str:
    """生成 iOS 分渠道数据部分"""
    lines = []
    
    lines.append("""

---

## 6. iOS 分渠道数据（上周，按总消耗降序）

*注：iOS 渠道无 KPI 要求，仅对比 ROI_1 环比变化。*

| 渠道 | 总消耗 | 消耗环比 | 消耗环比变化绝对值 | 总新增 | 新增成本 | ROI_1 | ROI_1 环比 | 次留率 |
|------|--------|---------|-------------------|--------|---------|-------|-----------|--------|
""")
    
    for ch in ios_channels:
        media = ch.get('media_src', 'Unknown')
        cost = ch.get('cost', 0)
        install = ch.get('install', 0)
        cpi = cost / install if install > 0 else 0
        roi_1 = ch.get('roi_1', 0)
        retention = ch.get('retention_1', 0)
        
        # 计算消耗环比
        prev_ch = ios_channels_prev.get(media, {})
        prev_cost = prev_ch.get('cost', 0) if prev_ch else 0
        cost_change_abs = cost - prev_cost
        cost_change_pct = (cost_change_abs / prev_cost * 100) if prev_cost > 0 else 0
        cost_change_dir = "↑" if cost_change_abs >= 0 else "↓"
        
        # 计算 ROI_1 环比
        prev_roi_1 = prev_ch.get('roi_1', 0) if prev_ch else 0
        roi_1_change = roi_1 - prev_roi_1
        roi_1_change_dir = "↑" if roi_1_change >= 0 else "↓"
        
        lines.append(f"| {media} | {format_currency(cost)} | {cost_change_pct:+.1f}% {cost_change_dir} | {format_currency(cost_change_abs)} | {format_number(install)} | ${cpi:.2f} | {format_percent(roi_1)} | {roi_1_change:+.2f}% {roi_1_change_dir} | {format_percent(retention)} |\n")
    
    return "".join(lines)


def main():
    """主函数 - 生成完整报告"""
    print("=" * 60)
    print("Wgame 周报生成脚本 - 完善版")
    print("=" * 60)
    
    # 计算日期范围
    date_ranges = calculate_date_ranges()
    last_start, last_end, wb_start, wb_end, twb_start, twb_end = date_ranges
    
    print(f"\n📅 日期范围：")
    print(f"   上周: {last_start} ~ {last_end}")
    print(f"   上上周: {wb_start} ~ {wb_end}")
    print(f"   上上上周: {twb_start} ~ {twb_end}")
    
    # 查询数据（这里使用模拟数据）
    print("\n📊 查询数据中...")
    
    # Android 渠道数据（上周）
    android_channels = [
        {"media_src": "Google", "cost": 85000, "install": 25000, "retention_1": 35.5, "roi_1": 2.8, "actual_roi": 3.6, "first_pay_rate": 8.2, "first_arppu": 15.5},
        {"media_src": "Facebook", "cost": 62000, "install": 22000, "retention_1": 33.2, "roi_1": 2.5, "actual_roi": 2.9, "first_pay_rate": 7.8, "first_arppu": 14.2},
        {"media_src": "Tiktok", "cost": 45000, "install": 15000, "retention_1": 30.1, "roi_1": 2.2, "actual_roi": 3.8, "first_pay_rate": 7.5, "first_arppu": 13.8},
        {"media_src": "Almedia", "cost": 28000, "install": 8000, "retention_1": 28.5, "roi_1": 3.5, "actual_roi": 7.2, "first_pay_rate": 9.1, "first_arppu": 16.2},
    ]
    
    # Android 渠道数据（上上周）- 用于计算环比
    android_channels_prev = {
        "Google": {"cost": 72000},
        "Facebook": {"cost": 58000},
        "Tiktok": {"cost": 48000},
        "Almedia": {"cost": 25000},
    }
    
    # iOS 渠道数据（上周）
    ios_channels = [
        {"media_src": "Apple Ads", "cost": 95000, "install": 28000, "retention_1": 38.2, "roi_1": 3.2},
        {"media_src": "Facebook", "cost": 55000, "install": 18000, "retention_1": 34.5, "roi_1": 2.8},
        {"media_src": "Google", "cost": 42000, "install": 14000, "retention_1": 33.8, "roi_1": 2.6},
    ]
    
    # iOS 渠道数据（上上周）- 用于计算环比
    ios_channels_prev = {
        "Apple Ads": {"cost": 88000, "roi_1": 3.5},
        "Facebook": {"cost": 52000, "roi_1": 2.9},
        "Google": {"cost": 45000, "roi_1": 2.7},
    }
    
    print("✅ 数据查询完成\n")
    
    # 生成报告各部分
    print("=" * 60)
    print("📄 生成报告...")
    print("=" * 60)
    
    # 第5节：Android 分渠道数据
    android_section = generate_android_channel_section(android_channels, android_channels_prev)
    print(android_section)
    
    # 第6节：iOS 分渠道数据
    ios_section = generate_ios_channel_section(ios_channels, ios_channels_prev)
    print(ios_section)
    
    print("\n" + "=" * 60)
    print("✅ 报告生成完成！")
    print("=" * 60)


if __name__ == '__main__':
    main()
