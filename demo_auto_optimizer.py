#!/usr/bin/env python3
"""
auto-optimizer 演示脚本
展示衰退检测和预算调整的完整流程
"""

import json
from datetime import datetime

# 模拟配置
APPS_CONFIG = {
    "ROK": {
        "name": "万国觉醒",
        "facebook": {
            "target_cpi": 4.0,
            "target_roi": 2.5
        }
    }
}

THRESHOLDS = {
    "campaign_decay": {
        "consecutive_days": 3,
        "cpi_above_target_pct": 1.25
    },
    "adset_decay": {
        "consecutive_days": 3,
        "cpi_above_target_pct": 1.25,
        "roi_below_target_pct": 0.80
    },
    "high_risk_spend": {
        "daily_spend_threshold": 500,
        "roi_below_target_pct": 0.80
    },
    "budget_adjustment": {
        "auto_max_reduction_pct": 0.30,
        "min_age_hours_ios": 72
    }
}

def check_campaign_decay(daily_cpis, target_cpi, thresholds):
    """检测 Campaign 衰退（B02）"""
    required_days = thresholds["campaign_decay"]["consecutive_days"]
    cpi_pct = thresholds["campaign_decay"]["cpi_above_target_pct"]
    
    if len(daily_cpis) < required_days:
        return None
    
    cpi_threshold = target_cpi * cpi_pct
    
    # 计算连续超标天数
    max_run = 0
    current_run = 0
    for cpi in daily_cpis:
        if cpi > cpi_threshold:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    
    if max_run >= required_days:
        return {
            "type": "campaign_decay",
            "severity": "P1",
            "consecutive_days": max_run,
            "cpi_threshold": round(cpi_threshold, 2),
            "message": f"Campaign 连续 {max_run} 天 CPI 超标（阈值 {cpi_threshold:.2f}）"
        }
    return None

def decide_budget_action(campaign_id, os, actual_roi, target_roi, daily_spend, launch_date, today):
    """预算行动决策（含 iOS 保护期）"""
    
    # iOS 72h 保护期检查
    if os == "ios":
        launch = datetime.strptime(launch_date, "%Y-%m-%d")
        now = datetime.strptime(today, "%Y-%m-%d")
        age_hours = (now - launch).total_seconds() / 3600
        
        if age_hours < 72:
            return {
                "campaign_id": campaign_id,
                "action": "skip",
                "reason": f"iOS SKAN grace period: {age_hours:.0f}h < 72h since launch",
                "os": os
            }
    
    # ROI 分级决策
    ratio = actual_roi / target_roi if target_roi > 0 else 0
    
    if ratio < 0.5:
        action = "pause"
    elif ratio < 1.0:
        action = "reduce"
    elif ratio < 1.5:
        action = "maintain"
    else:
        action = "scale"
    
    reason = f"actual_roi={actual_roi:.2f} vs target_roi={target_roi:.2f} (ratio={ratio:.2f})"
    if daily_spend > 0:
        reason += f"; daily_spend=${daily_spend:.0f}"
    
    return {
        "campaign_id": campaign_id,
        "action": action,
        "reason": reason,
        "os": os
    }

def compute_adjustment(current_budget, reduction_pct, daily_spend):
    """计算预算调整"""
    new_budget = round(current_budget * (1 - reduction_pct), 2)
    
    needs_confirmation = False
    reasons = []
    
    if reduction_pct > 0.30:
        needs_confirmation = True
        reasons.append(f"降幅 {reduction_pct:.0%} 超过自动执行上限 30%")
    
    if daily_spend > 500:
        needs_confirmation = True
        reasons.append(f"日耗 ${daily_spend:.0f} 超过 $500 阈值")
    
    return {
        "current_budget": current_budget,
        "new_budget": new_budget,
        "reduction_pct": reduction_pct,
        "needs_confirmation": needs_confirmation,
        "confirmation_reason": "; ".join(reasons) if reasons else ""
    }

def demo():
    """演示完整流程"""
    print("=" * 60)
    print("Auto-Optimizer 演示")
    print("=" * 60)
    
    project = "ROK"
    target_cpi = APPS_CONFIG[project]["facebook"]["target_cpi"]
    target_roi = APPS_CONFIG[project]["facebook"]["target_roi"]
    
    print(f"\n【项目配置】")
    print(f"  项目: {project}")
    print(f"  目标 CPI: ${target_cpi}")
    print(f"  目标 ROI: {target_roi}")
    
    # 场景 1: Campaign 衰退检测
    print("\n" + "=" * 60)
    print("【场景 1】Campaign 衰退检测（B02）")
    print("=" * 60)
    
    campaign_data = {
        "id": "123456789",
        "name": "ROK_US_Android_Campaign",
        "daily_cpis": [3.8, 4.2, 5.5, 5.8, 5.2],
        "daily_rois": [2.8, 2.5, 2.1, 1.9, 2.2]
    }
    
    print(f"\nCampaign: {campaign_data['name']}")
    print(f"近5天 CPI: {campaign_data['daily_cpis']}")
    print(f"目标 CPI: ${target_cpi}")
    print(f"衰退阈值: ${target_cpi * 1.25:.2f} (目标 x 125%)")
    
    alert = check_campaign_decay(
        campaign_data["daily_cpis"],
        target_cpi,
        THRESHOLDS
    )
    
    if alert:
        print(f"\n⚠️  检测到衰退!")
        print(f"   类型: {alert['type']}")
        print(f"   级别: {alert['severity']}")
        print(f"   连续天数: {alert['consecutive_days']} 天")
        print(f"   消息: {alert['message']}")
        
        print(f"\n【预算行动决策】")
        
        # Android Campaign
        decision = decide_budget_action(
            campaign_id=campaign_data["id"],
            os="android",
            actual_roi=1.9,
            target_roi=target_roi,
            daily_spend=300,
            launch_date="2026-04-01",
            today="2026-05-13"
        )
        print(f"\nAndroid Campaign:")
        print(f"  行动: {decision['action']}")
        print(f"  原因: {decision['reason']}")
        
        if decision['action'] == "reduce":
            adj = compute_adjustment(
                current_budget=300,
                reduction_pct=0.30,
                daily_spend=300
            )
            print(f"\n  预算调整:")
            print(f"    当前预算: ${adj['current_budget']}")
            print(f"    新预算: ${adj['new_budget']}")
            print(f"    降幅: {adj['reduction_pct']:.0%}")
            print(f"    需要确认: {adj['needs_confirmation']}")
        
        # iOS Campaign（保护期示例）
        decision_ios = decide_budget_action(
            campaign_id="987654321",
            os="ios",
            actual_roi=0.5,
            target_roi=target_roi,
            daily_spend=400,
            launch_date="2026-05-12",
            today="2026-05-13"
        )
        print(f"\niOS Campaign (昨天启动):")
        print(f"  行动: {decision_ios['action']}")
        print(f"  原因: {decision_ios['reason']}")
        print(f"  ⚠️  处于 SKAN 72h 保护期，跳过调整")
    else:
        print(f"\n✅ Campaign 健康，未检测到衰退")
    
    # 场景 2: 高风险消耗检测
    print("\n" + "=" * 60)
    print("【场景 2】高风险消耗检测（C04）")
    print("=" * 60)
    
    high_risk_campaign = {
        "id": "555666777",
        "name": "ROK_US_High_Spend",
        "daily_spend": 800,
        "roi": 1.5,
        "target_roi": 2.5
    }
    
    print(f"\nCampaign: {high_risk_campaign['name']}")
    print(f"日耗: ${high_risk_campaign['daily_spend']}")
    print(f"ROI: {high_risk_campaign['roi']}")
    print(f"目标 ROI: {high_risk_campaign['target_roi']}")
    print(f"高风险阈值: 日耗 >$500 且 ROI < {high_risk_campaign['target_roi'] * 0.8:.2f}")
    
    if (high_risk_campaign["daily_spend"] > 500 and 
        high_risk_campaign["roi"] < high_risk_campaign["target_roi"] * 0.8):
        print(f"\n⚠️  检测到高风险!")
        print(f"   级别: P1")
        print(f"   建议: 需要人工确认后暂停或大幅降预算")
    
    # 场景 3: 预算调整计算
    print("\n" + "=" * 60)
    print("【场景 3】预算调整计算")
    print("=" * 60)
    
    scenarios = [
        {"current": 300, "reduction": 0.30, "daily_spend": 300, "desc": "标准降预算"},
        {"current": 1000, "reduction": 0.50, "daily_spend": 800, "desc": "大幅降预算（需确认）"},
    ]
    
    for s in scenarios:
        adj = compute_adjustment(s["current"], s["reduction"], s["daily_spend"])
        print(f"\n场景: {s['desc']}")
        print(f"  当前预算: ${adj['current_budget']}")
        print(f"  新预算: ${adj['new_budget']}")
        print(f"  降幅: {adj['reduction_pct']:.0%}")
        print(f"  需要确认: {adj['needs_confirmation']}")
        if adj['needs_confirmation']:
            print(f"  原因: {adj['confirmation_reason']}")
    
    print("\n" + "=" * 60)
    print("演示完成")
    print("=" * 60)

if __name__ == "__main__":
    demo()
