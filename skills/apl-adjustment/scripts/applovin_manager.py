#!/usr/bin/env python3
"""
Applovin Campaign Manager 模块

用于程序化调用 Applovin Campaign API
"""

import json
import os
from typing import Optional, Dict, Any, List

import requests


# API 配置
BASE_URL = "https://api.applovin.com/campaign_management/v1"


class ApplovinCampaignManager:
    """Applovin Campaign 管理器"""
    
    def __init__(self, api_key: str, account_id: str):
        """
        初始化管理器
        
        Args:
            api_key: Campaign Management API Key
            account_id: Account ID
        """
        self.api_key = api_key
        self.account_id = account_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json"
        })
    
    @classmethod
    def from_env(cls) -> "ApplovinCampaignManager":
        """从环境变量创建管理器"""
        api_key = os.environ.get("APPLOVIN_API_KEY")
        account_id = os.environ.get("APPLOVIN_ACCOUNT_ID")
        
        if not api_key or not account_id:
            raise ValueError(
                "未设置环境变量 APPLOVIN_API_KEY 或 APPLOVIN_ACCOUNT_ID"
            )
        
        return cls(api_key, account_id)
    
    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                 data: Optional[Dict] = None) -> Dict[str, Any]:
        """发送 API 请求"""
        url = f"{BASE_URL}{endpoint}"
        
        if params is None:
            params = {}
        params["account_id"] = self.account_id
        
        if method.upper() == "GET":
            response = self.session.get(url, params=params, timeout=30)
        elif method.upper() == "POST":
            response = self.session.post(url, params=params, json=data, timeout=30)
        else:
            raise ValueError(f"不支持的 HTTP 方法: {method}")
        
        if response.status_code == 429:
            raise Exception("超出 API 频率限制（每 60 秒 1000 请求），请 10 分钟后重试")
        
        if response.status_code >= 400:
            error_code = response.headers.get("x-al-error-code", "Unknown")
            error_msg = response.headers.get("x-al-error-message", "Unknown error")
            trace_id = response.headers.get("X-TRACE-ID", "N/A")
            raise Exception(
                f"API 错误 [{response.status_code}]: {error_code} - {error_msg} "
                f"(Trace ID: {trace_id})"
            )
        
        return response.json()
    
    def list_campaigns(self, page: int = 1, size: int = 100) -> List[Dict[str, Any]]:
        """
        列出所有 Campaigns
        
        Args:
            page: 页码（从 1 开始）
            size: 每页数量（最大 100）
        
        Returns:
            Campaign 列表
        """
        params = {"page": page, "size": size}
        response = self._request("GET", "/campaign/list", params=params)
        return response if isinstance(response, list) else []
    
    def get_campaign(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        """
        获取单个 Campaign 详情
        
        Args:
            campaign_id: Campaign ID
        
        Returns:
            Campaign 详情，找不到返回 None
        """
        params = {"ids": campaign_id}
        campaigns = self._request("GET", "/campaign/list", params=params)
        return campaigns[0] if campaigns else None
    
    def pause_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """
        暂停 Campaign
        
        Args:
            campaign_id: Campaign ID
        
        Returns:
            API 响应
        """
        data = {"id": campaign_id, "status": "PAUSED"}
        return self._request("POST", "/campaign/update", data=data)
    
    def resume_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """
        恢复 Campaign
        
        Args:
            campaign_id: Campaign ID
        
        Returns:
            API 响应
        """
        data = {"id": campaign_id, "status": "LIVE"}
        return self._request("POST", "/campaign/update", data=data)
    
    def update_budget(self, campaign_id: int, budget_amount: float) -> Dict[str, Any]:
        """
        修改 Campaign 预算
        
        Args:
            campaign_id: Campaign ID
            budget_amount: 新预算金额
        
        Returns:
            API 响应
        """
        campaign = self.get_campaign(campaign_id)
        if not campaign:
            raise ValueError(f"找不到 Campaign ID {campaign_id}")
        
        budget = campaign.get("budget", {})
        budget["amount"] = budget_amount
        
        data = {"id": campaign_id, "budget": budget}
        return self._request("POST", "/campaign/update", data=data)
    
    def update_cpi_goal(self, campaign_id: int, cpi_target: float) -> Dict[str, Any]:
        """
        修改 CPI 目标
        
        Args:
            campaign_id: Campaign ID
            cpi_target: CPI 目标值
        
        Returns:
            API 响应
        """
        campaign = self.get_campaign(campaign_id)
        if not campaign:
            raise ValueError(f"找不到 Campaign ID {campaign_id}")
        
        goal = campaign.get("goal", {})
        goal["cpi"] = cpi_target
        
        data = {"id": campaign_id, "goal": goal}
        return self._request("POST", "/campaign/update", data=data)
    
    def find_campaigns_by_name(self, name_pattern: str) -> List[Dict[str, Any]]:
        """
        按名称搜索 Campaigns
        
        Args:
            name_pattern: 名称匹配模式（支持部分匹配）
        
        Returns:
            匹配的 Campaign 列表
        """
        campaigns = self.list_campaigns()
        return [
            c for c in campaigns 
            if name_pattern.lower() in c.get("name", "").lower()
        ]
    
    # ==================== 国家定向管理 ====================
    
    def get_targeting(self, campaign_id: int) -> List[Dict[str, Any]]:
        """
        获取 Campaign 的国家定向设置
        
        Args:
            campaign_id: Campaign ID
        
        Returns:
            定向国家列表
        """
        campaign = self.get_campaign(campaign_id)
        return campaign.get("targeting", []) if campaign else []
    
    def add_countries(self, campaign_id: int, country_codes: List[str]) -> Dict[str, Any]:
        """
        添加目标国家
        
        Args:
            campaign_id: Campaign ID
            country_codes: 国家代码列表 (ISO 3166-1 alpha-2, 如 ["US", "JP", "DE"])
        
        Returns:
            API 响应
        """
        campaign = self.get_campaign(campaign_id)
        if not campaign:
            raise ValueError(f"找不到 Campaign ID {campaign_id}")
        
        targeting = campaign.get("targeting", [])
        existing_codes = {t.get("country_code") for t in targeting}
        
        # 添加新国家
        for code in country_codes:
            code_upper = code.upper()
            if code_upper not in existing_codes:
                targeting.append({"country_code": code_upper})
        
        data = {"id": campaign_id, "targeting": targeting}
        return self._request("POST", "/campaign/update", data=data)
    
    def remove_countries(self, campaign_id: int, country_codes: List[str]) -> Dict[str, Any]:
        """
        移除目标国家
        
        Args:
            campaign_id: Campaign ID
            country_codes: 要移除的国家代码列表
        
        Returns:
            API 响应
        """
        campaign = self.get_campaign(campaign_id)
        if not campaign:
            raise ValueError(f"找不到 Campaign ID {campaign_id}")
        
        targeting = campaign.get("targeting", [])
        codes_to_remove = {c.upper() for c in country_codes}
        
        # 过滤掉要移除的国家
        targeting = [t for t in targeting if t.get("country_code") not in codes_to_remove]
        
        data = {"id": campaign_id, "targeting": targeting}
        return self._request("POST", "/campaign/update", data=data)
    
    def set_countries(self, campaign_id: int, country_codes: List[str]) -> Dict[str, Any]:
        """
        设置目标国家（替换现有）
        
        Args:
            campaign_id: Campaign ID
            country_codes: 国家代码列表
        
        Returns:
            API 响应
        """
        targeting = [{"country_code": c.upper()} for c in country_codes]
        data = {"id": campaign_id, "targeting": targeting}
        return self._request("POST", "/campaign/update", data=data)
    
    # ==================== 出价策略管理 ====================
    
    def update_bidding_strategy(self, campaign_id: int, strategy: str) -> Dict[str, Any]:
        """
        修改竞价策略
        
        Args:
            campaign_id: Campaign ID
            strategy: 竞价策略，可选值：
                - target_goal_with_cpi_billing: 目标 CPI 竞价
                - auto_bidding_with_cpm_billing: 自动 CPM 竞价
                - maximize_results_with_cpm_billing: 最大化结果 CPM 竞价
        
        Returns:
            API 响应
        """
        valid_strategies = [
            "target_goal_with_cpi_billing",
            "auto_bidding_with_cpm_billing", 
            "maximize_results_with_cpm_billing"
        ]
        
        if strategy not in valid_strategies:
            raise ValueError(f"无效的竞价策略: {strategy}. 可选: {valid_strategies}")
        
        data = {"id": campaign_id, "bidding_strategy": strategy}
        return self._request("POST", "/campaign/update", data=data)
    
    def update_country_bid(self, campaign_id: int, country_code: str, 
                          bid_amount: Optional[float] = None,
                          cpi_target: Optional[float] = None) -> Dict[str, Any]:
        """
        修改国家级别出价
        
        Args:
            campaign_id: Campaign ID
            country_code: 国家代码 (如 "US")
            bid_amount: 出价金额（可选）
            cpi_target: CPI 目标（可选）
        
        Returns:
            API 响应
        """
        campaign = self.get_campaign(campaign_id)
        if not campaign:
            raise ValueError(f"找不到 Campaign ID {campaign_id}")
        
        budget = campaign.get("budget", {})
        
        # 设置国家级别出价
        country_bids = budget.get("country_bids", {})
        country_upper = country_code.upper()
        
        if country_upper not in country_bids:
            country_bids[country_upper] = {}
        
        if bid_amount is not None:
            country_bids[country_upper]["bid"] = bid_amount
        
        if cpi_target is not None:
            country_bids[country_upper]["cpi_target"] = cpi_target
        
        budget["country_bids"] = country_bids
        data = {"id": campaign_id, "budget": budget}
        return self._request("POST", "/campaign/update", data=data)
    
    # ==================== 素材组管理 ====================
    
    def list_creative_sets(self, page: int = 1, size: int = 100) -> List[Dict[str, Any]]:
        """
        列出所有素材组
        
        Args:
            page: 页码
            size: 每页数量
        
        Returns:
            素材组列表
        """
        params = {"page": page, "size": size}
        response = self._request("GET", "/creative_set/list", params=params)
        return response if isinstance(response, list) else []
    
    def get_creative_sets_by_campaign(self, campaign_id: int, page: int = 1, 
                                      size: int = 100) -> Dict[str, Any]:
        """
        获取 Campaign 的素材组
        
        Args:
            campaign_id: Campaign ID
            page: 页码
            size: 每页数量
        
        Returns:
            素材组信息
        """
        params = {"ids": campaign_id, "page": page, "size": size}
        return self._request("GET", "/creative_set/list_by_campaign_id", params=params)
    
    def enable_creative_set(self, creative_set_id: int) -> Dict[str, Any]:
        """
        启用素材组
        
        Args:
            creative_set_id: 素材组 ID
        
        Returns:
            API 响应
        """
        data = {"id": creative_set_id, "status": "LIVE"}
        return self._request("POST", "/creative_set/update", data=data)
    
    def disable_creative_set(self, creative_set_id: int) -> Dict[str, Any]:
        """
        禁用素材组
        
        Args:
            creative_set_id: 素材组 ID
        
        Returns:
            API 响应
        """
        data = {"id": creative_set_id, "status": "PAUSED"}
        return self._request("POST", "/creative_set/update", data=data)


# 便捷函数（供其他 skill 直接调用）

def pause_campaign(campaign_id: int) -> Dict[str, Any]:
    """暂停指定 Campaign"""
    manager = ApplovinCampaignManager.from_env()
    return manager.pause_campaign(campaign_id)


def resume_campaign(campaign_id: int) -> Dict[str, Any]:
    """恢复指定 Campaign"""
    manager = ApplovinCampaignManager.from_env()
    return manager.resume_campaign(campaign_id)


def update_budget(campaign_id: int, budget: float) -> Dict[str, Any]:
    """更新 Campaign 预算"""
    manager = ApplovinCampaignManager.from_env()
    return manager.update_budget(campaign_id, budget)


def update_cpi(campaign_id: int, cpi: float) -> Dict[str, Any]:
    """更新 Campaign CPI 目标"""
    manager = ApplovinCampaignManager.from_env()
    return manager.update_cpi_goal(campaign_id, cpi)


def get_campaign_info(campaign_id: int) -> Optional[Dict[str, Any]]:
    """获取 Campaign 信息"""
    manager = ApplovinCampaignManager.from_env()
    return manager.get_campaign(campaign_id)


def list_all_campaigns() -> List[Dict[str, Any]]:
    """列出所有 Campaigns"""
    manager = ApplovinCampaignManager.from_env()
    return manager.list_campaigns()
