#!/usr/bin/env python3
"""
Applovin Campaign Manager - 操作确认包装器

所有修改操作在执行前必须经过用户确认
"""

import json
import time
from typing import Callable, Any, Dict, Optional
from datetime import datetime, timedelta


# 存储待确认的操作（内存中，重启后清空）
_pending_confirmations: Dict[str, Dict[str, Any]] = {}


def generate_confirmation_id() -> str:
    """生成确认 ID"""
    import uuid
    return str(uuid.uuid4())[:8]


def format_operation_details(operation_name: str, campaign_id: int, 
                             campaign_info: Optional[Dict] = None,
                             extra_details: Optional[Dict] = None) -> str:
    """格式化操作详情"""
    lines = []
    lines.append("=" * 50)
    lines.append("⚠️  即将执行广告操作，请确认")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"📌 操作类型: {operation_name}")
    lines.append(f"📌 Campaign ID: {campaign_id}")
    
    if campaign_info:
        lines.append(f"📌 Campaign 名称: {campaign_info.get('name', 'Unknown')}")
        lines.append(f"📌 当前状态: {campaign_info.get('status', 'Unknown')}")
        lines.append(f"📌 平台: {campaign_info.get('platform', 'Unknown')}")
        
        budget = campaign_info.get('budget', {})
        if budget and 'amount' in budget:
            lines.append(f"📌 当前预算: ${budget['amount']:,.2f}")
        
        goal = campaign_info.get('goal', {})
        if goal and 'cpi' in goal:
            lines.append(f"📌 当前 CPI 目标: ${goal['cpi']:.2f}")
    
    if extra_details:
        lines.append("")
        lines.append("📋 变更详情:")
        for key, value in extra_details.items():
            lines.append(f"   • {key}: {value}")
    
    lines.append("")
    lines.append("=" * 50)
    lines.append("请回复以下指令之一:")
    lines.append("  ✅ 确认执行: 回复 \"可以\" / \"确认\" / \"yes\" / \"ok\"")
    lines.append("  ❌ 取消操作: 回复其他任何内容，或 5 分钟内不回复")
    lines.append("=" * 50)
    
    return "\n".join(lines)


def wait_for_confirmation(
    confirmation_id: str,
    check_callback: Callable[[], Optional[str]],
    timeout_seconds: int = 300
) -> bool:
    """
    等待用户确认
    
    Args:
        confirmation_id: 确认 ID
        check_callback: 检查用户回复的回调函数，返回用户最新回复或 None
        timeout_seconds: 超时时间（默认 5 分钟）
    
    Returns:
        True: 用户确认
        False: 用户取消或超时
    """
    start_time = datetime.now()
    timeout = timedelta(seconds=timeout_seconds)
    
    print(f"⏳ 等待用户确认... (确认 ID: {confirmation_id})")
    print(f"   超时时间: {timeout_seconds} 秒")
    
    while datetime.now() - start_time < timeout:
        # 检查用户回复
        user_response = check_callback()
        
        if user_response:
            response_lower = user_response.strip().lower()
            
            # 确认关键词
            confirm_keywords = ['可以', '确认', 'yes', 'ok', 'y', '是', '执行', '同意']
            # 取消关键词
            cancel_keywords = ['取消', 'cancel', 'no', 'n', '否', '不', '停止', 'abort']
            
            if any(kw in response_lower for kw in confirm_keywords):
                print(f"✅ 用户确认执行 (回复: {user_response})")
                return True
            elif any(kw in response_lower for kw in cancel_keywords):
                print(f"❌ 用户取消操作 (回复: {user_response})")
                return False
            else:
                print(f"📝 收到回复: {user_response}，继续等待确认...")
        
        # 等待 1 秒后再次检查
        time.sleep(1)
    
    print("⏰ 等待超时，操作已取消")
    return False


def confirm_and_execute(
    send_message_func: Callable[[str], Any],
    receive_message_func: Callable[[], Optional[str]],
    operation: Callable,
    campaign_id: int,
    operation_name: str,
    campaign_info: Optional[Dict] = None,
    extra_details: Optional[Dict] = None,
    timeout_seconds: int = 300,
    *args,
    **kwargs
) -> Optional[Any]:
    """
    带确认的操作执行器
    
    流程:
    1. 展示操作详情
    2. 等待用户确认
    3. 确认后执行操作
    4. 返回操作结果
    
    Args:
        send_message_func: 发送消息给用户的函数
        receive_message_func: 接收用户回复的函数
        operation: 要执行的操作函数
        campaign_id: Campaign ID
        operation_name: 操作名称
        campaign_info: Campaign 信息（可选）
        extra_details: 额外详情（可选）
        timeout_seconds: 超时时间
        *args, **kwargs: 传递给 operation 的参数
    
    Returns:
        操作结果（用户取消返回 None）
    """
    # 生成确认 ID
    confirmation_id = generate_confirmation_id()
    
    # 格式化并发送确认消息
    confirm_message = format_operation_details(
        operation_name=operation_name,
        campaign_id=campaign_id,
        campaign_info=campaign_info,
        extra_details=extra_details
    )
    
    send_message_func(confirm_message)
    
    # 等待确认
    confirmed = wait_for_confirmation(
        confirmation_id=confirmation_id,
        check_callback=receive_message_func,
        timeout_seconds=timeout_seconds
    )
    
    if not confirmed:
        send_message_func("❌ 操作已取消")
        return None
    
    # 执行操作
    try:
        send_message_func(f"🚀 正在执行 {operation_name}...")
        result = operation(*args, **kwargs)
        send_message_func(f"✅ {operation_name} 执行成功")
        return result
    except Exception as e:
        error_msg = f"❌ {operation_name} 执行失败: {str(e)}"
        send_message_func(error_msg)
        raise


# 便捷函数

def confirm_pause_campaign(
    send_message_func: Callable[[str], Any],
    receive_message_func: Callable[[], Optional[str]],
    manager,
    campaign_id: int,
    campaign_info: Dict = None
):
    """确认后暂停 Campaign"""
    if campaign_info is None:
        campaign_info = manager.get_campaign(campaign_id)
    
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.pause_campaign,
        campaign_id=campaign_id,
        operation_name="暂停 Campaign",
        campaign_info=campaign_info,
        extra_details={"操作后状态": "PAUSED"}
    )


def confirm_resume_campaign(
    send_message_func: Callable[[str], Any],
    receive_message_func: Callable[[], Optional[str]],
    manager,
    campaign_id: int,
    campaign_info: Dict = None
):
    """确认后恢复 Campaign"""
    if campaign_info is None:
        campaign_info = manager.get_campaign(campaign_id)
    
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.resume_campaign,
        campaign_id=campaign_id,
        operation_name="恢复 Campaign",
        campaign_info=campaign_info,
        extra_details={"操作后状态": "LIVE"}
    )


def confirm_update_budget(
    send_message_func: Callable[[str], Any],
    receive_message_func: Callable[[], Optional[str]],
    manager,
    campaign_id: int,
    new_budget: float,
    campaign_info: Dict = None
):
    """确认后修改预算"""
    if campaign_info is None:
        campaign_info = manager.get_campaign(campaign_id)
    
    old_budget = campaign_info.get('budget', {}).get('amount', 0) if campaign_info else 0
    
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.update_budget,
        operation_name="修改 Campaign 预算",
        campaign_info=campaign_info,
        extra_details={
            "原预算": f"${old_budget:,.2f}",
            "新预算": f"${new_budget:,.2f}",
            "变化": f"${new_budget - old_budget:,.2f}"
        },
        campaign_id=campaign_id,
        budget_amount=new_budget
    )


def confirm_update_cpi(
    send_message_func: Callable[[str], Any],
    receive_message_func: Callable[[], Optional[str]],
    manager,
    campaign_id: int,
    new_cpi: float,
    campaign_info: Dict = None
):
    """确认后修改 CPI 目标"""
    if campaign_info is None:
        campaign_info = manager.get_campaign(campaign_id)
    
    old_cpi = campaign_info.get('goal', {}).get('cpi', 0) if campaign_info else 0
    
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.update_cpi_goal,
        operation_name="修改 CPI 目标",
        campaign_info=campaign_info,
        extra_details={
            "原 CPI": f"${old_cpi:.2f}",
            "新 CPI": f"${new_cpi:.2f}",
            "变化": f"${new_cpi - old_cpi:.2f}"
        },
        campaign_id=campaign_id,
        cpi_target=new_cpi
    )


def confirm_add_countries(
    send_message_func,
    receive_message_func,
    manager,
    campaign_id: int,
    country_codes: List[str],
    campaign_info: Dict = None
):
    """确认后添加目标国家"""
    if campaign_info is None:
        campaign_info = manager.get_campaign(campaign_id)
    
    current_countries = [t.get("country_code") for t in campaign_info.get("targeting", [])]
    
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.add_countries,
        operation_name="添加目标国家",
        campaign_info=campaign_info,
        extra_details={
            "当前国家": ", ".join(current_countries) if current_countries else "无",
            "新增国家": ", ".join(country_codes),
            "操作后国家数": len(current_countries) + len(country_codes)
        },
        campaign_id=campaign_id,
        country_codes=country_codes
    )


def confirm_remove_countries(
    send_message_func,
    receive_message_func,
    manager,
    campaign_id: int,
    country_codes: List[str],
    campaign_info: Dict = None
):
    """确认后移除目标国家"""
    if campaign_info is None:
        campaign_info = manager.get_campaign(campaign_id)
    
    current_countries = [t.get("country_code") for t in campaign_info.get("targeting", [])]
    
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.remove_countries,
        operation_name="移除目标国家",
        campaign_info=campaign_info,
        extra_details={
            "当前国家": ", ".join(current_countries) if current_countries else "无",
            "移除国家": ", ".join(country_codes),
            "操作后国家数": len(current_countries) - len(country_codes)
        },
        campaign_id=campaign_id,
        country_codes=country_codes
    )


def confirm_update_bidding_strategy(
    send_message_func,
    receive_message_func,
    manager,
    campaign_id: int,
    strategy: str,
    campaign_info: Dict = None
):
    """确认后修改竞价策略"""
    if campaign_info is None:
        campaign_info = manager.get_campaign(campaign_id)
    
    current_strategy = campaign_info.get("bidding_strategy", "Unknown")
    
    strategy_names = {
        "target_goal_with_cpi_billing": "目标 CPI 竞价",
        "auto_bidding_with_cpm_billing": "自动 CPM 竞价",
        "maximize_results_with_cpm_billing": "最大化结果 CPM 竞价"
    }
    
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.update_bidding_strategy,
        operation_name="修改竞价策略",
        campaign_info=campaign_info,
        extra_details={
            "当前策略": strategy_names.get(current_strategy, current_strategy),
            "新策略": strategy_names.get(strategy, strategy)
        },
        campaign_id=campaign_id,
        strategy=strategy
    )


def confirm_enable_creative_set(
    send_message_func,
    receive_message_func,
    manager,
    creative_set_id: int
):
    """确认后启用素材组"""
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.enable_creative_set,
        operation_name="启用素材组",
        campaign_info=None,
        extra_details={
            "素材组 ID": creative_set_id,
            "操作后状态": "LIVE"
        },
        creative_set_id=creative_set_id
    )


def confirm_disable_creative_set(
    send_message_func,
    receive_message_func,
    manager,
    creative_set_id: int
):
    """确认后禁用素材组"""
    return confirm_and_execute(
        send_message_func=send_message_func,
        receive_message_func=receive_message_func,
        operation=manager.disable_creative_set,
        operation_name="禁用素材组",
        campaign_info=None,
        extra_details={
            "素材组 ID": creative_set_id,
            "操作后状态": "PAUSED"
        },
        creative_set_id=creative_set_id
    )