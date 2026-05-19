"""素材命名解析工具 — 基于 config/naming-rules.json。

所有需要从素材名中提取字段（地区、语言、类型、版本等）的逻辑共用此模块，
避免各脚本各自内联解析 naming-rules.json。

Usage:
    from lib.naming import parse_material_name, validate_material_name, parse_short_name
"""
from __future__ import annotations

import re


def parse_material_name(name: str, naming_rules: dict) -> dict[str, str]:
    """从素材名中按 naming-rules 提取各字段。

    Returns:
        {"project": "ROK", "region": "JP", "language": "ja", "type": "video", "version": "v1"}
        解析失败时返回空 dict。
    """
    if not name:
        return {}
    sep = naming_rules.get("separator", "_")
    fields_def = naming_rules.get("fields", {})
    parts = name.split(sep)

    pos_to_field = {v["position"]: k for k, v in fields_def.items()}
    max_pos = max(pos_to_field.keys()) if pos_to_field else 0
    if len(parts) <= max_pos:
        return {}

    return {field: parts[pos] for pos, field in pos_to_field.items() if pos < len(parts)}


def validate_material_name(name: str, naming_rules: dict) -> dict:
    """校验素材名是否符合 naming-rules。

    Returns:
        {"is_valid": bool, "parsed": dict, "error": str}
    """
    if not name:
        return {"is_valid": False, "parsed": {}, "error": "empty name"}

    sep = naming_rules.get("separator", "_")
    fields_def = naming_rules.get("fields", {})
    parts = name.split(sep)
    expected_count = len(fields_def)

    if len(parts) != expected_count:
        return {
            "is_valid": False,
            "parsed": {},
            "error": f"field_count mismatch: expected {expected_count}, got {len(parts)}",
        }

    pos_to_field = {v["position"]: k for k, v in fields_def.items()}
    parsed: dict[str, str] = {}

    for pos, field_name in sorted(pos_to_field.items()):
        value = parts[pos]
        field_cfg = fields_def[field_name]
        parsed[field_name] = value

        allowed = field_cfg.get("allowed_values")
        if allowed is not None and value not in allowed:
            return {
                "is_valid": False,
                "parsed": parsed,
                "error": f"invalid value for field '{field_name}': '{value}' not in {allowed}",
            }

        pattern = field_cfg.get("pattern")
        if pattern is not None and not re.fullmatch(pattern, value):
            return {
                "is_valid": False,
                "parsed": parsed,
                "error": f"invalid value for field '{field_name}': '{value}' does not match '{pattern}'",
            }

    return {"is_valid": True, "parsed": parsed, "error": ""}


def generate_material_name(naming_rules: dict, **fields: str) -> str:
    """根据命名规则和字段值生成标准素材名称。

    Usage: generate_material_name(rules, project="ROK", region="JP", language="ja", type="video", version="v1")
    → "ROK_JP_ja_video_v1"
    """
    sep = naming_rules.get("separator", "_")
    fields_def = naming_rules.get("fields", {})
    ordered = sorted(fields_def.items(), key=lambda x: x[1].get("position", 0))
    return sep.join(fields.get(name, "") for name, _ in ordered)


def get_field(name: str, field_name: str, naming_rules: dict) -> str | None:
    """从素材名中提取指定字段值。解析失败返回 None。"""
    parsed = parse_material_name(name, naming_rules)
    return parsed.get(field_name)


def parse_short_name(name: str, naming_rules: dict) -> str:
    """从素材名解析短名（去掉 region 和 language），用于跨地区聚合。

    规则: {project}_{region}_{language}_{type}_{version} → {project}_{type}_{version}
    不符合标准命名时返回原全名。
    """
    if not name:
        return ""
    result = validate_material_name(name, naming_rules)
    if not result["is_valid"]:
        return name
    sep = naming_rules.get("separator", "_")
    parsed = result["parsed"]
    return sep.join([parsed.get("project", ""), parsed.get("type", ""), parsed.get("version", "")])
