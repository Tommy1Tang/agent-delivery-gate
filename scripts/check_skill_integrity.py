#!/usr/bin/env python3
"""Deep integrity checks for the software-development-team skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path


REQUIRED_PROMPT_MARKERS = {
    "handoff": ["Handoff", "handoff", "任务交接"],
    "governance": [
        "assets/constitution.md",
        "assets/tech.md",
        "references/local-governance.md",
        "team-overview.md",
        "全局治理文件",
    ],
    "output": ["输出契约", "输出责任", "负责输出"],
    "boundary": ["禁止越权", "你不要做", "禁止"],
    "validation": ["验证清单", "完成标准", "质量门禁", "安全门禁"],
    "return": ["回传 Orchestrator", "向 orchestrator 汇报", "最终汇总", "最终回复"],
}

BANNED_PROMPT_PATTERNS = [
    r"调度agent",
    r"需求agent",
    r"前端agent",
    r"后端agent",
    r"FULL_STACK",
]

EXPECTED_SCHEMAS = [
    "handoff.schema.json",
    "role-result.schema.json",
    "artifact-manifest.schema.json",
    "quality-gate.schema.json",
    "audit-record.schema.json",
    "evidence-ledger.schema.json",
    "metrics.schema.json",
    "migration-report.schema.json",
    "team-memory.schema.json",
    "failure-pattern.schema.json",
    "adr-record.schema.json",
]

EXPECTED_TEMPLATES = [
    "需求规格书.template.md",
    "开发计划.template.md",
    "任务清单.template.md",
    "详细设计说明书.template.md",
    "接口数据契约.template.md",
    "UI设计说明.template.md",
    "单元测试用例.template.md",
    "单元测试报告.template.md",
    "集成测试用例.template.md",
    "集成测试报告.template.md",
    "代码评审.template.md",
    "安全评审.template.md",
    "部署说明.template.md",
    "监督审计.template.md",
    "交付证据账本.template.md",
    "commit-message.template.md",
    "pr.template.md",
    "输入缺口清单.template.md",
]

EXPECTED_SCRIPTS = [
    "check_skill_integrity.py",
    "validate_delivery.py",
    "build_handoff.py",
    "orchestrate.py",
    "write_evidence_ledger.py",
    "run_golden_tests.py",
    "metrics_report.py",
    "compatibility_check.py",
    "detect_stack.py",
    "schema_migrator.py",
    "preflight_env_check.py",
    "contract_drift_check.py",
    "memory_store.py",
    "memory_integration.py",
    "delivery_checkpoint.py",
    "ledger_archiver.py",
    "design_system_loader.py",
    "validate_input_contract.py",
    "next_step.py",
    "build_baseline_slice.py",
    "check_input_consumers.py",
]

EXPECTED_ADAPTERS = [
    "references/adapters/python-fastapi-sqlite.md",
    "references/adapters/vue-element-plus.md",
    "references/adapters/java-spring-postgresql.md",
    "references/adapters/node-react.md",
]

EXPECTED_RUNTIME_ADAPTERS = [
    "references/runtime-adapters/qoder.md",
    "references/runtime-adapters/codex-subagents.md",
    "references/runtime-adapters/single-session-fallback.md",
]

EXPECTED_GOLDEN_CASES = [
    "tests/golden/forward-development.json",
    "tests/golden/ui-development.json",
    "tests/golden/security-change.json",
    "tests/golden/incident-fix.json",
    "tests/golden/e2e-mandatory-backend.json",
]

EXPECTED_REFERENCES = [
    "references/autonomous-update-policy.md",
    "references/prd-input-contract.md",
    "references/graph-engineering-laws.md",
    "references/development-baseline-contract.md",
]

# Process / ontology models for the skill's own delivery workflow.
# JSON is the machine truth source; YAML is the human-editable twin.
EXPECTED_PROCESS_MODELS = [
    "assets/config/skill-process.json",
    "assets/config/skill-process.yaml",
    "assets/config/skill-ontology.json",
    "assets/config/skill-ontology.yaml",
]

EXPECTED_COMMON_FRAGMENTS = [
    "assets/prompts/_common/role-contract.fragment.md",
]

EXPECTED_EXAMPLE_DIR = "assets/templates/examples"

UI_DESIGNER_REQUIRED_MARKERS = [
    "组件库架构",
    "响应式设计框架",
    "Design Token 系统",
    "Element Plus 映射",
    "designSystemBinding",
]

# Markers that must appear in write-code role prompts (frontend/backend/execution engineer)
WRITE_CODE_REQUIRED_MARKERS = [
    "先读后写",
    "list_dir",
    "read_file",
]

# Frontend Engineer specific markers
FRONTEND_REQUIRED_MARKERS = [
    "router",
    "src/api/",
    "src/types/",
]

# Backend Engineer specific markers
BACKEND_REQUIRED_MARKERS = [
    "Result<T>",
    "BusinessException",
    "数据库变更",
    "@Transactional",
]

# Supervisor Auditor specific markers
AUDIT_REQUIRED_MARKERS = [
    "deliveryGateEvidence",
    "reworkCount",
    "halted-",
    "逐字粘贴",
    "list_dir docs/",
    "双向对账",
    "可观测性报告",
    # S4-3 / S4-4 / S5-4
    "证据交叉验证",
    "返工根因聚类",
    "rootCauseClusters",
]

# Stability markers (S1-S5)
STABILITY_MARKERS = {
    "product-analyst.prompt.md": ["需求歧义自检", "Given-When-Then"],
    "architect.prompt.md": ["技术栈对账", "ADR 模板", "detect_stack"],
    "development-orchestrator.prompt.md": [
        "任务规模硬约束",
        "任务依赖循环检测",
        "Smoke Test 前置门禁",
        "Handoff Schema 自检",
        "多重崩溃自动决策",
    ],
    "backend-engineer.prompt.md": [
        "SQL 迁移破坏性自检",
        "依赖白名单",
        "跨文件一致性检查",
    ],
    "frontend-engineer.prompt.md": [
        "设计系统对齐自检",
        "依赖白名单",
        "跨文件一致性检查",
    ],
    "data-contract-designer.prompt.md": [
        "契约破坏性变更检测",
        "错误码冲突检测",
    ],
    "quality-gate-engineer.prompt.md": [
        "评审清单二阶验证",
        "覆盖率交叉验证",
        "异常路径覆盖验证",
    ],
    "devops-release-engineer.prompt.md": [
        "部署 Dry-Run",
        "环境差异检查",
    ],
    "execution-engineer.prompt.md": [
        "Fallback 模式补偿",
    ],
}

# role-contract.fragment.md must contain upstream readiness + validation scope
ROLE_CONTRACT_REQUIRED_MARKERS = [
    "上游已交付客观条件",
    "增量与全量验证策略",
    "upstreamReadiness",
]


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_skill_root(initial: Path) -> Path:
    """Walk upward looking for SKILL.md so the script works from any cwd."""
    candidate = initial.resolve()
    if (candidate / "SKILL.md").exists():
        return candidate
    for parent in [candidate, *candidate.parents]:
        if (parent / "SKILL.md").exists() and (parent / "assets" / "config").exists():
            return parent
    return candidate


def _load_module_constants(script_path: Path) -> dict:
    if not script_path.exists():
        return {}
    try:
        spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
        if spec is None or spec.loader is None:
            return {}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return {k: v for k, v in vars(module).items() if not k.startswith("_")}
    except Exception:
        return {}


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Cannot parse JSON {path}: {exc}")
        return {}


def extract_yaml_prompt_files(yaml_text: str) -> list[str]:
    return re.findall(r"promptFile:\s*([^\s]+)", yaml_text)


def marker_present(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


# P4-11: Template field names that validate_delivery.py should detect via regex.
# Maps template file -> field patterns that must exist in validate_delivery.py
TEMPLATE_VALIDATOR_ALIGNMENT = {
    "单元测试报告.template.md": [
        r"覆盖率",  # COVERAGE_PATTERN must detect this
        r"单元测试",
    ],
    "集成测试报告.template.md": [
        r"集成测试覆盖率",  # INTEGRATION_COVERAGE_PATTERN must detect this
    ],
    "代码评审.template.md": [
        r"verdict|裁决|结论",  # BLOCK_PATTERNS_VERDICT must detect these
    ],
    "安全评审.template.md": [
        r"verdict|裁决|结论",
    ],
}

# Critical regex patterns from validate_delivery.py that must be importable.
VALIDATOR_REQUIRED_PATTERNS = [
    "COVERAGE_PATTERN",
    "INTEGRATION_COVERAGE_PATTERN",
    "BLOCK_PATTERNS_VERDICT",
    "PLACEHOLDER_PATTERNS",
    "E2E_PASS_RATE_PATTERN",
    "E2E_TOTAL_PATTERN",
]


def _check_template_validator_alignment(root: Path, errors: list[str], warnings: list[str]) -> None:
    """P4-11: Cross-verify template field names align with validate_delivery.py regex patterns.

    Ensures that machine-readable fields in templates are actually parseable by the
    validator's regex patterns. Detects drift between template format and validator expectations.
    """
    validate_path = root / "scripts" / "validate_delivery.py"
    if not validate_path.exists():
        errors.append("P4-11: validate_delivery.py not found — cannot verify alignment")
        return

    validator_source = validate_path.read_text(encoding="utf-8")

    # Check that all required patterns are defined in validate_delivery.py
    for pattern_name in VALIDATOR_REQUIRED_PATTERNS:
        if pattern_name not in validator_source:
            errors.append(f"P4-11: validate_delivery.py missing required pattern: {pattern_name}")

    # Cross-check templates against validator regexes
    template_dir = root / "assets" / "templates"
    for template_name, required_fields in TEMPLATE_VALIDATOR_ALIGNMENT.items():
        template_path = template_dir / template_name
        if not template_path.exists():
            continue  # Missing template is caught by other checks

        template_text = template_path.read_text(encoding="utf-8")
        for field_pattern in required_fields:
            # Verify the field exists in the template
            if not re.search(field_pattern, template_text):
                warnings.append(
                    f"P4-11: template '{template_name}' does not contain expected field pattern '{field_pattern}' "
                    f"— validate_delivery.py may fail to parse this template's output"
                )
            # Verify the validator source references this field concept
            # (at least one of the pattern's alternatives should appear in validator source)
            field_alts = field_pattern.split("|")
            if not any(alt in validator_source for alt in field_alts):
                errors.append(
                    f"P4-11: validate_delivery.py does not reference any of [{field_pattern}] "
                    f"from template '{template_name}' — validator cannot parse this template's output"
                )

    # Verify that END-OF-DOC completeness check covers the right documents
    if "END-OF-DOC" in validator_source:
        completeness_docs = re.findall(r'"docs/([^"]+\.md)"', validator_source)
        template_based_docs = [
            t.replace(".template.md", ".md")
            for t in EXPECTED_TEMPLATES
            if (template_dir / t).exists()
        ]
        # Key docs that should be covered by completeness check
        key_docs = ["01-需求规格书.md", "04-详细设计说明书.md", "07-接口数据契约.md", "14-代码评审.md", "19-监督审计.md"]
        for doc in key_docs:
            if doc not in " ".join(completeness_docs):
                warnings.append(
                    f"P4-11: validate_delivery.py END-OF-DOC check may not cover 'docs/{doc}'"
                )


def check_skill(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        errors.append("Missing SKILL.md")
    else:
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            errors.append("SKILL.md frontmatter is missing")
        if "name: software-development-team" not in text:
            errors.append("SKILL.md name is not software-development-team")
        if "description:" not in text:
            errors.append("SKILL.md description is missing")

    config_path = root / "assets" / "config" / "agent-team-config.json"
    yaml_path = root / "assets" / "config" / "agent-team-config.yaml"
    config = load_json(config_path, errors)

    roles = config.get("roles", [])
    role_ids = [role.get("id") for role in roles]
    if len(role_ids) != len(set(role_ids)):
        errors.append("Duplicate role ids found in JSON config")

    mode = config.get("mode", {}).get("unified-large-delivery", {})
    route = mode.get("route", [])
    if not route:
        errors.append("Unified large delivery route is missing")
    unknown_route_roles = sorted(set(route) - set(role_ids))
    if unknown_route_roles:
        errors.append(f"Route contains unknown roles: {unknown_route_roles}")
    missing_route_roles = sorted(set(role_ids) - set(route))
    if missing_route_roles:
        errors.append(f"Roles missing from route: {missing_route_roles}")

    prompt_files = []
    for role in roles:
        prompt_file = role.get("promptFile", "")
        prompt_files.append(prompt_file)
        prompt_path = root / prompt_file
        if not prompt_path.exists():
            errors.append(f"Prompt missing for {role.get('id')}: {prompt_file}")
            continue
        prompt_text = prompt_path.read_text(encoding="utf-8")
        for marker_name, markers in REQUIRED_PROMPT_MARKERS.items():
            if not marker_present(prompt_text, markers):
                errors.append(f"Prompt {prompt_file} missing marker group: {marker_name}")
        for pattern in BANNED_PROMPT_PATTERNS:
            if re.search(pattern, prompt_text):
                errors.append(f"Prompt {prompt_file} contains banned pattern: {pattern}")
        if role.get("id") == "ui-designer":
            for marker in UI_DESIGNER_REQUIRED_MARKERS:
                if marker not in prompt_text:
                    errors.append(f"UI Designer prompt missing design consistency marker: {marker}")
        # Check write-code role markers (C1-C5)
        write_code_roles = {"execution-engineer", "frontend-engineer", "backend-engineer"}
        role_id = role.get("id", "")
        if role_id in write_code_roles:
            for marker in WRITE_CODE_REQUIRED_MARKERS:
                if marker not in prompt_text:
                    errors.append(f"{role_id} prompt missing write-code marker: {marker}")
        if role_id == "frontend-engineer":
            for marker in FRONTEND_REQUIRED_MARKERS:
                if marker not in prompt_text:
                    errors.append(f"Frontend Engineer prompt missing marker: {marker}")
        if role_id == "backend-engineer":
            for marker in BACKEND_REQUIRED_MARKERS:
                if marker not in prompt_text:
                    errors.append(f"Backend Engineer prompt missing marker: {marker}")
        if role_id == "supervisor-auditor":
            for marker in AUDIT_REQUIRED_MARKERS:
                if marker not in prompt_text:
                    errors.append(f"Supervisor Auditor prompt missing marker: {marker}")
        # Stability markers (S1-S5) per role prompt
        prompt_basename = Path(prompt_file).name
        stability_markers = STABILITY_MARKERS.get(prompt_basename)
        if stability_markers:
            for marker in stability_markers:
                if marker not in prompt_text:
                    errors.append(f"{prompt_basename} missing stability marker (S1-S5): {marker}")

    # role-contract fragment stability markers
    fragment_path = root / "assets" / "prompts" / "_common" / "role-contract.fragment.md"
    if fragment_path.exists():
        fragment_text = fragment_path.read_text(encoding="utf-8")
        for marker in ROLE_CONTRACT_REQUIRED_MARKERS:
            if marker not in fragment_text:
                errors.append(f"role-contract.fragment.md missing stability marker: {marker}")

    prompt_dir = root / "assets" / "prompts"
    actual_prompts = sorted(
        p.relative_to(root).as_posix()
        for p in prompt_dir.glob("*.md")
        if p.name != "README.txt"
    )
    configured_prompts = sorted(prompt_files)
    orphan_prompts = sorted(set(actual_prompts) - set(configured_prompts))
    if orphan_prompts:
        errors.append(f"Orphan prompt files: {orphan_prompts}")

    if yaml_path.exists():
        yaml_prompts = sorted(extract_yaml_prompt_files(yaml_path.read_text(encoding="utf-8")))
        if yaml_prompts != configured_prompts:
            errors.append("JSON/YAML promptFile parity failed")
    else:
        errors.append("Missing YAML config")

    for schema_name in EXPECTED_SCHEMAS:
        schema_path = root / "schemas" / schema_name
        if not schema_path.exists():
            errors.append(f"Missing schema: schemas/{schema_name}")
        else:
            load_json(schema_path, errors)

    for template_name in EXPECTED_TEMPLATES:
        template_path = root / "assets" / "templates" / template_name
        if not template_path.exists():
            errors.append(f"Missing template: assets/templates/{template_name}")
        elif template_path.stat().st_size == 0:
            errors.append(f"Empty template: assets/templates/{template_name}")

    for script_name in EXPECTED_SCRIPTS:
        if not (root / "scripts" / script_name).exists():
            errors.append(f"Missing harness script: scripts/{script_name}")

    for adapter_path in EXPECTED_ADAPTERS:
        if not (root / adapter_path).exists():
            errors.append(f"Missing technology adapter: {adapter_path}")

    # Process / ontology models + their machine-checkable consistency.
    for model_path in EXPECTED_PROCESS_MODELS:
        p = root / model_path
        if not p.exists():
            errors.append(f"Missing process/ontology model: {model_path}")
        elif p.stat().st_size == 0:
            errors.append(f"Empty process/ontology model: {model_path}")
    try:
        sys.path.insert(0, str((root / "scripts").resolve()))
        from next_step import check_models as _check_process_models
        _pm = _check_process_models(root)
        for e in _pm.get("errors", []):
            errors.append(f"Process model: {e}")
        for w in _pm.get("warnings", []):
            warnings.append(f"Process model: {w}")
    except ImportError:
        errors.append("scripts/next_step.py 不可导入，无法校验流程模型自洽性")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Process model check crashed: {exc}")

    # Upstream-input consumer audit: every docs/input/ artifact and models/* asset
    # must be consumed by at least one role prompt, or be on the script-consumed
    # whitelist. Catches the "contract promises it but no role prompt is wired"
    # break, where an input silently never reaches any role session.
    try:
        from check_input_consumers import audit as _audit_input_consumers
        _ic = _audit_input_consumers(root)
        for b in _ic.get("breaks", []):
            errors.append(b)
    except ImportError:
        errors.append("scripts/check_input_consumers.py 不可导入，无法校验上游输入消费完整性")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Input consumer audit crashed: {exc}")

    for adapter_path in EXPECTED_RUNTIME_ADAPTERS:
        if not (root / adapter_path).exists():
            errors.append(f"Missing runtime adapter: {adapter_path}")

    for case_path in EXPECTED_GOLDEN_CASES:
        full_path = root / case_path
        if not full_path.exists():
            errors.append(f"Missing golden case: {case_path}")
        else:
            load_json(full_path, errors)

    # Role registry consistency: every role in agent-team-config must also be
    # registered in orchestrate.py and build_handoff.py so the runtime never
    # silently drops mandatory roles such as browser-e2e-engineer.
    orchestrate_consts = _load_module_constants(root / "scripts" / "orchestrate.py")
    handoff_consts = _load_module_constants(root / "scripts" / "build_handoff.py")
    role_id_set = set(filter(None, role_ids))
    # development-orchestrator is the dispatcher itself; it never appears in the
    # downstream role timeout / governance maps.
    dispatched_roles = role_id_set - {"development-orchestrator"}
    orch_timeouts = orchestrate_consts.get("ROLE_TIMEOUTS") or {}
    if orch_timeouts:
        missing_orch = sorted(dispatched_roles - set(orch_timeouts.keys()))
        if missing_orch:
            errors.append(f"orchestrate.ROLE_TIMEOUTS missing role registration: {missing_orch}")
        unknown_orch = sorted(set(orch_timeouts.keys()) - dispatched_roles)
        if unknown_orch:
            errors.append(f"orchestrate.ROLE_TIMEOUTS contains unknown roles: {unknown_orch}")
    else:
        errors.append("Cannot load ROLE_TIMEOUTS from orchestrate.py")

    orch_governance = orchestrate_consts.get("ROLE_EXTRA_GOVERNANCE") or {}
    handoff_governance = handoff_consts.get("ROLE_EXTRA_GOVERNANCE") or {}
    if orch_governance and handoff_governance and orch_governance != handoff_governance:
        errors.append(
            "ROLE_EXTRA_GOVERNANCE differs between orchestrate.py and build_handoff.py"
        )

    mandatory_roles = {"browser-e2e-engineer"}
    for mr in mandatory_roles:
        if mr not in role_id_set:
            errors.append(f"Mandatory role '{mr}' not registered in agent-team-config")
        if mr not in route:
            errors.append(f"Mandatory role '{mr}' missing from unified-large-delivery route")

    # Role IO contract validation (P0-1): every dispatched role must declare expectedOutputs.
    for role in roles:
        rid = role.get("id", "")
        if rid == "development-orchestrator":
            continue  # Orchestrator doesn't produce deliverable files directly.
        if "expectedOutputs" not in role or not role["expectedOutputs"]:
            errors.append(f"Role '{rid}' missing expectedOutputs in config (P0-1 compliance)")
        if "expectedInputs" not in role:
            errors.append(f"Role '{rid}' missing expectedInputs in config (P0-1 compliance)")

    # Common fragments and example directory checks (P0-5).
    for frag_path in EXPECTED_COMMON_FRAGMENTS:
        if not (root / frag_path).exists():
            errors.append(f"Missing common fragment: {frag_path}")
    example_dir = root / EXPECTED_EXAMPLE_DIR
    if not example_dir.exists() or not example_dir.is_dir():
        errors.append(f"Missing template examples directory: {EXPECTED_EXAMPLE_DIR}")

    harness = config.get("harness", {})
    for key in ["schemas", "scripts", "templates", "adapters", "runtimeAdapters", "goldenTests"]:
        if key not in harness:
            errors.append(f"Missing harness config section: harness.{key}")

    for reference_path in EXPECTED_REFERENCES:
        if not (root / reference_path).exists():
            errors.append(f"Missing governance reference: {reference_path}")
        if reference_path not in config.get("governance", {}).get("workflowReferences", []):
            errors.append(f"Governance reference missing from config: {reference_path}")

    required_docs = config.get("artifacts", {}).get("requiredDocuments", [])
    for doc in [
        "docs/01-需求规格书.md",
        "docs/02-开发计划.md",
        "docs/03-任务清单.md",
        "docs/04-详细设计说明书.md",
        "docs/07-接口数据契约.md",
        "docs/14-代码评审.md",
        "docs/19-监督审计.md",
        "docs/18-部署说明.md",
    ]:
        if doc not in required_docs:
            errors.append(f"Required document missing from config: {doc}")

    if not errors and not warnings:
        warnings.append("No warnings")

    # P4-11: Template-validator alignment check.
    _check_template_validator_alignment(root, errors, warnings)

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_root", nargs="?", default=".", help="Path to the skill root")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    root = _resolve_skill_root(Path(args.skill_root))
    errors, warnings = check_skill(root)

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
    else:
        print(f"Skill root: {root}")
        print(f"Status: {'PASS' if not errors else 'FAIL'}")
        if errors:
            print("\nErrors:")
            for error in errors:
                print(f"- {error}")
        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"- {warning}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
