#!/usr/bin/env python3
"""Upstream-input consumer audit for software-development-team.

Detects the "input wired halfway then broken" failure mode: an upstream input
artifact (docs/input/0X or docs/input/models/*) that the contracts promise roles
will consume, but NO role prompt actually references. Contracts are prose; a role
session only loads its own prompt -- so an input mentioned only in a contract is
a soft constraint that silently never reaches any role.

This audit builds the input -> consumer-role matrix mechanically and flags any
tracked input with ZERO role consumers, unless it is on the SCRIPT_CONSUMED
whitelist (artifacts consumed by a gate script, not by a role -- e.g. the
baseline manifest is hashed by validate_input_contract.py C-INPUT-01).

A new input type with no consumer must be EITHER wired into a role prompt OR
explicitly whitelisted with a reason -- the whitelist forces that decision to be
conscious instead of accidental.

Zero third-party dependencies (stdlib only), consistent with the skill.

Usage:
    python scripts/check_input_consumers.py --skill-root .
    python scripts/check_input_consumers.py --skill-root . --json

Exit codes: 0 = no broken chains, 1 = at least one input has no consumer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Tracked upstream inputs -> markers that identify a role prompt consuming them.
# Markers are file-path-based where possible to avoid matching prose mentions.
TRACKED_INPUTS: dict[str, list[str]] = {
    # docs/input/0X (business requirement entry, prd-input-contract.md)
    "00-项目概述": ["00-项目概述", "input/00"],
    "01-能力目录": ["01-能力目录", "input/01"],
    "02-领域模型": ["02-领域模型", "input/02"],
    "03-状态机": ["03-状态机", "input/03"],
    "04-业务规则": ["04-业务规则", "input/04"],
    "05-流程模型": ["05-流程模型", "input/05"],
    "06-调研台账": ["06-调研台账", "input/06", "调研台账"],
    "07-待确认问题": ["07-待确认", "input/07"],
    # docs/input/models/* (development baseline package, LAW-9/LAW-10)
    "model-spec.json": ["model-spec"],
    "baseline-manifest.json": ["baseline-manifest"],
    "BPMN (*.bpmn)": [".bpmn", "bpmn/", "BPMN"],
    "OWL (*.owl)": [".owl", "ontology/", "OWL"],
    "requirements-graph.ttl": ["requirements-graph", ".ttl", "统一需求图"],
    "sparql-results.json": ["sparql"],
    "reasoning-report.json": ["reasoning-report", "推理报告"],
    "SHACL 校验报告": ["graph-validation", "SHACL"],
}

# Inputs consumed by a GATE SCRIPT rather than a role. Each needs a reason so the
# exemption is a conscious decision, not an accidental omission.
SCRIPT_CONSUMED: dict[str, str] = {
    "baseline-manifest.json": "validate_input_contract.py C-INPUT-01（sha256 哈希校验）",
    "model-spec.json": "validate_input_contract.py C-INPUT-04（规范源一致性校验）",
}


def _load_role_prompts(skill_root: Path) -> dict[str, str]:
    """Map role stem -> prompt text. Non-recursive: skips _common/ fragments."""
    prompts_dir = skill_root / "assets" / "prompts"
    texts: dict[str, str] = {}
    if not prompts_dir.is_dir():
        return texts
    for p in sorted(prompts_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            texts[p.stem] = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return texts


def audit(skill_root: Path) -> dict:
    """Build the consumption matrix and detect broken chains."""
    texts = _load_role_prompts(skill_root)

    matrix: dict[str, list[str]] = {}
    breaks: list[str] = []
    for artifact, markers in TRACKED_INPUTS.items():
        consumers = sorted(role for role, t in texts.items()
                           if any(m in t for m in markers))
        matrix[artifact] = consumers
        if not consumers and artifact not in SCRIPT_CONSUMED:
            breaks.append(
                f"input-consumer: 上游输入 '{artifact}' 无任何角色消费，且不在脚本消费"
                "白名单中（契约承诺但角色 prompt 未接，输入断链）。请接入相应角色 prompt，"
                "或确认它由门禁脚本消费后加入 SCRIPT_CONSUMED 白名单。"
            )

    return {
        "tool": "check_input_consumers",
        "rolePromptCount": len(texts),
        "trackedInputs": len(TRACKED_INPUTS),
        "status": "pass" if not breaks else "fail",
        "matrix": matrix,
        "scriptConsumed": SCRIPT_CONSUMED,
        "breaks": breaks,
    }


def _print_human(report: dict) -> None:
    print(f"Input consumer audit: {report['status'].upper()} "
          f"({report['rolePromptCount']} role prompts, "
          f"{report['trackedInputs']} tracked inputs)")
    for artifact, consumers in report["matrix"].items():
        if consumers:
            print(f"  - {artifact:<24} <- {', '.join(consumers)}")
        elif artifact in report["scriptConsumed"]:
            print(f"  - {artifact:<24} <- [script] "
                  f"{report['scriptConsumed'][artifact]}")
        else:
            print(f"  - {artifact:<24} <- !!! NO CONSUMER (断链)")
    for b in report["breaks"]:
        print(f"  [ERROR] {b}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit that every upstream input has a role consumer.")
    parser.add_argument("--skill-root", default=".", help="Skill root directory")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    if not skill_root.is_dir():
        print(f"error: skill root not found: {skill_root}", file=sys.stderr)
        return 3

    report = audit(skill_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
