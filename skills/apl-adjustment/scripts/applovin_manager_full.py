#!/usr/bin/env python3
"""
Applovin Campaign Manager - 完整版

包含所有 API 功能：
- Campaign: list, get, create, update, pause, resume
- 预算: 全球预算、国家级预算
- 目标: CPI, CPE, CPP, AD_ROAS, BLD_ROAS, CHK_ROAS
- 国家定向: 添加、移除、设置，支持美国地区
- 素材组: list, get, create, update, clone, enable, disable
- 资源: list, upload
"""

import json
import os
from typing import Optional, Dict, Any, List
from pathlib import Path

import requests


BASE_URL = "https://api.ads.axon.ai/manage/v1"


class ApplovinCampaignManager:
    """Applovin Campaign 完整管理器"""
    
    def __init__(self, api_key: str, account_id: str):
        self.api_key = api_key
        self.account_id = account_id
        self.session = requests.Session()
        self.session.headers.update({"Authorization": api_key})
    
    @classmethod
    def from_env(cls) -> "ApplovinCampaignManager":
        api_key = os.environ.get("APPLOVIN_API_KEY")
        account_id = os.environ.get("APPLOVIN_ACCOUNT_ID")
        if not api_key or not account_id:
            raise ValueError("未设置 APPLOVIN_API_KEY 或 APPLOVIN_ACCOUNT_ID")
        return cls(api_key, account_id)
    
    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                 data: Optional[Dict] = None, files: Optional[Dict] = None) -> Any:
        url = f"{BASE_URL}{endpoint}"
        if params is None:
            params = {}
        params["account_id"] = self.account_id
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, params=params, timeout=30)
            elif method.upper() == "POST":
                if files:
                    response = self.session.post(url, params=params, data=data, 
                                                files=files, timeout=300)
                else:
                    response = self.session.post(url, params=params, json=data, timeout=30)
            else:
                raise ValueError(f"不支持的方法: {method}")
            
            if response.status_code == 429:
                raise Exception("超出 API 频率限制，请 10 分钟后重试")
            
            if response.status_code >= 400:
                error_code = response.headers.get("x-al-error-code", "Unknown")
                error_msg = response.headers.get("x-al-error-message", "Unknown")
                trace_id = response.headers.get("X-TRACE-ID", "N/A")
                raise Exception(f"API 错误 [{response.status_code}]: {error_code} - {error_msg} (Trace: {trace_id})")
            
            return response.json() if response.content else {}
        except requests.exceptions.Timeout:
            raise Exception("请求超时")
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求失败: {e}")
    
    # ==================== Campaign ====================
    
    def list_campaigns(self, page: int = 1, size: int = 100) -> List[Dict]:
        params = {"page": page, "size": size}
        response = self._request("GET", "/campaign/list", params=params)
        return response if isinstance(response, list) else []
    
    def get_campaign(self, campaign_id: int) -> Optional[Dict]:
        params = {"ids": campaign_id}
        campaigns = self._request("GET", "/campaign/list", params=params)
        return campaigns[0] if campaigns else None
    
    def create_campaign(self, name: str, platform: str, package_name: str,
                       start_date: str, end_date: str, budget: Dict, 
                       goal: Dict, targeting: List[Dict], tracking: Dict,
                       **kwargs) -> Dict:
        """
        创建 Campaign
        
        Args:
            name: Campaign 名称
            platform: 平台 (android/ios)
            package_name: 包名
            start_date: 开始日期 (ISO 8601)
            end_date: 结束日期 (ISO 8601)
            budget: 预算配置 {"daily_budget_for_all_countries": 1000}
            goal: 目标配置 {"goal_type": "CPI", "goal_value_for_all_countries": 2.5}
            targeting: 定向 [{"country_code": "US"}]
            tracking: 跟踪配置 {"tracking_method": "ADJUST", "click_url": "...", "impression_url": "..."}
        """
        data = {
            "name": name,
            "platform": platform,
            "package_name": package_name,
            "start_date": start_date,
            "end_date": end_date,
            "budget": budget,
            "goal": goal,
            "targeting": targeting,
            "tracking": tracking,
            "type": "APP"
        }
        data.update(kwargs)
        return self._request("POST", "/campaign/create", data=data)
    
    def update_campaign(self, campaign_id: int, **updates) -> Dict:
        """更新 Campaign"""
        data = {"id": campaign_id}
        data.update(updates)
        return self._request("POST", "/campaign/update", data=data)
    
    def pause_campaign(self, campaign_id: int) -> Dict:
        return self.update_campaign(campaign_id, status="PAUSED")
    
    def resume_campaign(self, campaign_id: int) -> Dict:
        return self.update_campaign(campaign_id, status="LIVE")
    
    # ==================== 预算管理 ====================
    
    def update_global_budget(self, campaign_id: int, daily_budget: float) -> Dict:
        """修改全球预算"""
        campaign = self.get_campaign(campaign_id)
        budget = campaign.get("budget", {})
        budget["daily_budget_for_all_countries"] = daily_budget
        return self.update_campaign(campaign_id, budget=budget)
    
    def update_country_budget(self, campaign_id: int, country_code: str, 
                             daily_budget: float) -> Dict:
        """修改国家级预算"""
        campaign = self.get_campaign(campaign_id)
        budget = campaign.get("budget", {})
        
        if "country_budgets" not in budget:
            budget["country_budgets"] = {}
        
        budget["country_budgets"][country_code.upper()] = {
            "daily_budget": daily_budget
        }
        return self.update_campaign(campaign_id, budget=budget)
    
    # ==================== 目标管理 ====================
    
    def update_goal(self, campaign_id: int, goal_type: str, 
                   goal_value: float, country_code: Optional[str] = None) -> Dict:
        """
        修改目标
        
        Args:
            goal_type: CPI, CPE, CPP, AD_ROAS, BLD_ROAS, CHK_ROAS
            goal_value: 目标值
            country_code: 可选，指定国家
        """
        campaign = self.get_campaign(campaign_id)
        goal = campaign.get("goal", {})
        goal["goal_type"] = goal_type
        
        if country_code:
            if "country_goals" not in goal:
                goal["country_goals"] = {}
            goal["country_goals"][country_code.upper()] = {
                "goal_value": goal_value
            }
        else:
            goal["goal_value_for_all_countries"] = goal_value
        
        return self.update_campaign(campaign_id, goal=goal)
    
    # ==================== 国家定向 ====================
    
    def get_targeting(self, campaign_id: int) -> List[Dict]:
        campaign = self.get_campaign(campaign_id)
        return campaign.get("targeting", []) if campaign else []
    
    def add_countries(self, campaign_id: int, country_codes: List[str],
                     region_codes: Optional[Dict[str, List[str]]] = None) -> Dict:
        """
        添加目标国家
        
        Args:
            country_codes: 国家代码列表
            region_codes: 可选，美国地区代码 {"US": ["CA", "NY"]}
        """
        campaign = self.get_campaign(campaign_id)
        targeting = campaign.get("targeting", [])
        existing = {t.get("country_code") for t in targeting}
        
        for code in country_codes:
            code_upper = code.upper()
            if code_upper not in existing:
                target = {"country_code": code_upper}
                if region_codes and code_upper in region_codes:
                    target["region_codes"] = region_codes[code_upper]
                targeting.append(target)
        
        return self.update_campaign(campaign_id, targeting=targeting)
    
    def remove_countries(self, campaign_id: int, country_codes: List[str]) -> Dict:
        """移除目标国家"""
        campaign = self.get_campaign(campaign_id)
        targeting = campaign.get("targeting", [])
        codes_to_remove = {c.upper() for c in country_codes}
        targeting = [t for t in targeting if t.get("country_code") not in codes_to_remove]
        return self.update_campaign(campaign_id, targeting=targeting)
    
    def set_countries(self, campaign_id: int, country_codes: List[str],
                     region_codes: Optional[Dict[str, List[str]]] = None) -> Dict:
        """设置目标国家（替换）"""
        targeting = []
        for code in country_codes:
            target = {"country_code": code.upper()}
            if region_codes and code.upper() in region_codes:
                target["region_codes"] = region_codes[code.upper()]
            targeting.append(target)
        return self.update_campaign(campaign_id, targeting=targeting)
    
    # ==================== 竞价策略 ====================
    
    def update_bidding_strategy(self, campaign_id: int, strategy: str) -> Dict:
        """
        修改竞价策略
        
        Args:
            strategy: target_goal_with_cpi_billing, auto_bidding_with_cpm_billing, 
                     maximize_results_with_cpm_billing
        """
        valid = ["target_goal_with_cpi_billing", "auto_bidding_with_cpm_billing",
                "maximize_results_with_cpm_billing"]
        if strategy not in valid:
            raise ValueError(f"无效策略: {strategy}")
        return self.update_campaign(campaign_id, bidding_strategy=strategy)
    
    # ==================== 素材组管理 ====================
    
    def list_creative_sets(self, page: int = 1, size: int = 100) -> List[Dict]:
        """列出所有素材组"""
        params = {"page": page, "size": size}
        response = self._request("GET", "/creative_set/list", params=params)
        return response if isinstance(response, list) else []
    
    def get_creative_set(self, creative_set_id: int) -> Optional[Dict]:
        """获取素材组详情"""
        params = {"ids": creative_set_id}
        sets = self._request("GET", "/creative_set/list", params=params)
        return sets[0] if sets else None
    
    def get_creative_sets_by_campaign(self, campaign_id: int, page: int = 1,
                                       size: int = 100) -> Dict:
        """获取 Campaign 的素材组"""
        params = {"ids": campaign_id, "page": page, "size": size}
        return self._request("GET", "/creative_set/list_by_campaign_id", params=params)
    
    def create_creative_set(self, name: str, campaign_id: str, assets: List[Dict],
                           countries: Optional[List[str]] = None,
                           languages: Optional[List[str]] = None,
                           status: str = "LIVE") -> Dict:
        """
        创建素材组
        
        Args:
            name: 素材组名称
            campaign_id: Campaign ID
            assets: 资源列表 [{"id": "asset_id", "type": "VID_LONG_P"}]
            countries: 可选，国家代码列表
            languages: 可选，语言列表
            status: LIVE 或 PAUSED
        """
        data = {
            "name": name,
            "campaign_id": campaign_id,
            "assets": assets,
            "status": status,
            "type": "APP"
        }
        if countries:
            data["countries"] = countries
        if languages:
            data["languages"] = languages
        return self._request("POST", "/creative_set/create", data=data)
    
    def update_creative_set(self, creative_set_id: int, **updates) -> Dict:
        """
        更新素材组
        
        注意：
        - id 必须是 String 类型
        - assets 字段是必需的（如果要更新）
        - 建议先获取素材组完整信息，再修改需要的字段
        """
        data = {"id": str(creative_set_id)}
        data.update(updates)
        return self._request("POST", "/creative_set/update", data=data)
    
    def update_creative_set_status(self, creative_set_id: int, status: str) -> Dict:
        """
        更新素材组状态（LIVE/PAUSED）
        
        会自动获取素材组完整信息并保留 assets 字段
        """
        if status not in ["LIVE", "PAUSED"]:
            raise ValueError(f"无效状态: {status}")
        
        # 获取素材组完整信息
        cs = self.get_creative_set(creative_set_id)
        if not cs:
            raise ValueError(f"素材组不存在: {creative_set_id}")
        
        # 构建更新请求（保留所有必需字段）
        data = {
            "id": str(creative_set_id),
            "status": status,
            "type": cs.get("type", "APP"),
            "campaign_id": cs.get("campaign_id"),
            "name": cs.get("name"),
            "assets": cs.get("assets", []),
        }
        
        # 可选字段
        if cs.get("countries"):
            data["countries"] = cs.get("countries")
        if cs.get("languages"):
            data["languages"] = cs.get("languages")
        if cs.get("product_page"):
            data["product_page"] = cs.get("product_page")
        
        return self._request("POST", "/creative_set/update", data=data)
    
    def clone_creative_set(self, creative_set_id: int, target_campaign_id: int,
                          status: str = "PAUSED") -> Dict:
        """
        克隆素材组
        
        Args:
            creative_set_id: 源素材组 ID
            target_campaign_id: 目标 Campaign ID
            status: 克隆后状态 (LIVE/PAUSED)
        """
        data = {
            "creative_set_id": creative_set_id,
            "campaign_id": target_campaign_id,
            "status": status
        }
        return self._request("POST", "/creative_set/clone", data=data)
    
    def enable_creative_set(self, creative_set_id: int) -> Dict:
        """启用素材组"""
        return self.update_creative_set_status(creative_set_id, "LIVE")
    
    def disable_creative_set(self, creative_set_id: int) -> Dict:
        """禁用素材组"""
        return self.update_creative_set_status(creative_set_id, "PAUSED")
    
    # ==================== 资源管理 ====================
    
    def list_assets(self, page: int = 1, size: int = 100,
                   resource_type: Optional[str] = None) -> List[Dict]:
        """
        列出资源
        
        Args:
            resource_type: 可选，image/html/video
        """
        params = {"page": page, "size": size}
        if resource_type:
            params["resource_type"] = resource_type
        response = self._request("GET", "/asset/list", params=params)
        return response if isinstance(response, list) else []
    
    def upload_assets(self, file_paths: List[str]) -> Dict:
        """
        上传资源
        
        Args:
            file_paths: 文件路径列表 (最多 40 个，总大小不超过 10GB，单个不超过 1GB)
        
        Returns:
            包含 upload_id 的响应
        """
        files = []
        for path in file_paths:
            p = Path(path)
            if not p.exists():
                raise ValueError(f"文件不存在: {path}")
            
            # 根据扩展名判断 Content-Type
            ext = p.suffix.lower()
            content_type_map = {
                '.html': 'text/html',
                '.gif': 'image/gif',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.mp4': 'video/mp4',
                '.mov': 'video/quicktime'
            }
            content_type = content_type_map.get(ext, 'application/octet-stream')
            
            files.append(('files', (p.name, open(path, 'rb'), content_type)))
        
        try:
            response = self._request("POST", "/asset/upload", files=files)
            return response
        finally:
            for _, file_tuple in files:
                file_tuple[1].close()
    
    def get_upload_result(self, upload_id: str) -> Dict:
        """查询上传结果"""
        params = {"upload_id": upload_id}
        return self._request("GET", "/asset/upload_result", params=params)


# 便捷函数

def pause_campaign(campaign_id: int) -> Dict:
    return ApplovinCampaignManager.from_env().pause_campaign(campaign_id)

def resume_campaign(campaign_id: int) -> Dict:
    return ApplovinCampaignManager.from_env().resume_campaign(campaign_id)

def update_budget(campaign_id: int, budget: float) -> Dict:
    return ApplovinCampaignManager.from_env().update_global_budget(campaign_id, budget)

def update_goal(campaign_id: int, goal_type: str, goal_value: float) -> Dict:
    return ApplovinCampaignManager.from_env().update_goal(campaign_id, goal_type, goal_value)
