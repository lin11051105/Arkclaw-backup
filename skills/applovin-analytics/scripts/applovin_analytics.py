#!/usr/bin/env python3
"""
Applovin Reporting API 客户端
用于查询投放数据和分析
"""

import os
import requests
import json
from typing import Dict, List, Optional, Union, Callable
from datetime import datetime, timedelta
from urllib.parse import urlencode


class ApplovinAnalytics:
    """Applovin Reporting API 客户端"""
    
    BASE_URL = "https://r.applovin.com/report"
    
    # T1 国家列表（高价值国家）
    T1_COUNTRIES = {'us', 'gb', 'au', 'ca', 'uk', 'de', 'fr'}
    
    # T3 国家列表（待加载）
    T3_COUNTRIES = None
    
    # 国家出价分析默认配置
    COUNTRY_BID_CONFIG = {
        'short_period_days': 14,
        'long_period_days': 30,
        'pause_threshold_ratio': 0.3,
        'increase_goal_ratio': 0.7,
        'decrease_goal_ratio': 1.1,
        'pause_min_spend': 1000,  # 非T3国家暂停门槛
        'not_started_max_spend': 1000,  # 未起量门槛
    }
    
    # 预定义的列组合
    COLUMN_SETS = {
        "basic": ["campaign", "campaign_id", "cost", "conversions", "clicks", "impressions"],
        "roas": ["campaign", "campaign_id", "cost", "conversions", "roas_7d", "iap_roas_7d"],
        "cpi": ["campaign", "campaign_id", "cost", "conversions", "average_cpa"],
        "ir": ["campaign", "campaign_id", "impressions", "conversions", "conversion_rate"],
        "cpp": ["campaign", "campaign_id", "cost", "first_purchase", "cpp_0d"],
        "creative": ["campaign", "campaign_id", "creative_set", "creative_set_id", "cost", "conversions"],
        "country": ["campaign", "campaign_id", "country", "cost", "conversions", "roas_7d"],
        "full": ["campaign", "campaign_id", "platform", "cost", "conversions", "clicks", "impressions", 
                 "ctr", "conversion_rate", "roas_7d", "iap_roas_7d", "average_cpa"]
    }
    
    def __init__(self, api_key: str):
        """
        初始化 Reporting API 客户端
        
        Args:
            api_key: Report Key（注意：不是 Campaign Management API Key）
        """
        self.api_key = api_key
    
    @classmethod
    def from_env(cls) -> "ApplovinAnalytics":
        """从环境变量创建客户端"""
        api_key = os.getenv("APPLOVIN_REPORT_KEY")
        if not api_key:
            raise ValueError("APPLOVIN_REPORT_KEY environment variable not set")
        return cls(api_key)
    
    def _make_request(self, params: Dict) -> Dict:
        """发送 Reporting API 请求"""
        params["api_key"] = self.api_key
        url = f"{self.BASE_URL}?{urlencode(params)}"
        
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        if params.get("format") == "csv":
            return {"csv_data": response.text}
        
        return response.json()
    
    def query(self,
              start: str,
              end: str,
              columns: Union[str, List[str]],
              report_type: str = "advertiser",
              format: str = "json",
              **kwargs) -> Dict:
        """
        通用查询接口
        
        Args:
            start: 开始日期 (YYYY-MM-DD)
            end: 结束日期 (YYYY-MM-DD 或 "now")
            columns: 列名（预定义集合名称或列名列表）
            report_type: "advertiser" 或 "publisher"
            format: "json" 或 "csv"
            **kwargs: 其他参数（filters, sort, limit, offset, etc.）
            
        Returns:
            API 响应数据
        """
        # 处理预定义列集合
        if isinstance(columns, str) and columns in self.COLUMN_SETS:
            columns = self.COLUMN_SETS[columns]
        
        if isinstance(columns, list):
            columns = ",".join(columns)
        
        params = {
            "start": start,
            "end": end,
            "columns": columns,
            "format": format,
            "report_type": report_type,
            "day_column": "day"  # 默认使用 cohort 数据
        }
        
        # 添加可选参数
        for key, value in kwargs.items():
            if value is not None:
                if key == "filters":
                    # 处理过滤条件
                    for filter_key, filter_value in value.items():
                        if isinstance(filter_value, list):
                            params[f"filter_{filter_key}"] = ",".join(filter_value)
                        else:
                            params[f"filter_{filter_key}"] = filter_value
                elif key == "sort":
                    # 处理排序
                    for sort_key, sort_value in value.items():
                        params[f"sort_{sort_key}"] = sort_value
                else:
                    params[key] = value
        
        # 尝试 advertiser，失败则切换 publisher
        try:
            return self._make_request(params)
        except requests.HTTPError:
            if report_type == "advertiser":
                print("Advertiser report failed, trying publisher...")
                params["report_type"] = "publisher"
                return self._make_request(params)
            raise
    
    def query_campaigns(self,
                       start: str,
                       end: str,
                       columns: Union[str, List[str]] = "full",
                       **filters) -> List[Dict]:
        """
        查询 Campaign 级别数据
        
        Args:
            start: 开始日期
            end: 结束日期
            columns: 列集合或列名列表
            **filters: 过滤条件（platform, country, campaign_id 等）
            
        Returns:
            Campaign 数据列表
        """
        result = self.query(
            start=start,
            end=end,
            columns=columns,
            filters=filters if filters else None,
            sort={"cost": "DESC"}
        )
        
        return self._extract_results(result)
    
    def query_creative_sets(self,
                           start: str,
                           end: str,
                           columns: Union[str, List[str]] = "creative",
                           **filters) -> List[Dict]:
        """
        查询素材组级别数据
        
        Args:
            start: 开始日期
            end: 结束日期
            columns: 列集合或列名列表
            **filters: 过滤条件
            
        Returns:
            素材组数据列表
        """
        # 确保包含 creative_set 相关列
        if isinstance(columns, str):
            columns = self.COLUMN_SETS.get(columns, columns)
        
        cols_set = set(columns if isinstance(columns, list) else columns.split(","))
        required = {"creative_set", "creative_set_id"}
        columns = list(cols_set | required)
        
        result = self.query(
            start=start,
            end=end,
            columns=columns,
            filters=filters if filters else None,
            sort={"cost": "DESC"}
        )
        
        return self._extract_results(result)
    
    def query_by_country(self,
                        start: str,
                        end: str,
                        columns: Union[str, List[str]] = "country",
                        **filters) -> List[Dict]:
        """
        查询分国家数据
        
        Args:
            start: 开始日期
            end: 结束日期
            columns: 列集合或列名列表
            **filters: 过滤条件
            
        Returns:
            分国家数据列表
        """
        # 确保包含 country 列
        if isinstance(columns, str):
            columns = self.COLUMN_SETS.get(columns, columns)
        
        cols_set = set(columns if isinstance(columns, list) else columns.split(","))
        required = {"country"}
        columns = list(cols_set | required)
        
        result = self.query(
            start=start,
            end=end,
            columns=columns,
            filters=filters if filters else None
        )
        
        return self._extract_results(result)
    
    def query_by_channel(self,
                        start: str,
                        end: str,
                        columns: Union[str, List[str]] = "basic",
                        **filters) -> List[Dict]:
        """
        查询分渠道数据
        
        Args:
            start: 开始日期
            end: 结束日期
            columns: 列集合或列名列表
            **filters: 过滤条件
            
        Returns:
            分渠道数据列表
        """
        # 添加 traffic_source 列
        if isinstance(columns, str):
            columns = self.COLUMN_SETS.get(columns, columns)
        
        cols_set = set(columns if isinstance(columns, list) else columns.split(","))
        required = {"traffic_source"}
        columns = list(cols_set | required)
        
        result = self.query(
            start=start,
            end=end,
            columns=columns,
            filters=filters if filters else None
        )
        
        return self._extract_results(result)
    
    def _extract_results(self, result: Dict) -> List[Dict]:
        """从 API 响应中提取结果列表"""
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return result if isinstance(result, list) else []
    
    @staticmethod
    def format_percentage(value: Union[str, float, None]) -> float:
        """
        格式化百分比数据
        
        Reporting API 返回的百分比是原始数值（如 110.12 表示 110.12%）
        需要除以 100 转换为小数（1.1012）
        
        Args:
            value: API 返回的百分比值
            
        Returns:
            格式化后的小数值（如 0.11012 表示 11.012%）
        """
        if value is None:
            return 0.0
        try:
            return float(value) / 100
        except (ValueError, TypeError):
            return 0.0
    
    PERCENTAGE_COLUMNS = {
        'ctr', 'conversion_rate', 'roas_0d', 'roas_1d', 'roas_2d', 'roas_3d', 
        'roas_7d', 'roas_14d', 'roas_28d', 'roas_30d', 'roas_90d', 'roas_1y',
        'iap_roas_0d', 'iap_roas_7d', 'iap_roas_30d',
        'ad_roas_0d', 'ad_roas_7d', 'ad_roas_30d'
    }
    
    def normalize_data(self, data: List[Dict]) -> List[Dict]:
        """
        标准化数据，自动转换百分比字段
        
        Args:
            data: 原始数据列表
            
        Returns:
            标准化后的数据列表
        """
        normalized = []
        for item in data:
            new_item = dict(item)
            for key in new_item:
                if key in self.PERCENTAGE_COLUMNS:
                    new_item[key] = self.format_percentage(new_item[key])
            normalized.append(new_item)
        return normalized
    
    def analyze(self,
               data: List[Dict],
               metric: str,
               threshold: float,
               operator: str = "<",
               min_cost: float = 0.0) -> List[Dict]:
        """
        通用数据分析
        
        Args:
            data: 数据列表
            metric: 指标名称（如 "roas_7d", "average_cpa", "conversion_rate"）
            threshold: 阈值
            operator: 比较操作符（<, >, <=, >=, ==）
            min_cost: 最小消耗过滤
            
        Returns:
            异常数据列表
        """
        anomalies = []
        
        ops = {
            "<": lambda x, y: x < y,
            ">": lambda x, y: x > y,
            "<=": lambda x, y: x <= y,
            ">=": lambda x, y: x >= y,
            "==": lambda x, y: x == y
        }
        
        op_func = ops.get(operator, ops["<"])
        
        for item in data:
            cost = float(item.get("cost", 0))
            value = float(item.get(metric, 0) or 0)
            
            if cost >= min_cost and op_func(value, threshold):
                anomalies.append({
                    **item,
                    "metric": metric,
                    "value": value,
                    "threshold": threshold,
                    "operator": operator
                })
        
        # 按指标值排序
        anomalies.sort(key=lambda x: x["value"])
        return anomalies
    
    def suggest(self,
               analysis_results: Dict[str, List[Dict]],
               context: str = "") -> List[Dict]:
        """
        生成调整建议
        
        Args:
            analysis_results: 分析结果字典，如 {"low_roas": [...], "high_cpi": [...]}
            context: 上下文信息
            
        Returns:
            建议列表
        """
        suggestions = []
        
        for analysis_type, items in analysis_results.items():
            for item in items:
                suggestion = self._create_suggestion(item, analysis_type)
                if suggestion:
                    suggestions.append(suggestion)
        
        return suggestions
    
    def _create_suggestion(self, item: Dict, analysis_type: str) -> Optional[Dict]:
        """根据分析类型创建建议"""
        
        suggestion_map = {
            "low_roas": {
                "action": "pause",
                "priority": "high",
                "reason_template": "ROAS {value:.2%} 低于阈值 {threshold:.2%}"
            },
            "high_cpi": {
                "action": "pause",
                "priority": "high", 
                "reason_template": "CPI ${value:.2f} 高于阈值 ${threshold:.2f}"
            },
            "low_ir": {
                "action": "review",
                "priority": "medium",
                "reason_template": "IR {value:.2%} 低于阈值 {threshold:.2%}"
            },
            "high_cpp": {
                "action": "pause",
                "priority": "high",
                "reason_template": "CPP ${value:.2f} 高于阈值 ${threshold:.2f}"
            },
            "low_country_roas": {
                "action": "exclude_country",
                "priority": "medium",
                "reason_template": "国家 {country} ROAS {value:.2%} 异常"
            }
        }
    
    def fetch_creative_set_dates_from_management_api(
        self,
        campaign_id: str,
        management_api_key: Optional[str] = None
    ) -> Dict[str, str]:
        """
        从 Campaign Management API 获取素材组创建日期
        
        Args:
            campaign_id: Campaign ID
            management_api_key: Campaign Management API Key（可选，默认从环境变量获取）
            
        Returns:
            素材组名称到创建日期的字典 {set_name: date_str}
        """
        if management_api_key is None:
            management_api_key = os.getenv("APPLOVIN_API_KEY")
        
        if not management_api_key:
            print("Warning: APPLOVIN_API_KEY not set, cannot fetch creative set dates from Management API")
            return {}
        
        account_id = os.getenv("APPLOVIN_ACCOUNT_ID", "300004")
        
        # 使用正确的 API 域名和端点
        base_url = "https://api.ads.axon.ai/manage/v1"
        url = f"{base_url}/creative_set/list_by_campaign_id"
        
        headers = {
            "Authorization": management_api_key,
            "Content-Type": "application/json"
        }
        
        params = {
            "account_id": account_id,
            "ids": campaign_id,
            "page": 1,
            "size": 100
        }
        
        set_dates = {}
        total_fetched = 0
        page = 1
        max_pages = 10  # 安全限制
        
        try:
            while page <= max_pages:
                params["page"] = page
                print(f"  Fetching page {page}...")
                
                response = requests.get(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                # 解析返回的素材组列表
                # API 返回格式: {"campaign_count": 1, "creative_set_count": 100, "campaigns": {"campaign_id": [...]}}
                creative_sets = []
                if isinstance(data, dict) and "campaigns" in data:
                    campaigns_data = data.get("campaigns", {})
                    for campaign_sets in campaigns_data.values():
                        if isinstance(campaign_sets, list):
                            creative_sets.extend(campaign_sets)
                elif isinstance(data, list):
                    creative_sets = data
                
                if not creative_sets:
                    break
                
                for creative_set in creative_sets:
                    name = creative_set.get("name", "").strip()  # 去除首尾空格
                    created_at = creative_set.get("created_at", "")
                    if name and created_at:
                        # 转换 ISO 8601 格式为 YYYY-MM-DD
                        try:
                            date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            set_dates[name] = date_obj.strftime('%Y-%m-%d')
                        except:
                            set_dates[name] = created_at[:10] if len(created_at) >= 10 else created_at
                
                total_fetched += len(creative_sets)
                print(f"    Page {page}: {len(creative_sets)} sets (total: {len(set_dates)} with dates)")
                
                # 检查是否还有更多页
                # API 返回的 creative_set_count 可能是该页的数量，不是总数
                # 所以用实际返回的数据量来判断
                if len(creative_sets) < params["size"]:
                    print(f"    Last page reached (returned {len(creative_sets)} < size {params['size']})")
                    break
                
                page += 1
                if page > max_pages:
                    print(f"    Reached max pages limit ({max_pages})")
                    break
            
            print(f"\n✅ Fetched {len(set_dates)} creative set dates from Management API (total: {total_fetched} sets)")
            
        except Exception as e:
            print(f"Warning: Failed to fetch creative set dates: {e}")
        
        return set_dates
    
    def analyze_creative_sets(self,
                               campaign_id: str,
                               start_date: str,
                               end_date: str,
                               volume_threshold: float,
                               set_dates: Optional[Dict[str, str]] = None,
                               today: Optional[datetime] = None,
                               auto_fetch_dates: bool = True) -> Dict:
        """
        素材组分析 - 4步分类法
        
        Args:
            campaign_id: Campaign ID
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            volume_threshold: 起量消耗判定阈值（A类/B类划分门槛）
            set_dates: 素材组创建日期字典 {set_name: date_str}，如果为 None 且 auto_fetch_dates=True 则自动获取
            today: 分析日期，默认为今天
            auto_fetch_dates: 是否自动从 Management API 获取创建日期
            
        Returns:
            分析结果字典，包含分类和建议
        """
        if today is None:
            today = datetime.now()
        
        days_14_ago = today - timedelta(days=14)
        days_7_ago = today - timedelta(days=7)  # 新素材门槛改为近7天
        days_30_ago = today - timedelta(days=30)
        
        # 自动获取素材组创建日期
        if set_dates is None and auto_fetch_dates:
            print("Fetching creative set dates from Management API...")
            set_dates = self.fetch_creative_set_dates_from_management_api(campaign_id)
        elif set_dates is None:
            set_dates = {}
        
        # 查询 Campaign 数据
        campaign_columns = ['campaign', 'campaign_id', 'cost', 'conversions', 'roas_28d']
        campaign_data = self.query(
            start=start_date,
            end=end_date,
            columns=campaign_columns,
            filters={'campaign_id': [campaign_id]}
        )
        campaign_results = self._extract_results(campaign_data)
        
        if not campaign_results:
            return {'error': 'Campaign not found'}
        
        campaign = campaign_results[0]
        campaign_roas_28d = float(campaign.get('roas_28d', 0) or 0) / 100
        campaign_name = campaign['campaign']
        
        # 查询素材组数据 - 获取更多指标
        print("\nQuerying creative sets data from Reporting API...")
        creative_columns = [
            'creative_set', 'creative_set_id', 'cost', 'conversions',
            'roas_0d', 'roas_28d', 'cpp_0d', 'cpp_28d',
            'conversion_rate', 'average_cpa', 'unique_purchasers_28d'
        ]
        
        # 遍历所有分页获取素材组数据
        all_creative_results = []
        page = 1
        max_pages = 20
        
        while page <= max_pages:
            print(f"  Fetching page {page}...")
            creative_data = self.query(
                start=start_date,
                end=end_date,
                columns=creative_columns,
                filters={'campaign_id': [campaign_id]},
                limit=1000,
                offset=(page - 1) * 1000
            )
            creative_results = self._extract_results(creative_data)
            
            if not creative_results:
                break
            
            all_creative_results.extend(creative_results)
            print(f"    Got {len(creative_results)} sets (total: {len(all_creative_results)})")
            
            if len(creative_results) < 1000:
                break
            
            page += 1
        
        print(f"\n✅ Total creative sets from Reporting API: {len(all_creative_results)}")
        print(f"   (Reporting API only returns sets with data in the date range)")
        
        # 过滤前七天有消耗的素材组
        active_sets = [c for c in all_creative_results if float(c.get('cost', 0)) > 0]
        print(f"✅ Sets with consumption (> $0): {len(active_sets)}")
        
        # 注意：Reporting API 只返回有消耗的素材组
        # Management API 显示总共有 100 个素材组，但只有 31 个在前七天有消耗数据
        
        # 合并创建日期并处理指标
        print("\nProcessing metrics and merging with Management API data...")
        
        for s in active_sets:
            set_name = s['creative_set']
            s['created_date'] = set_dates.get(set_name, 'unknown')
            
            # 处理百分比数据（除以100）
            s['roas_0d'] = float(s.get('roas_0d', 0) or 0) / 100
            s['roas_28d'] = float(s.get('roas_28d', 0) or 0) / 100
            s['conversion_rate'] = float(s.get('conversion_rate', 0) or 0) / 100
            
            # 处理金额数据
            s['cost_7d'] = float(s.get('cost', 0))
            s['average_cpa'] = float(s.get('average_cpa', 0))  # CPI
            s['cpp_0d'] = float(s.get('cpp_0d', 0))
            s['cpp_28d'] = float(s.get('cpp_28d', 0))
            
            # 其他指标
            s['conversions'] = int(float(s.get('conversions', 0)))
            s['unique_purchasers_28d'] = int(float(s.get('unique_purchasers_28d', 0)))
        
        # 按消耗降序排列
        active_sets.sort(key=lambda x: x['cost_7d'], reverse=True)
        print(f"✅ Sorted by cost (descending)")
        
        # Step 1: 筛选低于 Campaign ROAS
        low_roas_sets = [s for s in active_sets if s['roas_28d'] < campaign_roas_28d]
        
        # Step 2: 按消耗分类
        class_a = [s for s in low_roas_sets if s['cost_7d'] >= volume_threshold]
        class_b = [s for s in low_roas_sets if s['cost_7d'] < volume_threshold]
        
        # Step 3: A类细分
        threshold_0_5 = campaign_roas_28d * 0.5
        a1, a2, a3 = [], [], []
        
        for s in class_a:
            created_str = s.get('created_date', 'unknown')
            if created_str != 'unknown':
                created_date = datetime.strptime(created_str, '%Y-%m-%d')
            else:
                created_date = datetime(2020, 1, 1)
            
            is_recent_14d = created_date >= days_14_ago
            is_recent_7d = created_date >= days_7_ago  # 新素材门槛改为近7天
            
            s['is_recent_14d'] = is_recent_14d
            s['is_recent_7d'] = is_recent_7d
            
            if is_recent_14d:
                if s['roas_28d'] >= threshold_0_5:
                    s['category'] = 'A1'
                    s['label'] = '起量+学习中，ROAS表现一般'
                    s['action'] = '继续观察'
                    a1.append(s)
                else:
                    # 新素材逻辑（近7天）
                    if is_recent_7d:
                        s['category'] = 'A2-新素材'
                        s['label'] = '起量，但ROAS表现差，新素材'
                        s['action'] = '继续观察'
                    else:
                        s['category'] = 'A2'
                        s['label'] = '起量，但ROAS表现差'
                        s['action'] = '暂停投放'
                    a2.append(s)
            else:
                # A3 新素材逻辑（近7天）
                if is_recent_7d:
                    s['category'] = 'A3-新素材'
                    s['label'] = '起量，且学习完成，但ROAS表现差，新素材'
                    s['action'] = '继续观察'
                else:
                    s['category'] = 'A3'
                    s['label'] = '起量，且学习完成，但ROAS表现差'
                    s['action'] = '暂停投放'
                a3.append(s)
        
        # Step 4: B类细分
        b1, b2 = [], []
        
        for s in class_b:
            created_str = s.get('created_date', 'unknown')
            if created_str != 'unknown':
                created_date = datetime.strptime(created_str, '%Y-%m-%d')
            else:
                created_date = datetime(2020, 1, 1)
            
            is_recent_30d = created_date >= days_30_ago
            s['is_recent_30d'] = is_recent_30d
            
            # 如果没有创建日期，视为旧素材（不显示"可能已删除"）
            
            if is_recent_30d and created_str != 'unknown':
                s['category'] = 'B1'
                s['label'] = '不起量+学习中，ROAS表现一般'
                s['action'] = '继续观察'
                b1.append(s)
            else:
                s['category'] = 'B2'
                s['label'] = '不起量，且ROAS表现一般'
                s['action'] = '暂停投放'
                b2.append(s)
        
        return {
            'campaign_name': campaign_name,
            'campaign_id': campaign_id,
            'campaign_roas_28d': campaign_roas_28d,
            'volume_threshold': volume_threshold,
            'analysis_period': f'{start_date} to {end_date}',
            'total_sets': len(active_sets),
            'low_roas_sets': len(low_roas_sets),
            'all_sets': active_sets,  # 包含所有素材组（用于筛选正常素材组）
            'class_a': class_a,
            'class_b': class_b,
            'a1': a1,
            'a2': a2,
            'a3': a3,
            'b1': b1,
            'b2': b2,
            'summary': {
                'pause': len([s for s in a2 + a3 if s['action'] == '暂停投放']) + len(b2),
                'observe': len(a1) + len([s for s in a2 + a3 if s['action'] == '继续观察']) + len(b1)
            }
        }
    
    def _create_suggestion(self, item: Dict, analysis_type: str) -> Optional[Dict]:
        """根据分析类型创建建议"""
        
        suggestion_map = {
            "low_roas": {
                "action": "pause",
                "priority": "high",
                "reason_template": "ROAS {value:.2%} 低于阈值 {threshold:.2%}"
            },
            "high_cpi": {
                "action": "pause",
                "priority": "high", 
                "reason_template": "CPI ${value:.2f} 高于阈值 ${threshold:.2f}"
            },
            "low_ir": {
                "action": "review",
                "priority": "medium",
                "reason_template": "IR {value:.2%} 低于阈值 {threshold:.2%}"
            },
            "high_cpp": {
                "action": "pause",
                "priority": "high",
                "reason_template": "CPP ${value:.2f} 高于阈值 ${threshold:.2f}"
            },
            "low_country_roas": {
                "action": "exclude_country",
                "priority": "medium",
                "reason_template": "国家 {country} ROAS {value:.2%} 异常"
            }
        }
        
        config = suggestion_map.get(analysis_type)
        if not config:
            return None
        
        return {
            "type": item.get("campaign_id") and "campaign" or "creative_set",
            "id": item.get("campaign_id") or item.get("creative_set_id"),
            "name": item.get("campaign") or item.get("creative_set"),
            "action": config["action"],
            "priority": config["priority"],
            "reason": config["reason_template"].format(**item),
            "cost": item.get("cost", 0),
            "metric": item.get("metric"),
            "value": item.get("value"),
            "analysis_type": analysis_type
        }
    
    def analyze_campaign_bid_overall(self,
                                    campaign_id: str,
                                    start_date: str,
                                    end_date: str,
                                    potential_data: Optional[Dict] = None) -> Dict:
        """
        整体出价分析
        
        分析规则：
        1. 读取 Campaign 当前出价（从 Management API）
        2. 读取历史一周的 spend、budget
        3. 读取 potential 数据（从邮件或传入的参数）
        4. 计算花超比例 (potential/budget) 和实际花费比例 (spend/budget)
        5. 根据规则生成备注和结论
        
        Args:
            campaign_id: Campaign ID
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            potential_data: potential 数据字典 {date: {'potential': value, 'note': ''}}
                           如果为 None，则 potential = budget
            
        Returns:
            出价分析结果
        """
        from datetime import datetime, timedelta
        
        print(f"\n{'='*100}")
        print("CAMPAIGN BID ANALYSIS (Overall)")
        print(f"{'='*100}")
        print(f"Campaign ID: {campaign_id}")
        print(f"Date Range: {start_date} to {end_date}")
        print()
        
        # 1. 获取 Campaign 当前出价（从 Management API）
        print("Fetching campaign bid info from Management API...")
        # 这里需要从 Management API 获取，暂时使用默认值
        # 实际实现时需要调用 Management API
        campaign_goal = {
            'goal_type': 'CHK_ROAS',
            'target_value': 0.147,  # 平均 goal 值
            'roas_day_target': 'DAY28'
        }
        
        # 2. 获取历史 spend 数据
        print("Fetching historical spend data...")
        daily_data = []
        current_date = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        while current_date <= end:
            date_str = current_date.strftime('%Y-%m-%d')
            
            # 查询单日数据
            data = self.query(
                start=date_str,
                end=date_str,
                columns=['day', 'campaign', 'campaign_id', 'cost'],
                filters={'campaign_id': [campaign_id]},
                report_type='advertiser'
            )
            results = self._extract_results(data)
            
            spend = sum(float(r.get('cost', 0)) for r in results)
            
            daily_data.append({
                'date': date_str,
                'spend': spend
            })
            
            current_date += timedelta(days=1)
        
        # 3. 获取 Campaign budget（从 Management API）
        # 这里使用默认值，实际需要从 API 获取
        daily_budget = 3000  # 需要从 Management API 获取
        
        # 4. 计算分析
        analysis_results = []
        for d in daily_data:
            date = d['date']
            spend = d['spend']
            budget = daily_budget
            
            # 获取 potential
            if potential_data and date in potential_data:
                potential_info = potential_data[date]
                potential = potential_info.get('potential', budget)
                potential_note = potential_info.get('note', '')
            else:
                potential = budget
                potential_note = '当日没有potential'
            
            # 计算比例
            potential_budget_ratio = (potential / budget) * 100 if budget > 0 else 0
            spend_budget_ratio = (spend / budget) * 100 if budget > 0 else 0
            
            # 花超比例备注
            if potential_budget_ratio > 160:
                potential_remark = '出价偏低，需要调整'
            elif potential_budget_ratio >= 130:
                potential_remark = '出价略低，需要关注'
            else:
                potential_remark = '出价正常，无需调整'
            
            # 实际花费比例备注
            if spend_budget_ratio <= 75:
                spend_remark = '出价偏高，需要调整'
            else:
                spend_remark = '出价正常'
            
            # 综合备注
            if potential_note and '没有potential' not in potential_note:
                remark = f'{potential_remark} | {spend_remark} | {potential_note}'
            else:
                remark = f'{potential_remark} | {spend_remark}'
            
            analysis_results.append({
                'date': date,
                'budget': budget,
                'potential': potential,
                'potential_budget_ratio': potential_budget_ratio,
                'spend': spend,
                'spend_budget_ratio': spend_budget_ratio,
                'remark': remark
            })
        
        # 5. 计算汇总
        if analysis_results:
            summary = {
                'date': '汇总（平均值）',
                'budget': sum(r['budget'] for r in analysis_results) / len(analysis_results),
                'potential': sum(r['potential'] for r in analysis_results) / len(analysis_results),
                'potential_budget_ratio': sum(r['potential_budget_ratio'] for r in analysis_results) / len(analysis_results),
                'spend': sum(r['spend'] for r in analysis_results) / len(analysis_results),
                'spend_budget_ratio': sum(r['spend_budget_ratio'] for r in analysis_results) / len(analysis_results),
                'remark': ''
            }
            
            # 汇总备注
            if summary['potential_budget_ratio'] > 160:
                summary_potential_remark = '出价偏低，需要调整'
            elif summary['potential_budget_ratio'] >= 130:
                summary_potential_remark = '出价略低，需要关注'
            else:
                summary_potential_remark = '出价正常，无需调整'
            
            if summary['spend_budget_ratio'] <= 75:
                summary_spend_remark = '出价偏高，需要调整'
            else:
                summary_spend_remark = '出价正常'
            
            summary['remark'] = f'{summary_potential_remark} | {summary_spend_remark}'
        else:
            summary = {}
        
        return {
            'campaign_id': campaign_id,
            'campaign_goal': campaign_goal,
            'daily_budget': daily_budget,
            'analysis_period': f'{start_date} to {end_date}',
            'daily_analysis': analysis_results,
            'summary': summary
        }


    def analyze_country_bid(self,
                           campaign_id: str,
                           t3_countries: Optional[set] = None,
                           config: Optional[Dict] = None) -> Dict:
        """
        分国家出价分析
        
        规则：
        1. 暂停：双周期ROI < 30%，且（属于T3 或 非T3但近14天消耗 >= $1000）
        2. 未起量：双周期ROI < 30%，非T3，且近14天消耗 < $1000
        3. T1特殊：如果建议暂停的国家属于T1，改为提Goal
        4. 提Goal：30% <= 双周期ROI < 70%
        5. 观察：70% <= 双周期ROI < 110%
        6. 降Goal：双周期ROI >= 110%
        
        Args:
            campaign_id: Campaign ID
            t3_countries: T3国家集合（可选，默认使用内置列表）
            config: 配置参数（可选）
            
        Returns:
            分析结果字典
        """
        cfg = config or self.COUNTRY_BID_CONFIG
        
        # 计算日期范围
        today = datetime.now()
        short_start = (today - timedelta(days=cfg['short_period_days'])).strftime('%Y-%m-%d')
        short_end = today.strftime('%Y-%m-%d')
        long_start = (today - timedelta(days=cfg['long_period_days'])).strftime('%Y-%m-%d')
        long_end = today.strftime('%Y-%m-%d')
        
        # 加载T3国家
        if t3_countries is None:
            if self.T3_COUNTRIES is None:
                # 尝试从文件加载
                try:
                    with open('/tmp/t3_countries.json', 'r') as f:
                        self.T3_COUNTRIES = set(json.load(f))
                except:
                    self.T3_COUNTRIES = set()
            t3_set = self.T3_COUNTRIES
        else:
            t3_set = t3_countries
        
        t1_set = self.T1_COUNTRIES
        
        # 查询数据
        short_data = self.query(
            start=short_start,
            end=short_end,
            columns=['day', 'country', 'cost', 'roas_7d'],
            filters={'campaign_id': [campaign_id]},
            report_type='advertiser'
        )
        short_results = self._extract_results(short_data)
        
        long_data = self.query(
            start=long_start,
            end=long_end,
            columns=['day', 'country', 'cost', 'roas_7d'],
            filters={'campaign_id': [campaign_id]},
            report_type='advertiser'
        )
        long_results = self._extract_results(long_data)
        
        # 计算指标
        def calc_metrics(data):
            country_stats = defaultdict(lambda: {'cost': 0, 'roas_sum': 0})
            total_cost = total_roas_sum = 0
            for r in data:
                country = r.get('country', 'Unknown')
                cost = float(r.get('cost', 0))
                roas = float(r.get('roas_7d', 0))
                if cost > 0:
                    country_stats[country]['cost'] += cost
                    country_stats[country]['roas_sum'] += roas * cost
                    total_cost += cost
                    total_roas_sum += roas * cost
            
            result = {}
            for c, s in country_stats.items():
                if s['cost'] > 0:
                    result[c] = {'cost': s['cost'], 'roas': s['roas_sum'] / s['cost']}
            bench = total_roas_sum / total_cost if total_cost > 0 else 0
            return result, bench
        
        country_short, bench_short = calc_metrics(short_results)
        country_long, bench_long = calc_metrics(long_results)
        
        # 分析每个国家
        all_countries = set(country_short.keys()) | set(country_long.keys())
        results = []
        
        for country in all_countries:
            cost_s = country_short.get(country, {}).get('cost', 0)
            cost_l = country_long.get(country, {}).get('cost', 0)
            roas_s = country_short.get(country, {}).get('roas', 0)
            roas_l = country_long.get(country, {}).get('roas', 0)
            
            ratio_s = roas_s / bench_short if bench_short > 0 else 0
            ratio_l = roas_l / bench_long if bench_long > 0 else 0
            
            is_t3 = country.lower() in t3_set
            is_t1 = country.lower() in t1_set
            
            # 判断建议
            if ratio_s < cfg['pause_threshold_ratio'] and ratio_l < cfg['pause_threshold_ratio']:
                if is_t3:
                    base_action = '暂停'
                elif cost_s >= cfg['pause_min_spend']:
                    base_action = '暂停'
                else:
                    base_action = '未起量，还需观察'
            elif ratio_s < cfg['increase_goal_ratio'] and ratio_l < cfg['increase_goal_ratio']:
                base_action = '提Goal'
            elif ratio_s >= cfg['decrease_goal_ratio'] and ratio_l >= cfg['decrease_goal_ratio']:
                base_action = '降Goal'
            else:
                base_action = '观察'
            
            # T1特殊处理
            if is_t1 and base_action == '暂停':
                action = '提Goal'
                note = 'T1国家，原建议暂停，改为提Goal'
            else:
                action = base_action
                note = ''
            
            results.append({
                'country': country,
                'cost_short': round(cost_s),
                'cost_long': round(cost_l),
                'roas_short': roas_s,
                'roas_long': roas_l,
                'bench_short': bench_short,
                'bench_long': bench_long,
                'is_t3': is_t3,
                'is_t1': is_t1,
                'action': action,
                'note': note
            })
        
        # 按消耗降序排序
        results.sort(key=lambda x: x['cost_short'], reverse=True)
        
        # 分组
        groups = {
            'pause': [r for r in results if r['action'] == '暂停'],
            'not_started': [r for r in results if r['action'] == '未起量，还需观察'],
            'increase': [r for r in results if r['action'] == '提Goal'],
            'decrease': [r for r in results if r['action'] == '降Goal'],
            'observe': [r for r in results if r['action'] == '观察']
        }
        
        return {
            'campaign_id': campaign_id,
            'benchmark': {'short': bench_short, 'long': bench_long},
            'config': cfg,
            'countries': results,
            'summary': {k: len(v) for k, v in groups.items()},
            'groups': groups
        }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python applovin_analytics.py <command> [options]")
        print("Commands:")
        print("  query <start> <end> <columns>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    try:
        analytics = ApplovinAnalytics.from_env()
        
        if command == "query":
            if len(sys.argv) < 5:
                print("Usage: query <start> <end> <columns>")
                sys.exit(1)
            
            result = analytics.query(
                start=sys.argv[2],
                end=sys.argv[3],
                columns=sys.argv[4]
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
