"""naming_generator — 素材命名规则生成与校验.

委托 lib/naming.py 统一实现，保持 campaign-builder CLI 的接口兼容。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)

from lib.naming import (
    generate_material_name,
    parse_material_name,
    validate_material_name,
)


def generate_name(rules: dict[str, Any], **fields: str) -> str:
    """根据命名规则和字段值生成标准名称."""
    return generate_material_name(rules, **fields)


def validate_name(rules: dict[str, Any], name: str) -> dict[str, Any]:
    """校验名称是否符合命名规则. Returns {"valid": bool, "errors": list[str]}."""
    result = validate_material_name(name, rules)
    if result["is_valid"]:
        return {"valid": True, "errors": []}
    return {"valid": False, "errors": [result["error"]]}


def parse_name(rules: dict[str, Any], name: str) -> dict[str, str] | None:
    """解析名称为字段字典，格式不合法返回 None."""
    parsed = parse_material_name(name, rules)
    return parsed if parsed else None
