"""campaign-builder CLI 入口。

用法（从项目根目录）:
    python workspace/skills/campaign-builder/scripts/cli.py <command> [options]

子命令:
    naming       素材命名规则（生成 / 校验 / 解析）
    sop          SOP 清单校验
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_WORKSPACE = _SCRIPTS.parents[2]


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


_naming_mod = _load("naming_generator")
_sop_mod = _load("sop_checker")

_CONFIG_DIR = _WORKSPACE / "config"


def _load_config() -> dict:
    naming_rules = json.loads(
        (_CONFIG_DIR / "naming-rules.json").read_text(encoding="utf-8")
    )
    sop_path = _CONFIG_DIR / "sop-templates" / "default.json"
    sop_template = (
        json.loads(sop_path.read_text(encoding="utf-8"))
        if sop_path.exists()
        else {"checklist": []}
    )
    return {"naming_rules": naming_rules, "sop_template": sop_template}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="campaign-builder CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # naming 子命令
    p = sub.add_parser("naming", help="素材命名规则")
    p.add_argument("action", choices=["generate", "validate", "parse"])
    p.add_argument("--name", help="待校验/解析的名称")
    p.add_argument("--fields", help="生成用字段 JSON（如 '{\"project\":\"ROK\"}'）")

    # sop 子命令
    p = sub.add_parser("sop", help="SOP 清单校验")
    p.add_argument("--check-results", required=True, help="自动检查结果 JSON")

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_naming(args: argparse.Namespace, config: dict) -> dict:
    """素材命名规则操作."""
    rules = config["naming_rules"]

    if args.action == "generate":
        fields = json.loads(args.fields) if args.fields else {}
        name = _naming_mod.generate_name(rules, **fields)
        return {"action": "generate", "name": name}

    if args.action == "validate":
        result = _naming_mod.validate_name(rules, args.name or "")
        return {"action": "validate", **result}

    if args.action == "parse":
        result = _naming_mod.parse_name(rules, args.name or "")
        return {"action": "parse", "fields": result}

    return {"error": f"unknown action: {args.action}"}


def _cmd_sop(args: argparse.Namespace, config: dict) -> dict:
    """SOP 清单校验."""
    template = config["sop_template"]
    check_results = json.loads(args.check_results)
    return _sop_mod.check_sop(template, check_results)


_CMD_MAP = {
    "naming": _cmd_naming,
    "sop": _cmd_sop,
}


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        config = _load_config()
        result = _CMD_MAP[args.command](args, config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
