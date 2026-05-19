"""Plan DSL JSON 校验与自动修复。

用法:
    # 从 stdin 读取
    echo '{"dsl_version":1,...}' | python validate_dsl.py

    # 从文件读取
    python validate_dsl.py --file /path/to/dsl.json

    # 只修复 JSON 格式，不做 DSL 语义校验
    python validate_dsl.py --fix-only

输出 JSON:
    {
      "valid": true/false,
      "repaired": true/false,
      "errors": ["..."],
      "warnings": ["..."],
      "dsl": { ... }          // 修复后的 DSL（仅当解析成功时）
    }
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

# ── Action Registry 白名单 ──────────────────────────────────────────

QUERY_ACTIONS = {
    "query_creative_performance", "query_attribution", "query_installs",
    "query_revenue", "query_ltv", "query_retention", "query_account_balance",
    "query_spend_progress", "query_creative_assets", "query_creative_inventory",
    "query_creative_fatigue", "query_shortname_summary", "query_postback_status",
    "query_compliance_result", "query_ai_tags", "query_cpe_achievement",
    "query_roi_progress", "query_material_report", "get_custom_report",
}

WRITE_ACTIONS = {
    "update_entity_status", "update_budget",
    "create_campaign", "create_adset", "create_ad",
    "write_lifecycle_action", "submit_compliance_check", "submit_ai_tagging",
}

ENGINE_ACTIONS = {
    "tag_entity", "notify", "audit_log", "fail_plan", "complete_plan",
    "compose_report_data", "render_report",
    "compute_test_structure", "compute_account_pool",
    "compute_attribution", "compute_anomaly_attribution",
    "compute_growth_attribution", "compute_a_b_factors",
    "compute_period_diff", "compute_winner_pattern",
    "compute_region_preference", "compute_metric_baseline",
    "compute_billing_diff", "check_budget_feasibility",
    "run_sop_checklist", "run_link_test",
    "aggregate_metrics", "compute_group_by_field",
    "compute_install_gap", "render_settlement", "parse_creative_naming",
}

ALL_ACTIONS = QUERY_ACTIONS | WRITE_ACTIONS | ENGINE_ACTIONS

VALID_PLAN_TYPES = {
    "alert", "creative_decay", "campaign_decay", "creative_scale",
    "creative_inventory", "campaign_launch", "sop_check", "link_test",
    "optimization", "report", "reconciliation", "analysis",
    "creative_ab_test", "dco_pipeline", "custom",
}

VALID_NODE_TYPES = {
    "action", "condition", "yield", "foreach", "parallel", "agent", "sub_plan",
}

VALID_AGENT_TASKS = {
    "trend_attribution", "report_narrative", "creative_brief",
    "strategy_advice", "anomaly_diagnosis", "material_insight",
}

VALID_YIELD_TYPES = {"approval", "timer", "signal"}

VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}

BUILTIN_FUNCTIONS = {
    "consecutive_below", "consecutive_above", "consecutive_decline",
    "trend_decline", "trend_increase", "rolling_avg",
    "percentile", "avg", "sum", "min", "max", "count", "stddev",
    "today", "now", "days_since", "date_offset", "days_between",
    "extract_field", "concat", "coalesce", "contains", "len", "abs",
}


# ── JSON 修复 ────────────────────────────────────────────────────────

def repair_json(raw: str) -> tuple[str, list[str]]:
    """尝试修复常见 JSON 格式错误，返回 (修复后字符串, 修复动作列表)。"""
    fixes: list[str] = []
    text = raw.strip()

    # 0. 提取 markdown 代码块中的 JSON
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
        fixes.append("从 markdown 代码块中提取 JSON")

    # 1. 去除尾部逗号: ,} 或 ,]
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r",\s*([}\]])", r"\1", text)
    if prev != raw.strip() and "尾部逗号" not in " ".join(fixes):
        fixes.append("移除尾部多余逗号")

    # 2. 单引号 → 双引号（仅限 key 位置，简单启发式）
    if "'" in text and '"' not in text[:20]:
        text = text.replace("'", '"')
        fixes.append("单引号替换为双引号")

    # 3. 补全缺失的闭合括号
    opens = 0
    open_sq = 0
    for ch in text:
        if ch == "{":
            opens += 1
        elif ch == "}":
            opens -= 1
        elif ch == "[":
            open_sq += 1
        elif ch == "]":
            open_sq -= 1

    if opens > 0:
        text += "}" * opens
        fixes.append(f"补全 {opens} 个缺失的 '}}'")
    elif opens < 0:
        # 多余的 }，从末尾移除
        for _ in range(-opens):
            idx = text.rfind("}")
            if idx >= 0:
                text = text[:idx] + text[idx + 1:]
        fixes.append(f"移除 {-opens} 个多余的 '}}'")

    if open_sq > 0:
        text += "]" * open_sq
        fixes.append(f"补全 {open_sq} 个缺失的 ']'")
    elif open_sq < 0:
        for _ in range(-open_sq):
            idx = text.rfind("]")
            if idx >= 0:
                text = text[:idx] + text[idx + 1:]
        fixes.append(f"移除 {-open_sq} 个多余的 ']'")

    # 4. 修复缺少逗号的相邻键值对: }"key" 或 ]"key"
    text = re.sub(r'([}\"])\s*\n\s*"', r'\1,\n"', text)

    # 5. 注释移除（JSON 不允许注释）
    if "//" in text or "/*" in text:
        text = re.sub(r"//[^\n]*", "", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        fixes.append("移除 JSON 中的注释")

    return text, fixes


# ── DSL 语义校验 ──────────────────────────────────────────────────────

def validate_dsl(dsl: dict[str, Any]) -> tuple[list[str], list[str]]:
    """校验 DSL 结构，返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []

    # dsl_version
    if dsl.get("dsl_version") != 1:
        errors.append(f"dsl_version 应为 1，实际为 {dsl.get('dsl_version')}")

    plan = dsl.get("plan", {})
    if not plan:
        errors.append("缺少 plan 字段")
        return errors, warnings

    # plan.type
    plan_type = plan.get("type")
    if plan_type not in VALID_PLAN_TYPES:
        errors.append(f"plan.type '{plan_type}' 不在合法枚举中，合法值：{sorted(VALID_PLAN_TYPES)}")

    # risk_level
    risk = plan.get("risk_level")
    if risk and risk not in VALID_RISK_LEVELS:
        errors.append(f"risk_level '{risk}' 不合法，合法值：{sorted(VALID_RISK_LEVELS)}")

    # trigger
    trigger = plan.get("trigger", {})
    kind = trigger.get("kind")
    if kind and kind not in ("schedule", "api", "sub_plan"):
        errors.append(f"trigger.kind '{kind}' 不合法，合法值：schedule / api / sub_plan")

    # nodes
    nodes = plan.get("nodes", [])
    if not nodes:
        warnings.append("nodes 为空")
    else:
        _validate_nodes(nodes, errors, warnings, path="nodes")

    return errors, warnings


def _validate_nodes(nodes: list, errors: list, warnings: list, path: str) -> None:
    """递归校验节点列表。"""
    if not isinstance(nodes, list):
        errors.append(f"{path}: 应为数组，实际为 {type(nodes).__name__}")
        return

    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"{path}[{i}]: 节点应为对象，实际为 {type(node).__name__}")
            continue

        ntype = node.get("type")
        npath = f"{path}[{i}]({node.get('id', ntype)})"

        if ntype not in VALID_NODE_TYPES:
            errors.append(f"{npath}: 节点类型 '{ntype}' 不合法")
            continue

        if ntype == "action":
            action_name = node.get("action", "")
            if action_name not in ALL_ACTIONS:
                if node.get("_draft"):
                    warnings.append(f"{npath}: action '{action_name}' 标记为 draft（不在 Registry 中）")
                else:
                    errors.append(f"{npath}: action '{action_name}' 不在 Action Registry 中")

            if action_name in WRITE_ACTIONS and not node.get("idempotency_key"):
                if action_name in ("write_lifecycle_action", "submit_compliance_check", "submit_ai_tagging"):
                    pass  # 这些非幂等写操作不强制要求 idempotency_key
                else:
                    warnings.append(f"{npath}: 写操作 '{action_name}' 缺少 idempotency_key")

        elif ntype == "condition":
            if not node.get("if"):
                errors.append(f"{npath}: condition 缺少 if 表达式")
            _validate_expression(node.get("if", ""), npath, errors, warnings)
            if "then" in node:
                _validate_nodes(node["then"], errors, warnings, f"{npath}.then")
            for j, elif_branch in enumerate(node.get("else_if", [])):
                if "then" in elif_branch:
                    _validate_nodes(elif_branch["then"], errors, warnings, f"{npath}.else_if[{j}].then")
            if "else" in node and node["else"]:
                _validate_nodes(node["else"], errors, warnings, f"{npath}.else")

        elif ntype == "yield":
            yield_type = node.get("yield")
            if yield_type not in VALID_YIELD_TYPES:
                errors.append(f"{npath}: yield 类型 '{yield_type}' 不合法，合法值：{sorted(VALID_YIELD_TYPES)}")

        elif ntype == "foreach":
            if not node.get("items"):
                errors.append(f"{npath}: foreach 缺少 items 字段")
            do_nodes = node.get("do", [])
            _validate_nodes(do_nodes, errors, warnings, f"{npath}.do")

        elif ntype == "parallel":
            branches = node.get("branches", [])
            if not isinstance(branches, list):
                errors.append(f"{npath}: parallel.branches 应为数组")
            else:
                for j, branch in enumerate(branches):
                    if not isinstance(branch, list):
                        errors.append(f"{npath}.branches[{j}]: 每个分支必须是节点数组 [...]，实际为 {type(branch).__name__}")
                    else:
                        _validate_nodes(branch, errors, warnings, f"{npath}.branches[{j}]")

        elif ntype == "agent":
            task = node.get("task")
            if task not in VALID_AGENT_TASKS:
                errors.append(f"{npath}: agent task '{task}' 不在合法枚举中，合法值：{sorted(VALID_AGENT_TASKS)}")

        elif ntype == "sub_plan":
            if not node.get("template_id") and not node.get("inline"):
                errors.append(f"{npath}: sub_plan 需要 template_id 或 inline 之一")


def _validate_expression(expr: str, path: str, errors: list, warnings: list) -> None:
    """检查表达式中是否使用了不存在的函数。"""
    if not expr or not isinstance(expr, str):
        return
    # 提取所有函数调用: funcname(
    func_calls = re.findall(r"([a_zA-Z_][a-zA-Z0-9_]*)\s*\(", expr)
    for func in func_calls:
        if func not in BUILTIN_FUNCTIONS:
            warnings.append(f"{path}: 表达式使用了未注册函数 '{func}()'，请确认是否在 Section 5 内置函数列表中")


# ── 主入口 ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Plan DSL JSON 校验与自动修复")
    parser.add_argument("--file", "-f", help="从文件读取 DSL JSON（默认从 stdin）")
    parser.add_argument("--fix-only", action="store_true", help="只修复 JSON 格式，不做 DSL 语义校验")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            raw = fh.read()
    else:
        raw = sys.stdin.read()

    if not raw.strip():
        print(json.dumps({"valid": False, "repaired": False, "errors": ["输入为空"], "warnings": []}, ensure_ascii=False))
        sys.exit(1)

    result: dict[str, Any] = {"valid": False, "repaired": False, "errors": [], "warnings": []}

    # 1. 先尝试直接解析
    try:
        dsl = json.loads(raw)
        result["repaired"] = False
    except json.JSONDecodeError:
        # 2. 解析失败，尝试修复
        repaired_text, fixes = repair_json(raw)
        try:
            dsl = json.loads(repaired_text)
            result["repaired"] = True
            result["warnings"].extend([f"[自动修复] {f}" for f in fixes])
        except json.JSONDecodeError as e:
            result["errors"].append(f"JSON 解析失败且无法自动修复: {e}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)

    # 3. DSL 语义校验
    if not args.fix_only:
        sem_errors, sem_warnings = validate_dsl(dsl)
        result["errors"].extend(sem_errors)
        result["warnings"].extend(sem_warnings)

    result["valid"] = len(result["errors"]) == 0
    result["dsl"] = dsl

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
