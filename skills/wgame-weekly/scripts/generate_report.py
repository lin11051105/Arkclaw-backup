#!/usr/bin/env python3
"""Wgame 周报生成脚本 - 简化版"""
import json
import subprocess
import sys
from datetime import datetime, timedelta

KPI = {"overall_roi_7": 6.8, "overall_actual_roi": 4.1, "android_actual_roi": 5.4, "ios_actual_roi": 3.6}

def query_dap(rid, sd, ed, table, platform=None):
    params = [f"report_id={rid}", f"start_date={sd}", f"end_date={ed}", "tz=0", f"table={table}"]
    if platform: params.append(f"filter_platform={platform}")
    cmd = ["atlas-skillhub", "gateway", "call-tool", "--service", "dap", "--tool", "get_custom_report"] + params
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0:
        r = json.loads(result.stdout)
        if "content" in r and r["content"]:
            t = r["content"][0].get("text", "")
            if t: return json.loads(t)
    return None

def parse(data):
    if not data or 'tables' not in data: return [], []
    t = data['tables'][0]
    return [c['name'] for c in t.get('columns', [])], t.get('data', [])

def getv(row, cols, name, d=0):
    try: 
        i = cols.index(name)
        return row[i] if i < len(row) and row[i] is not None else d
    except: return d

def agg(cols, rows):
    tc = ti = 0
    a = i = p = {'cost': 0, 'install': 0, 'actual_roi': 0, 'retention_1': 0}
    for r in rows:
        pl = getv(r, cols, '操作系统', '')
        c = getv(r, cols, '消耗数', 0)
        ins = getv(r, cols, '总新增账号数', 0)
        ar = getv(r, cols, 'Actual_ROI', 0)
        r1 = getv(r, cols, '账号次留率', 0)
        tc += c; ti += ins
        d = {'cost': c, 'install': ins, 'actual_roi': ar, 'retention_1': r1}
        if pl == 'Android': a = d
        elif pl == 'iOS': i = d
        elif pl == 'PC': p = d
    cpi = tc / ti if ti > 0 else 0
    wroi = (a['cost']*a['actual_roi'] + i['cost']*i['actual_roi'] + p['cost']*p['actual_roi']) / tc if tc > 0 else 0
    wret = (a['install']*a['retention_1'] + i['install']*i['retention_1'] + p['install']*p['retention_1']) / ti if ti > 0 else 0
    return {'cost': tc, 'install': ti, 'cpi': cpi, 'actual_roi': wroi, 'retention_1': wret, 'android': a, 'ios': i, 'pc': p}

def proc_country(cols, rows):
    r = []
    for row in rows:
        r.append({'country': getv(row, cols, '国家', ''), 'cost': getv(row, cols, '消耗数', 0), 'install': getv(row, cols, '总新增账号数', 0), 'cpi': getv(row, cols, '总新增成本', 0), 'actual_roi': getv(row, cols, 'Actual_ROI', 0)})
    return sorted(r, key=lambda x: x['cost'], reverse=True)

def proc_channel(cols, rows):
    r = []
    for row in rows:
        r.append({'channel': getv(row, cols, '渠道', ''), 'cost': getv(row, cols, '消耗数', 0), 'install': getv(row, cols, '总新增账号数', 0), 'cpi': getv(row, cols, '总新增成本', 0), 'actual_roi': getv(row, cols, 'Actual_ROI', 0), 'retention_1': getv(row, cols, '账号次留率', 0)})
    return sorted(r, key=lambda x: x['cost'], reverse=True)

def fc(v): return "$0" if v is None or v == 0 else f"${float(v):,.0f}"
def fn(v): return "0" if v is None else f"{int(float(v)):,}"
def fp(v): return "0.00%" if v is None else f"{float(v):.2f}%"

def main():
    today = datetime.utcnow()
    this_m = today - timedelta(days=today.weekday())
    last_m = this_m - timedelta(days=7)
    last_s = last_m + timedelta(days=6)
    wb_m = last_m - timedelta(days=7)
    wb_s = wb_m + timedelta(days=6)
    
    ls, le = last_m.strftime("%Y-%m-%d"), last_s.strftime("%Y-%m-%d")
    ws, we = wb_m.strftime("%Y-%m-%d"), wb_s.strftime("%Y-%m-%d")
    
    print(f"查询: {ls}~{le}", file=sys.stderr)
    
    lw = agg(*parse(query_dap(16621, ls, le, "store")))
    ac = proc_country(*parse(query_dap(16621, ls, le, "country", "android")))
    ic = proc_country(*parse(query_dap(16621, ls, le, "country", "ios")))
    ch = proc_channel(*parse(query_dap(16621, ls, le, "media_src", "android")))
    
    print(f"消耗: {fc(lw['cost'])}, 新增: {fn(lw['install'])}, ROI: {fp(lw['actual_roi'])}", file=sys.stderr)
    
    # 生成报告
    r = f"""# Wgame（战火勋章）周会数据报告

**报告周期**：{ls} ~ {le}  
**生成时间**：{datetime.now().strftime("%Y-%m-%d %H:%M")}

---

## 1. 上周汇总数据

| 指标 | 数值 |
|------|------|
| 总消耗 | {fc(lw['cost'])} |
| 总新增 | {fn(lw['install'])} |
| 新增成本 | {fc(lw['cpi'])} |
| Actual_ROI | {fp(lw['actual_roi'])} |
| 次留率 | {fp(lw['retention_1'])} |

### 分平台数据

| 平台 | 消耗 | 新增 | 新增成本 | Actual_ROI | KPI | 达标 |
|------|------|------|---------|-----------|-----|------|
| Android | {fc(lw['android']['cost'])} | {fn(lw['android']['install'])} | {fc(lw['android']['cost']/lw['android']['install'] if lw['android']['install'] else 0)} | **{fp(lw['android']['actual_roi'])}** | 5.4% | {'✓' if lw['android']['actual_roi'] >= 5.4 else '✗'} |
| iOS | {fc(lw['ios']['cost'])} | {fn(lw['ios']['install'])} | {fc(lw['ios']['cost']/lw['ios']['install'] if lw['ios']['install'] else 0)} | **{fp(lw['ios']['actual_roi'])}** | 3.6% | {'✓' if lw['ios']['actual_roi'] >= 3.6 else '✗'} |
| PC | {fc(lw['pc']['cost'])} | {fn(lw['pc']['install'])} | {fc(lw['pc']['cost']/lw['pc']['install'] if lw['pc']['install'] else 0)} | {fp(lw['pc']['actual_roi'])} | - | - |

---

## 2. 安卓分国家数据（消耗Top10）

| 排名 | 国家 | 消耗 | 新增 | 新增成本 | Actual_ROI |
|------|------|------|------|---------|-----------|
"""
    for i, c in enumerate(ac[:10], 1):
        r += f"| {i} | {c['country']} | {fc(c['cost'])} | {fn(c['install'])} | {fc(c['cpi'])} | {fp(c['actual_roi'])} |\n"
    
    r += """
---

## 3. iOS分国家数据（消耗Top10）

| 排名 | 国家 | 消耗 | 新增 | 新增成本 | Actual_ROI |
|------|------|------|------|---------|-----------|
"""
    for i, c in enumerate(ic[:10], 1):
        r += f"| {i} | {c['country']} | {fc(c['cost'])} | {fn(c['install'])} | {fc(c['cpi'])} | {fp(c['actual_roi'])} |\n"
    
    r += """
---

## 4. 安卓分渠道数据

| 渠道 | 消耗 | 新增 | 新增成本 | Actual_ROI |
|------|------|------|---------|-----------|
"""
    for c in ch:
        r += f"| {c['channel']} | {fc(c['cost'])} | {fn(c['install'])} | {fc(c['cpi'])} | {fp(c['actual_roi'])} |\n"
    
    r += "\n---\n\n*数据来源：DAP #16621*\n"
    
    print(r)

if __name__ == "__main__":
    main()
