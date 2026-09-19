#!/usr/bin/env python3
"""
Handoff Schema 自检（S4-1）

校验 Orchestrator build_handoff.py 生成的 handoff JSON 是否符合 schemas/handoff.schema.json。
若 jsonschema 库不可用，会回退到「关键字段存在性」最小检查。

调用：
    python scripts/validate_handoff_schema.py --handoff <path> [--schema <path>]

退出码：
    0  通过
    1  schema 校验失败
    2  使用错误
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_TOP_FIELDS = [
    "roleId",
    "deliveryId",
    "workflowDomain",
    "taskSummary",
    "outputs",
]


def minimal_check(handoff: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for field in REQUIRED_TOP_FIELDS:
        if field not in handoff:
            errors.append(f"missing required field: {field}")
    if "outputs" in handoff and not isinstance(handoff["outputs"], list):
        errors.append("outputs must be array")
    if "taskSummary" in handoff and not isinstance(handoff["taskSummary"], str):
        errors.append("taskSummary must be string")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Handoff schema validator (S4-1)")
    parser.add_argument("--handoff", required=True, help="handoff JSON 文件")
    parser.add_argument("--schema", help="schema 文件路径（可选，默认 schemas/handoff.schema.json）")
    args = parser.parse_args()

    handoff_path = Path(args.handoff).resolve()
    if not handoff_path.exists():
        print(f"[validate_handoff_schema] not found: {handoff_path}", file=sys.stderr)
        return 2

    try:
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "status": "fail",
            "errors": [f"invalid JSON: {exc}"],
        }, ensure_ascii=False, indent=2))
        return 1

    schema_path: Path
    if args.schema:
        schema_path = Path(args.schema).resolve()
    else:
        skill_root = Path(__file__).resolve().parent.parent
        schema_path = skill_root / "schemas" / "handoff.schema.json"

    errors: List[str] = []
    used_full_schema = False
    if schema_path.exists():
        try:
            import jsonschema  # type: ignore
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = jsonschema.Draft7Validator(schema)
            for err in validator.iter_errors(handoff):
                errors.append(f"{list(err.absolute_path)}: {err.message}")
            used_full_schema = True
        except ImportError:
            errors.extend(minimal_check(handoff))
    else:
        errors.extend(minimal_check(handoff))

    summary = {
        "status": "pass" if not errors else "fail",
        "handoff": str(handoff_path),
        "schema": str(schema_path) if schema_path.exists() else None,
        "schemaCheckMode": "full" if used_full_schema else "minimal",
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
