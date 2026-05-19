#!/usr/bin/env python3
"""
APL 素材上传 V2 - 从 DAP 同步素材到 Applovin

改进版：直接使用 DAP HTTP API，不依赖 data skill 的文本解析
"""

import argparse
import json
import os
import sys
import requests
from typing import List, Dict, Optional


def query_dap_materials(
    game_id: int,
    material_type: str = "video",
    language: Optional[str] = None,
    ratio: Optional[str] = None,
    material_class: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page_size: int = 1000
) -> List[Dict]:
    """使用 DAP HTTP API 查询素材"""
    
    token = os.environ.get('DAP_API_TOKEN')
    if not token:
        print("  ⚠️ 未设置 DAP_API_TOKEN")
        return []
    
    print(f"\n{'='*60}")
    print("查询 DAP 素材库")
    print(f"{'='*60}")
    print(f"  项目 ID: {game_id}")
    print(f"  类型: {material_type}")
    print(f"  语系: {language or '全部'}")
    print(f"  尺寸: {ratio or '全部'}")
    print(f"  大类: {material_class or '全部'}")
    print(f"  时间: {start_date or '不限'} ~ {end_date or '不限'}")
    
    url = "https://dap.lilithgame.com/dapper/api/material/v2/list/materials"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {token}"
    }
    
    all_materials = []
    page = 1
    
    while True:
        payload = {
            "game_id": game_id,
            "type": material_type,
            "order": "upload_datetime",
            "sort": "desc",
            "page": page,
            "page_size": page_size
        }
        
        if language:
            payload["language"] = language
        if ratio:
            payload["ratio"] = ratio
        if material_class:
            payload["material_class"] = material_class
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            data = response.json()
            
            if data.get('code') != 0:
                print(f"  ❌ API 错误: {data.get('message', 'Unknown')}")
                break
            
            items = data.get('data', {}).get('items', [])
            if not items:
                break
            
            # 筛选日期
            for item in items:
                upload_time = item.get('upload_datetime', '')
                if upload_time:
                    upload_date = upload_time.split(' ')[0] if ' ' in upload_time else upload_time[:10]
                    if start_date and end_date:
                        if start_date <= upload_date <= end_date:
                            all_materials.append(item)
                    else:
                        all_materials.append(item)
            
            print(f"  第 {page} 页: {len(items)} 条 (累计 {len(all_materials)} 条)")
            
            total = data.get('data', {}).get('total', 0)
            if page * page_size >= total:
                break
            
            page += 1
            if page > 100:
                break
                
        except Exception as e:
            print(f"  ❌ 请求失败: {e}")
            break
    
    print(f"\n  ✅ 找到 {len(all_materials)} 条素材")
    return all_materials


def display_materials(materials: List[Dict]):
    """显示素材列表"""
    if not materials:
        print("\n  没有找到素材")
        return
    
    print(f"\n{'='*60}")
    print("素材列表")
    print(f"{'='*60}")
    
    # 按日期分组
    date_groups = {}
    for m in materials:
        upload_time = m.get('upload_datetime', '')
        if upload_time:
            date = upload_time.split(' ')[0] if ' ' in upload_time else upload_time[:10]
            date_groups.setdefault(date, []).append(m)
    
    print(f"\n总计: {len(materials)} 条\n")
    
    print("按日期分布:")
    for date in sorted(date_groups.keys()):
        print(f"  {date}: {len(date_groups[date])} 条")
    
    print("\n按大类分布:")
    class_groups = {}
    for m in materials:
        cls = m.get('material_class_name', '未分类')
        class_groups.setdefault(cls, []).append(m)
    
    for cls, items in sorted(class_groups.items(), key=lambda x: -len(x[1])):
        print(f"  {cls}: {len(items)} 条")
    
    print("\n前 10 条素材:")
    print("-" * 60)
    for i, m in enumerate(materials[:10], 1):
        print(f"{i}. {m.get('name', 'N/A')}")
        print(f"   ID: {m.get('id', 'N/A')}")
        print(f"   时间: {m.get('upload_datetime', 'N/A')}")
        print(f"   大类: {m.get('material_class_name', 'N/A')}")
        print()


def main():
    parser = argparse.ArgumentParser(description="APL 素材上传 V2")
    parser.add_argument("--game-id", type=int, required=True, help="项目 ID")
    parser.add_argument("--type", default="video", help="素材类型")
    parser.add_argument("--language", help="语系")
    parser.add_argument("--ratio", help="尺寸")
    parser.add_argument("--material-class", help="素材大类")
    parser.add_argument("--start-date", required=True, help="开始日期")
    parser.add_argument("--end-date", required=True, help="结束日期")
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print("APL 素材上传 V2")
    print(f"{'='*60}")
    
    materials = query_dap_materials(
        game_id=args.game_id,
        material_type=args.type,
        language=args.language,
        ratio=args.ratio,
        material_class=args.material_class,
        start_date=args.start_date,
        end_date=args.end_date
    )
    
    if materials:
        display_materials(materials)
    else:
        print("\n❌ 未找到素材")
        print("\n可能原因：")
        print("  1. 筛选条件过于严格")
        print("  2. 指定时间范围内没有素材")
        print("  3. 未设置 DAP_API_TOKEN")


if __name__ == "__main__":
    main()
