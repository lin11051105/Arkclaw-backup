#!/usr/bin/env python3
"""
APL 素材上传 - 从 DAP 素材库同步素材到 Applovin

功能流程：
1. 根据用户筛选条件从 DAP 查询素材
2. 获取素材的本地同步文件夹地址
3. 从 Windows 同步文件夹复制素材到本地
4. 上传素材到 Applovin
5. 同步过审状态
"""

import argparse
import json
import os
import sys
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# 导入 Applovin 管理器
from applovin_manager_full import ApplovinCampaignManager


def get_user_confirmation(operation_name: str, details: Dict) -> bool:
    """获取用户确认"""
    print("\n" + "=" * 60)
    print("⚠️  即将执行素材上传操作，请确认")
    print("=" * 60)
    print(f"\n📌 操作类型: {operation_name}")
    
    for key, value in details.items():
        print(f"📌 {key}: {value}")
    
    print("\n" + "=" * 60)
    print("请确认是否执行？")
    print('  ✅ 确认执行: 输入 "可以" / "确认" / "yes" / "ok"')
    print('  ❌ 取消操作: 输入其他任何内容')
    print("=" * 60)
    
    try:
        user_input = input("\n您的选择: ").strip().lower()
    except KeyboardInterrupt:
        print("\n❌ 操作已取消")
        return False
    
    confirm_keywords = ['可以', '确认', 'yes', 'ok', 'y', '是', '执行', '同意']
    if any(kw in user_input for kw in confirm_keywords):
        print("✅ 用户已确认")
        return True
    else:
        print("❌ 操作已取消")
        return False


def query_dap_materials_via_cli(
    game_id: int,
    material_type: str = "video",
    language: Optional[str] = None,
    ratio: Optional[str] = None,
    material_class: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page_size: int = 1000
) -> List[Dict]:
    """
    使用 data skill CLI 查询 DAP 素材库
    """
    print(f"\n{'='*60}")
    print("步骤 1: 查询 DAP 素材库")
    print(f"{'='*60}")
    print(f"  项目 ID: {game_id}")
    print(f"  类型: {material_type}")
    print(f"  语系: {language or '全部'}")
    print(f"  尺寸: {ratio or '全部'}")
    print(f"  大类: {material_class or '全部'}")
    print(f"  时间: {start_date or '不限'} ~ {end_date or '不限'}")
    print(f"  page_size: {page_size}")
    
    # 构建查询消息
    filter_desc = f"""查询 Wgame（game_id={game_id}）的素材，条件如下：
- 类型: {material_type}
- 语系: {language or '全部'}
- 尺寸: {ratio or '全部'}
- 大类: {material_class or '全部'}
- 时间范围: {start_date} ~ {end_date}

请使用 mcp__dapper__list_materials 工具，参数：
- game_id: {game_id}
- type: {material_type}
{f'- language: {language}' if language else ''}
{f'- ratio: {ratio}' if ratio else ''}
- order: upload_datetime
- sort: desc
- page_size: {page_size}

需要遍历所有分页获取完整数据，然后筛选出上传日期在 {start_date} ~ {end_date} 之间的素材。

返回每个素材的：id, name, material_class_name, upload_datetime, file_path（Windows 同步文件夹地址）
"""
    
    # 调用 data skill
    cmd = [
        "atlas-skillhub", "gateway", "call-a2a",
        "--service", "data-analysis",
        "--timeout", "600",
        "--message", filter_desc
    ]
    
    print(f"\n  正在调用 data skill 查询...")
    print(f"  命令: {' '.join(cmd[:6])}...")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        output = result.stdout + result.stderr
        
        # 检查是否有错误
        if result.returncode != 0:
            print(f"  ❌ 查询失败: {output[:500]}")
            return []
        
        print(f"  ✅ 查询完成")
        
        # 从输出中解析素材数量
        # data skill 返回的是文本报告，我们需要从中提取关键信息
        return _parse_materials_from_output(output, start_date, end_date)
        
    except subprocess.TimeoutExpired:
        print(f"  ❌ 查询超时")
        return []
    except Exception as e:
        print(f"  ❌ 查询异常: {e}")
        return []


def _parse_materials_from_output(output: str, start_date: str, end_date: str) -> List[Dict]:
    """
    从 data skill 输出中解析素材列表
    
    data skill 返回的是 Markdown 格式的文本报告，包含表格和列表
    我们需要从中提取素材的详细信息
    """
    materials = []
    
    print(f"\n  解析查询结果...")
    
    # 首先检查是否有"未找到"或"没有"等关键词
    if "未找到" in output or "没有找到" in output or "没有符合条件的" in output:
        print(f"  ⚠️ 未找到符合条件的素材")
        return []
    
    # 尝试从输出中提取素材总数
    total_match = None
    for line in output.split('\n'):
        if '总计' in line and '条' in line:
            # 尝试提取数字
            import re
            numbers = re.findall(r'\d+', line)
            if numbers:
                total_match = int(numbers[0])
                print(f"  找到素材总数: {total_match}")
                break
    
    # 由于 data skill 返回的是文本报告，而不是结构化数据
    # 我们需要使用另一种方法来获取素材列表
    
    # 方法：使用正则表达式提取素材信息
    # 典型的素材信息格式：
    # - 素材名称: xxx
    # - 素材ID: xxx
    # - 上传时间: xxx
    
    # 查找所有可能的素材条目
    lines = output.split('\n')
    current_material = {}
    
    for line in lines:
        line = line.strip()
        
        # 尝试匹配素材名称（通常在列表中）
        if line.startswith('- ') or line.startswith('* '):
            # 可能是素材列表项
            content = line[2:].strip()
            
            # 尝试提取素材信息
            # 格式可能是：素材名 (ID: xxx, 时间: xxx)
            import re
            
            # 匹配类似 "WGAME_V_EN_AI_xxx_xxx (ID: 12345)" 的格式
            match = re.match(r'(.+?)\s*\(ID:\s*(\d+)', content)
            if match:
                name = match.group(1).strip()
                material_id = match.group(2)
                
                # 构建素材信息
                material = {
                    'id': material_id,
                    'name': name,
                    'material_class_name': 'AI',  # 从查询条件推断
                    'upload_datetime': '',  # 需要从其他信息中提取
                    'sync_folder': '',  # 需要从其他信息中提取
                    'file_path': ''  # 需要从其他信息中提取
                }
                materials.append(material)
    
    # 如果上面的方法没有提取到素材，说明 data skill 返回的格式不是我们预期的
    # 这时候我们需要使用备选方案：直接调用 DAP HTTP API
    
    if not materials and total_match and total_match > 0:
        print(f"\n  ⚠️ 无法从文本报告中解析素材详情")
        print(f"  但查询显示共有 {total_match} 条素材")
        print(f"  建议使用备选方案：直接调用 DAP HTTP API")
        
        # 返回一个模拟结果，表示需要进一步处理
        return [{"_note": "需要直接调用 DAP HTTP API", "expected_count": total_match}]
    
    print(f"\n  成功解析 {len(materials)} 条素材")
    return materials


def query_dap_materials_direct(
    game_id: int,
    material_type: str = "video",
    language: Optional[str] = None,
    ratio: Optional[str] = None,
    material_class: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page_size: int = 1000
) -> List[Dict]:
    """
    直接使用 DAP HTTP API 查询素材（备选方案）
    
    当 data skill 返回文本报告无法解析时，使用此函数直接调用 DAP API
    """
    import requests
    import os
    
    # 获取 DAP API Token
    token = os.environ.get('DAP_API_TOKEN')
    if not token:
        print("  ⚠️ 未设置 DAP_API_TOKEN，无法直接调用 DAP API")
        return []
    
    print(f"\n  使用备选方案：直接调用 DAP HTTP API")
    
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
                print(f"  ❌ DAP API 错误: {data.get('message', 'Unknown')}")
                break
            
            items = data.get('data', {}).get('items', [])
            if not items:
                break
            
            # 筛选日期范围内的素材
            for item in items:
                upload_time = item.get('upload_datetime', '')
                if upload_time:
                    # 提取日期部分
                    upload_date = upload_time.split(' ')[0] if ' ' in upload_time else upload_time[:10]
                    if start_date and end_date:
                        if start_date <= upload_date <= end_date:
                            all_materials.append(item)
                    else:
                        all_materials.append(item)
            
            # 检查是否还有更多页
            total = data.get('data', {}).get('total', 0)
            if page * page_size >= total:
                break
            
            page += 1
            if page > 100:  # 安全限制
                break
                
            print(f"    第 {page-1} 页: {len(items)} 条素材")
            
        except Exception as e:
            print(f"  ❌ DAP API 请求失败: {e}")
            break
    
    print(f"  ✅ 从 DAP API 获取到 {len(all_materials)} 条素材")
    return all_materials


def copy_materials_from_sync_folder(
    materials: List[Dict],
    local_dest_dir: str = "/tmp/apl_upload"
) -> List[Tuple[Dict, str]]:
    """
    步骤 3: 从 Windows 同步文件夹复制素材到本地
    """
    print(f"\n{'='*60}")
    print("步骤 3: 复制素材到本地")
    print(f"{'='*60}")
    
    if not materials:
        print("  没有需要复制的素材")
        return []
    
    os.makedirs(local_dest_dir, exist_ok=True)
    print(f"  本地目标目录: {local_dest_dir}")
    
    copied = []
    
    for material in materials:
        sync_folder = material.get("sync_folder") or material.get("file_path")
        file_name = material.get("file_name") or material.get("name")
        
        if not sync_folder or not file_name:
            print(f"  ⚠️ 素材 {material.get('id', 'unknown')} 缺少路径信息，跳过")
            continue
        
        # 构建路径
        src_path = os.path.join(sync_folder, file_name)
        dest_path = os.path.join(local_dest_dir, file_name)
        
        print(f"\n  素材: {file_name}")
        print(f"    源路径: {src_path}")
        print(f"    目标路径: {dest_path}")
        
        # 检查源文件是否存在
        if not os.path.exists(src_path):
            print(f"    ⚠️ 源文件不存在，跳过")
            continue
        
        # 复制文件
        try:
            import shutil
            shutil.copy2(src_path, dest_path)
            copied.append((material, dest_path))
            print(f"    ✅ 已复制")
        except Exception as e:
            print(f"    ❌ 复制失败: {e}")
    
    print(f"\n  总计: {len(copied)}/{len(materials)} 个素材已复制")
    
    return copied


def confirm_materials(
    materials: List[Tuple[Dict, str]]
) -> bool:
    """
    步骤 4: 和用户确认素材
    """
    print(f"\n{'='*60}")
    print("步骤 4: 素材确认")
    print(f"{'='*60}")
    
    if not materials:
        print("  没有可确认的素材")
        return False
    
    print(f"\n  找到 {len(materials)} 个素材:\n")
    
    for i, (material, local_path) in enumerate(materials, 1):
        print(f"  {i}. {material.get('name', 'unknown')}")
        print(f"     大类: {material.get('material_class_name', 'unknown')}")
        print(f"     上传时间: {material.get('upload_datetime', 'unknown')}")
        print(f"     本地路径: {local_path}")
        print()
    
    return get_user_confirmation(
        "上传素材到 Applovin",
        {"素材数量": len(materials)}
    )


def upload_to_applovin(
    materials: List[Tuple[Dict, str]],
    manager: ApplovinCampaignManager
) -> Dict:
    """
    步骤 5: 上传素材到 Applovin
    """
    print(f"\n{'='*60}")
    print("步骤 5: 上传素材到 Applovin")
    print(f"{'='*60}")
    
    file_paths = [local_path for _, local_path in materials]
    
    if not file_paths:
        return {"status": "error", "message": "没有可上传的文件"}
    
    print(f"  准备上传 {len(file_paths)} 个文件...")
    
    # 分批上传（每批最多 40 个）
    batch_size = 40
    all_results = []
    
    for i in range(0, len(file_paths), batch_size):
        batch = file_paths[i:i+batch_size]
        print(f"\n  上传批次 {i//batch_size + 1}/{(len(file_paths)-1)//batch_size + 1} ({len(batch)} 个文件)...")
        
        try:
            result = manager.upload_assets(batch)
            upload_id = result.get("upload_id")
            print(f"    上传任务 ID: {upload_id}")
            
            # 等待上传完成
            print(f"    等待上传完成...")
            max_wait = 300
            waited = 0
            
            while waited < max_wait:
                time.sleep(5)
                waited += 5
                
                status = manager.get_upload_result(upload_id)
                state = status.get("state", "PENDING")
                
                if state == "COMPLETED":
                    print(f"    ✅ 上传完成")
                    all_results.append(status)
                    break
                elif state == "FAILED":
                    print(f"    ❌ 上传失败: {status.get('message', 'unknown')}")
                    all_results.append(status)
                    break
                elif waited % 30 == 0:
                    print(f"    ⏳ 上传中... ({waited}s)")
            else:
                print(f"    ⚠️ 上传超时")
                all_results.append({"status": "timeout", "upload_id": upload_id})
                
        except Exception as e:
            print(f"    ❌ 上传异常: {e}")
            all_results.append({"status": "error", "message": str(e)})
    
    print(f"\n  上传批次完成: {len(all_results)}")
    
    return {
        "status": "completed",
        "batches": len(all_results),
        "results": all_results
    }


def sync_review_status(
    upload_results: Dict,
    manager: ApplovinCampaignManager
) -> List[Dict]:
    """
    步骤 6: 同步过审状态
    """
    print(f"\n{'='*60}")
    print("步骤 6: 同步素材过审状态")
    print(f"{'='*60}")
    
    # 获取所有上传的素材 ID
    all_assets = []
    for result in upload_results.get("results", []):
        if result.get("state") == "COMPLETED":
            all_assets.extend(result.get("assets", []))
    
    if not all_assets:
        print("  没有可同步的素材")
        return []
    
    print(f"  需要同步 {len(all_assets)} 个素材的状态")
    print(f"  查询 Applovin 素材库...")
    
    # 查询所有素材
    apl_assets = []
    page = 1
    while True:
        result = manager.list_assets(page=page, size=100)
        if not result:
            break
        apl_assets.extend(result)
        if len(result) < 100:
            break
        page += 1
        if page > 100:
            break
    
    print(f"  从 Applovin 获取到 {len(apl_assets)} 个素材")
    
    # 匹配上传的素材
    uploaded_ids = {a.get("id") for a in all_assets}
    matched = [a for a in apl_assets if a.get("id") in uploaded_ids]
    
    print(f"  匹配到 {len(matched)} 个素材")
    
    # 按状态分组
    status_groups = {}
    for asset in matched:
        status = asset.get("status", "UNKNOWN")
        status_groups.setdefault(status, []).append(asset)
    
    # 显示状态摘要
    print(f"\n  过审状态摘要:")
    for status, items in sorted(status_groups.items()):
        print(f"    {status}: {len(items)} 个")
        for item in items[:5]:  # 只显示前5个
            print(f"      - {item.get('name', 'unknown')}")
        if len(items) > 5:
            print(f"      ... 还有 {len(items) - 5} 个")
    
    return matched


def main():
    parser = argparse.ArgumentParser(
        description="APL 素材上传 - 从 DAP 同步素材到 Applovin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 上传上周 Wgame 的英文 AI 视频素材（9:16）
  python upload_from_dap.py \\
    --game-id 10048 \\
    --type video \\
    --language en \\
    --ratio "1080*1920" \\
    --material-class AI \\
    --start-date 2026-05-11 \\
    --end-date 2026-05-17

  # 上传所有上周的素材
  python upload_from_dap.py \\
    --game-id 10048 \\
    --start-date 2026-05-11 \\
    --end-date 2026-05-17
"""
    )
    
    # 必需参数
    parser.add_argument("--game-id", type=int, required=True,
                       help="项目 ID (Wgame=10048)")
    
    # 可选筛选参数
    parser.add_argument("--type", default="video",
                       choices=["video", "image", "image_set", "trial_play"],
                       help="素材类型 (默认: video)")
    parser.add_argument("--language", 
                       help="语系 (en/cn/ja/ko/ru 等)")
    parser.add_argument("--ratio",
                       help="尺寸比例 (如 1080*1920)")
    parser.add_argument("--material-class",
                       help="素材大类 (AI/3D/剪辑/KOL/本地化)")
    parser.add_argument("--start-date", required=True,
                       help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True,
                       help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--page-size", type=int, default=1000,
                       help="每页查询数量 (默认: 1000)")
    
    # 本地目录
    parser.add_argument("--local-dir", default="/tmp/apl_upload",
                       help="本地临时目录 (默认: /tmp/apl_upload)")
    
    # 跳过步骤
    parser.add_argument("--skip-confirm", action="store_true",
                       help="跳过用户确认")
    
    args = parser.parse_args()
    
    # 检查环境变量
    api_key = os.environ.get("APPLOVIN_API_KEY")
    account_id = os.environ.get("APPLOVIN_ACCOUNT_ID")
    
    if not api_key or not account_id:
        print("❌ 错误: 未设置 APPLOVIN_API_KEY 或 APPLOVIN_ACCOUNT_ID")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print("APL 素材上传 - 从 DAP 同步到 Applovin")
    print(f"{'='*60}")
    
    # 步骤 1: 查询 DAP（优先使用 data skill）
    materials = query_dap_materials_via_cli(
        game_id=args.game_id,
        material_type=args.type,
        language=args.language,
        ratio=args.ratio,
        material_class=args.material_class,
        start_date=args.start_date,
        end_date=args.end_date,
        page_size=args.page_size
    )
    
    # 如果 data skill 返回空，尝试备选方案
    if not materials:
        print("\n  ⚠️ data skill 未返回素材列表，尝试备选方案...")
        materials = query_dap_materials_direct(
            game_id=args.game_id,
            material_type=args.type,
            language=args.language,
            ratio=args.ratio,
            material_class=args.material_class,
            start_date=args.start_date,
            end_date=args.end_date,
            page_size=args.page_size
        )
    
    if not materials:
        print("\n❌ 未找到符合条件的素材")
        sys.exit(0)
    
    # 步骤 2 & 3: 复制素材到本地
    copied_materials = copy_materials_from_sync_folder(
        materials,
        local_dest_dir=args.local_dir
    )
    
    if not copied_materials:
        print("\n❌ 没有成功复制的素材")
        sys.exit(0)
    
    # 步骤 4: 用户确认
    if not args.skip_confirm:
        if not confirm_materials(copied_materials):
            print("\n❌ 用户取消上传")
            sys.exit(0)
    
    # 步骤 5: 上传到 Applovin
    manager = ApplovinCampaignManager(api_key, account_id)
    upload_results = upload_to_applovin(copied_materials, manager)
    
    # 步骤 6: 同步过审状态
    sync_review_status(upload_results, manager)
    
    print(f"\n{'='*60}")
    print("✅ 素材上传流程完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()