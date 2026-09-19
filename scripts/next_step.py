#!/usr/bin/env python3
"""Process-pointer resolver for software-development-team.

Externalises delivery state so the Orchestrator LLM does not have to remember
the workflow. It answers one question mechanically:

    "Given the process model and what the evidence ledger says has already
     happened, which node am I on and what exactly must I do next?"

Modes:
  (default)        resolve the current node + next action for a project
  --check          closed-world consistency check of the process/ontology models
                   (roles, prompts, transitions, reachability, guard syntax)
  --mermaid        emit the derived flowchart view (never hand-maintain it)
  --graph          emit the materialised ontology graph (roles/artifacts/nodes)
  --impact X       downstream impact query: which nodes/roles are blocked if
                   artifact/role/node X is missing or broken
  --record-pointer persist the resolved pointer into the evidence ledger

Reads `assets/config/skill-process.json` (machine truth source). The YAML twin
is for humans only -- PyYAML is not stdlib and this skill stays dependency-free.

Usage:
    python scripts/next_step.py --skill-root . --project-root <dir>
    python scripts/next_step.py --skill-root . --check
    python scripts/next_step.py --skill-root . --mermaid

Exit codes: 0 = actionable/ok, 1 = halted or model inconsistent, 3 = usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

RESERVED_TARGETS = {"REWORK", "SP-HALT", "SP-DONE"}
LEDGER_CANDIDATES = (
    "evidence-ledger.json",
    "docs/evidence-ledger.json",
    "_test_output/evidence-ledger.json",
)

# ---- Transition guard grammar (C-SDT-08) ----------------------------------
# Guards on edges are EVALUABLE, not decorative. Grammar: <var> <op> <value>.
# Variables are typed per node kind; anything outside this grammar fails --check.
GUARD_RE = re.compile(
    r"^\s*(exit|status|verdict|passRate|retries)\s*(==|!=|>=|<=|>|<)\s*([A-Za-z0-9_.\-]+)\s*$"
)
GUARD_VARS_BY_NODE_TYPE = {
    "gate": {"exit", "retries"},
    "role-dispatch": {"status", "verdict", "passRate", "retries"},
}
# Sentinel: guard variable value cannot be derived from the ledger/filesystem.
UNKNOWN = object()

E2E_PASS_RATE_RE = re.compile(r"E2E测试通过率[：:]\s*([\d.]+)")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_process(skill_root: Path) -> dict:
    path = skill_root / "assets" / "config" / "skill-process.json"
    if not path.is_file():
        raise FileNotFoundError(f"process model not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_ontology(skill_root: Path) -> dict | None:
    path = skill_root / "assets" / "config" / "skill-ontology.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_team_config(skill_root: Path) -> dict | None:
    path = skill_root / "assets" / "config" / "agent-team-config.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_ledger(project_root: Path) -> tuple[dict | None, str | None]:
    for rel in LEDGER_CANDIDATES:
        path = project_root / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8")), rel
            except (OSError, json.JSONDecodeError):
                continue
    return None, None


# --------------------------------------------------------------------------
# Satisfaction evaluation (closed world: no record == not done)
# --------------------------------------------------------------------------

def _artifact_present(project_root: Path, paths: list[str]) -> str | None:
    """Return the first existing non-empty alias path, else None."""
    for rel in paths:
        p = project_root / rel
        if p.is_file() and p.stat().st_size > 0:
            return rel
    return None


def _missing_outputs(project_root: Path, node: dict) -> list[str]:
    missing: list[str] = []
    for out in node.get("outputs", []):
        if _artifact_present(project_root, out.get("paths", [])) is None:
            missing.append(f"{out.get('artifact')} ({' | '.join(out.get('paths', []))})")
    return missing


def _role_run(ledger: dict | None, role_id: str) -> dict | None:
    if not ledger:
        return None
    latest = None
    for run in ledger.get("roleRuns", []) or []:
        if run.get("roleId") == role_id:
            latest = run  # last occurrence wins (reruns overwrite)
    return latest


def _command_passed(ledger: dict | None, needle: str) -> dict | None:
    if not ledger:
        return None
    hit = None
    for cmd in ledger.get("commands", []) or []:
        if needle in (cmd.get("command") or ""):
            hit = cmd
    return hit


def _parse_guard(expr: str) -> tuple[str, str, str] | None:
    """Parse '<var> <op> <value>' or return None when outside the grammar."""
    m = GUARD_RE.match(expr or "")
    return (m.group(1), m.group(2), m.group(3)) if m else None


def _guard_context(project_root: Path, node: dict, ledger: dict | None) -> dict:
    """Derive guard-variable values for a node from ledger + filesystem.

    Honest tri-state: a variable the ledger cannot answer stays UNKNOWN rather
    than being guessed. `exit` uses the optional commands[].exitCode when
    recorded; otherwise status pass => 0 and status fail => nonzero-unknown
    (enough to decide exit==0 / exit!=0 but not exit==1 vs exit==2).
    """
    ctx: dict = {"exit": UNKNOWN, "status": UNKNOWN, "verdict": UNKNOWN,
                 "passRate": UNKNOWN, "retries": UNKNOWN}

    if node.get("type") == "gate":
        needle = (node.get("satisfiedBy") or {}).get("commandContains", "")
        cmd = _command_passed(ledger, needle) if needle else None
        if cmd is not None:
            if isinstance(cmd.get("exitCode"), int):
                ctx["exit"] = cmd["exitCode"]
            elif cmd.get("status") == "pass":
                ctx["exit"] = 0
            elif cmd.get("status") == "fail":
                ctx["exit"] = "nonzero"  # exit!=0 True, exit==0 False, codes UNKNOWN
            if isinstance(cmd.get("retryCount"), int):
                ctx["retries"] = cmd["retryCount"]
        return ctx

    run = _role_run(ledger, node.get("role", ""))
    if run is not None:
        ctx["status"] = run.get("status", UNKNOWN) or UNKNOWN
        if isinstance(run.get("retryCount"), int):
            ctx["retries"] = run["retryCount"]

    # verdict: read the NATIVE field only (quality-gate.schema.json#/verdict).
    # LAW-4 (no-inference): a missing verdict stays UNKNOWN. We do NOT reverse-
    # engineer it from checks[].status or status — that would be the script
    # guessing a governance decision it is not entitled to make.
    if node.get("role") == "quality-gate-engineer" and ledger:
        verdicts = [g.get("verdict") for g in (ledger.get("qualityGates") or [])
                    if isinstance(g, dict) and g.get("verdict")]
        if verdicts:
            ctx["verdict"] = "BLOCK" if "BLOCK" in verdicts else "PASS"

    # passRate: machine-readable line the E2E report is REQUIRED to carry
    # (SKILL.md RED LINE: 「E2E测试通过率：XX.X%」). No line => UNKNOWN, never
    # inferred from prose.
    if node.get("role") == "browser-e2e-engineer":
        for out in node.get("outputs", []):
            if out.get("artifact") != "E2E测试报告":
                continue
            rel = _artifact_present(project_root, out.get("paths", []))
            if rel:
                try:
                    text = (project_root / rel).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                m = E2E_PASS_RATE_RE.search(text)
                if m:
                    ctx["passRate"] = float(m.group(1))
    return ctx


def _eval_guard(expr: str, ctx: dict) -> bool | None:
    """Evaluate a guard against a context. None = undecidable (UNKNOWN input)."""
    parsed = _parse_guard(expr)
    if parsed is None:
        return None
    var, op, raw = parsed
    actual = ctx.get(var, UNKNOWN)
    if actual is UNKNOWN:
        return None

    if actual == "nonzero" and var == "exit":
        if op == "==" and raw == "0":
            return False
        if op == "!=" and raw == "0":
            return True
        return None  # cannot distinguish exit==1 from exit==2 without exitCode

    try:
        expected: object = float(raw)
        actual_num = float(actual)  # type: ignore[arg-type]
        a, b = actual_num, expected
    except (TypeError, ValueError):
        if op not in ("==", "!="):
            return None  # ordering comparison on non-numeric values
        a, b = str(actual), str(raw)
    return {
        "==": a == b, "!=": a != b,
        ">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b,  # type: ignore[operator]
    }[op]


def _fired_transition(project_root: Path, node: dict, ledger: dict | None) -> str | None:
    """Which forward edge actually fired for a satisfied node (first True guard)."""
    ctx = _guard_context(project_root, node, ledger)
    for tr in node.get("transitions", []):
        if tr.get("to") in RESERVED_TARGETS or tr.get("haltStatus"):
            continue
        if _eval_guard(tr.get("on", ""), ctx) is True:
            return f"{tr.get('on')} -> {tr.get('to')}"
    return None


def _occurrences(ledger: dict | None, node: dict) -> int:
    """How many times this node ran (rework re-entries show up here)."""
    if not ledger:
        return 0
    if node.get("type") == "gate":
        needle = (node.get("satisfiedBy") or {}).get("commandContains", "")
        return sum(1 for c in ledger.get("commands", []) or []
                   if needle and needle in (c.get("command") or ""))
    role = node.get("role", "")
    return sum(1 for r in ledger.get("roleRuns", []) or [] if r.get("roleId") == role)


def _node_applicable(project_root: Path, node: dict, ledger: dict | None) -> tuple[bool, str]:
    """Decide whether a node applies to this delivery.

    Returns (applicable, reason). Conditional nodes are never silently skipped:
    when no decision has been recorded they stay applicable and are reported as
    requiring an explicit objective-criteria decision.
    """
    when = node.get("when", "always")
    if when == "always":
        return True, "always"
    if when == "input-contract-mode":
        if (project_root / "docs" / "input").is_dir():
            return True, "docs/input/ 存在，上游输入契约模式启用"
        return False, "docs/input/ 不存在，本节点不适用"
    if when == "conditional":
        run = _role_run(ledger, node.get("role", ""))
        if run is not None:
            return True, f"已有决策记录（status={run.get('status')}）"
        return True, "条件角色，尚无决策记录 —— 必须按客观条件显式裁定派发或跳过"
    return True, f"未知 when 值 '{when}'，保守视为适用"


def _load_code_artifact(project_root: Path, reference: object) -> dict | None:
    if not isinstance(reference, dict):
        return None
    raw_path = reference.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    unresolved = project_root / raw_path
    if unresolved.is_symlink():
        return None
    candidate = unresolved.resolve(strict=False)
    try:
        candidate.relative_to(project_root.resolve(strict=True))
    except ValueError:
        return None
    if not candidate.is_file() or candidate.is_symlink():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _node_satisfied(project_root: Path, process: dict, node: dict, ledger: dict | None) -> tuple[bool, list[str]]:
    """Closed-world satisfaction. Returns (satisfied, unmet_reasons)."""
    unmet: list[str] = []
    spec = node.get("satisfiedBy") or {}
    node_type = node.get("type")

    if node_type == "terminal":
        return False, ["terminal 节点不参与满足判定"]

    # Code-intelligence entry/revalidation gates are declared by node, not
    # inferred from role names or node ids. They are no-ops for objectively
    # non-code deliveries and fail closed for applicable code changes.
    required_code_gates = node.get("requiredCodeGates", [])
    if required_code_gates:
        try:
            from validate_code_intelligence import has_code_change
            from code_gate_mode import explain_code_gate_mode
            code_applicable = has_code_change(ledger or {})
        except ImportError:
            code_applicable = True
            unmet.append("C-CODE 校验器不可导入，无法证明代码智能门禁")
        if code_applicable:
            code = (ledger or {}).get("codeIntelligence")
            recorded = {
                row.get("gateId"): row
                for row in (code or {}).get("gateResults", [])
                if isinstance(row, dict)
            } if isinstance(code, dict) else {}
            inventory = _load_code_artifact(project_root, code.get("bootstrapInventory")) if isinstance(code, dict) else None
            decision = explain_code_gate_mode(ledger or {}, process, inventory)
            mode = decision.get("mode")
            if mode == "blocked":
                unmet.append(f"代码智能模式 BLOCK: {decision.get('code')}（{'; '.join(str(item) for item in decision.get('reasons', []))}）")
            for gate_id in required_code_gates:
                row = recorded.get(gate_id) or {}
                verdict = row.get("verdict")
                if mode == "bootstrap" and gate_id == "C-CODE-05":
                    if verdict != "NOT_APPLICABLE" or row.get("code") != "BOOTSTRAP_NOT_APPLICABLE":
                        unmet.append(f"{gate_id} bootstrap 需要 NOT_APPLICABLE+BOOTSTRAP_NOT_APPLICABLE，当前为 {verdict or '未记录'}+{row.get('code') or '未记录'}")
                elif mode == "bootstrap" and gate_id == "C-CODE-06":
                    if verdict != "PASS" or row.get("code") != "BOOTSTRAP_BASELINE_CREATED" or row.get("comparisonMode") != "baseline-creation" or row.get("diffClaimed") is not False:
                        unmet.append(f"{gate_id} bootstrap 需要 PASS+BOOTSTRAP_BASELINE_CREATED+baseline-creation+diffClaimed=false")
                elif verdict != "PASS" or row.get("code") in {"BOOTSTRAP_NOT_APPLICABLE", "BOOTSTRAP_BASELINE_CREATED"}:
                    unmet.append(f"{gate_id} normal 需要非 bootstrap PASS 证据，当前为 {verdict or '未记录'}（UNKNOWN/BLOCK 均禁止推进）")

    if node_type == "gate":
        needle = spec.get("commandContains")
        if not needle:
            return False, ["门禁节点缺少 satisfiedBy.commandContains（模型缺陷）"]
        cmd = _command_passed(ledger, needle)
        if cmd is None:
            unmet.append(f"证据账本中没有包含 '{needle}' 的命令记录")
        elif spec.get("requirePass", True) and cmd.get("status") != "pass":
            unmet.append(f"命令 '{needle}' 记录状态为 {cmd.get('status')}，未通过")
        return (not unmet), unmet

    # role-dispatch
    role_id = spec.get("roleRun") or node.get("role", "")
    accept = spec.get("acceptStatuses", ["completed"])
    run = _role_run(ledger, role_id)
    if run is None:
        unmet.append(f"证据账本中没有 {role_id} 的 roleRun 记录")
    elif run.get("status") not in accept:
        unmet.append(f"{role_id} 的 status={run.get('status')}，不在可接受集合 {accept}")
    elif run.get("status") == "skipped":
        reason = run.get("reasonForSkip")
        if not reason:
            unmet.append(f"{role_id} 标记 skipped 但缺少 reasonForSkip（白名单枚举）")
        elif reason == "objective-conditions-met" and not run.get("objectiveConditionsRef"):
            unmet.append(f"{role_id} 以客观条件跳过但缺少 objectiveConditionsRef")

    # Outputs must actually be on disk -- self-reported status is not enough.
    # A skipped node is not expected to produce artifacts.
    skipped = run is not None and run.get("status") == "skipped"
    if not skipped:
        missing = _missing_outputs(project_root, node)
        if missing:
            unmet.append("产出物缺失或为空：" + "; ".join(missing))

    return (not unmet), unmet


# --------------------------------------------------------------------------
# Pointer resolution
# --------------------------------------------------------------------------

def _successors(node: dict) -> list[str]:
    """Forward edges only: rework/halt/terminal edges do not drive progression."""
    out: list[str] = []
    for tr in node.get("transitions", []):
        tgt = tr.get("to")
        if not tgt or tgt in RESERVED_TARGETS:
            continue
        if tr.get("haltStatus"):
            continue
        out.append(tgt)
    return out


def _traversal_order(process: dict) -> list[dict]:
    """Topological order of the forward graph reachable from entry.

    Real graph traversal (not declaration order): follows `transitions` so that
    branch/merge topology is honoured. Repair loops such as SP-01A -> SP-01 are
    broken by ignoring back-edges into already-visited nodes, and repair nodes
    are excluded from progression because they are remediation, not milestones.
    """
    nodes = {n["nodeId"]: n for n in process["nodes"]}
    entry = process.get("entry")

    # 1. Collect the forward-reachable milestone set from entry.
    reachable: list[str] = []
    seen: set[str] = set()
    stack = [entry] if entry in nodes else []
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in nodes:
            continue
        seen.add(cur)
        if nodes[cur].get("type") != "terminal" and not nodes[cur].get("repairFor"):
            reachable.append(cur)
        for nxt in _successors(nodes[cur]):
            stack.append(nxt)

    # 2. Kahn topological sort restricted to that set; ties broken by nodeId so
    #    the order is deterministic across runs.
    in_set = set(reachable)
    indeg = {nid: 0 for nid in in_set}
    adj: dict[str, list[str]] = {nid: [] for nid in in_set}
    for nid in in_set:
        for nxt in _successors(nodes[nid]):
            if nxt in in_set:
                adj[nid].append(nxt)
                indeg[nxt] += 1

    ready = sorted(n for n, d in indeg.items() if d == 0)
    ordered: list[str] = []
    while ready:
        cur = ready.pop(0)
        ordered.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
                ready.sort()

    # 3. Any node left with indegree > 0 sits on a cycle we could not break;
    #    append deterministically so it is still evaluated rather than dropped.
    leftover = sorted(n for n in in_set if n not in set(ordered))
    ordered.extend(leftover)
    return [nodes[nid] for nid in ordered]


def resolve(skill_root: Path, project_root: Path) -> dict:
    process = load_process(skill_root)
    ledger, ledger_path = load_ledger(project_root)

    delivery_status = (ledger or {}).get("deliveryStatus")
    completed: list[str] = []
    skipped: list[str] = []
    not_applicable: list[str] = []
    pending: list[dict] = []
    traversed: list[dict] = []

    for node in _traversal_order(process):
        applicable, why = _node_applicable(project_root, node, ledger)
        if not applicable:
            not_applicable.append(f"{node['nodeId']} {node['name']}（{why}）")
            continue
        satisfied, unmet = _node_satisfied(project_root, process, node, ledger)
        if satisfied:
            run = _role_run(ledger, node.get("role", "")) if node.get("role") else None
            occurrences = _occurrences(ledger, node)
            entry = {
                "node": node["nodeId"],
                "name": node["name"],
                "result": "skipped" if (run and run.get("status") == "skipped") else "completed",
                "via": _fired_transition(project_root, node, ledger),
                "occurrences": occurrences,
                "reworked": occurrences > 1,
            }
            traversed.append(entry)
            if entry["result"] == "skipped":
                skipped.append(f"{node['nodeId']} {node['name']}")
            else:
                completed.append(f"{node['nodeId']} {node['name']}")
        else:
            pending.append({"node": node, "unmet": unmet, "applicableReason": why})

    total = len(completed) + len(skipped) + len(pending)
    report: dict = {
        "tool": "next_step",
        "processId": process.get("processId"),
        "processVersion": process.get("version"),
        "ledgerPath": ledger_path,
        "deliveryStatus": delivery_status,
        "progress": {
            "completed": len(completed),
            "skipped": len(skipped),
            "pending": len(pending),
            "applicableTotal": total,
            "notApplicable": len(not_applicable),
        },
        "completedNodes": completed,
        "skippedNodes": skipped,
        "notApplicableNodes": not_applicable,
        "traversedPath": traversed,
        "reworkedNodes": [t["node"] for t in traversed if t["reworked"]],
    }

    # Halted deliveries must not be silently advanced.
    if delivery_status and delivery_status.startswith(("halted", "failed")):
        report.update({
            "state": "halted",
            "currentNode": "SP-HALT",
            "nodeName": "中断挂起",
            "action": f"交付已挂起（deliveryStatus={delivery_status}）。禁止继续推进；"
                      "按 references/halt-and-resume-policy.md 处理并等待用户裁决。",
            "blockedBy": [delivery_status],
        })
        return report

    if not pending:
        report.update({
            "state": "ready-for-done",
            "currentNode": process["terminals"]["done"],
            "nodeName": "交付完成",
            "action": "全部适用节点已满足。确认 SP-18 交付验收门禁 exit==0 后方可宣布完成。",
            "blockedBy": [],
        })
        return report

    head = pending[0]
    node = head["node"]
    if node.get("type") == "gate":
        action = f"执行门禁命令：{node.get('command')}"
    else:
        action = (f"在独立 session 中派发角色 {node.get('role')}"
                  f"（prompt: {node.get('promptFile')}）")

    report.update({
        "state": "actionable",
        "currentNode": node["nodeId"],
        "nodeName": node["name"],
        "nodeType": node.get("type"),
        "phase": node.get("phase"),
        "role": node.get("role"),
        "promptFile": node.get("promptFile"),
        "command": node.get("command"),
        "action": action,
        "applicableReason": head["applicableReason"],
        "unmet": head["unmet"],
        "expectedOutputs": [
            {"artifact": o.get("artifact"), "paths": o.get("paths", [])}
            for o in node.get("outputs", [])
        ],
        "handoffInputs": node.get("inputs", []),
        "postcondition": node.get("postcondition"),
        "transitions": node.get("transitions", []),
        "hardThresholds": node.get("hardThresholds"),
        "entryPrecondition": node.get("entryPrecondition"),
        "parallelPrecondition": node.get("parallelPrecondition"),
        "skippable": node.get("skippable"),
        "conditionSummary": node.get("conditionSummary"),
        "conditionRef": node.get("conditionRef"),
        "governance": node.get("governance", []),
        "notes": node.get("notes"),
        "downstreamPending": [
            f"{p['node']['nodeId']} {p['node']['name']}" for p in pending[1:]
        ],
        "blockedBy": [],
    })
    return report


# --------------------------------------------------------------------------
# --check : closed-world model consistency
# --------------------------------------------------------------------------

def check_models(skill_root: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    process = load_process(skill_root)
    ontology = load_ontology(skill_root)
    team = load_team_config(skill_root)

    nodes = {n["nodeId"]: n for n in process["nodes"]}
    if len(nodes) != len(process["nodes"]):
        errors.append("C-SDT-03: 存在重复的 nodeId")

    known_roles = {r["id"] for r in (team or {}).get("roles", [])} if team else set()
    non_skippable = set()
    if ontology:
        for cls in ontology.get("classes", []):
            if cls.get("classId") == "Role":
                non_skippable = set(cls.get("nonSkippable", []))

    for node in process["nodes"]:
        nid = node["nodeId"]
        ntype = node.get("type")

        # C-SDT-01 / C-SDT-02
        if ntype == "role-dispatch":
            role = node.get("role")
            if not role:
                errors.append(f"C-SDT-01: {nid} 是 role-dispatch 但缺少 role 字段")
            elif known_roles and role not in known_roles:
                errors.append(f"C-SDT-01: {nid} 的 role '{role}' 不在 agent-team-config.json#/roles")
            prompt = node.get("promptFile")
            if not prompt:
                errors.append(f"C-SDT-02: {nid} 缺少 promptFile")
            elif not (skill_root / prompt).is_file():
                errors.append(f"C-SDT-02: {nid} 的 promptFile 不存在：{prompt}")
            # C-SDT-04
            if role in non_skippable and node.get("skippable") is not False:
                errors.append(f"C-SDT-04: {nid} 的角色 '{role}' 属不可跳过角色，skippable 必须为 false")

        # C-SDT-06
        if ntype == "gate":
            if not node.get("command"):
                errors.append(f"C-SDT-06: {nid} 是 gate 但缺少 command")
            if not (node.get("satisfiedBy") or {}).get("commandContains"):
                errors.append(f"C-SDT-06: {nid} 是 gate 但缺少 satisfiedBy.commandContains")

        # C-SDT-03
        for tr in node.get("transitions", []):
            target = tr.get("to")
            if not target:
                errors.append(f"C-SDT-03: {nid} 有 transition 缺少 to")
            elif target not in nodes and target not in RESERVED_TARGETS:
                errors.append(f"C-SDT-03: {nid} 的 transition 目标 '{target}' 未定义")

        # C-SDT-08: every guard must be inside the evaluable grammar, with a
        # variable valid for this node kind. Guards are executable, not prose.
        allowed_vars = GUARD_VARS_BY_NODE_TYPE.get(ntype, set())
        for tr in node.get("transitions", []):
            expr = tr.get("on")
            if not expr:
                if ntype != "terminal":
                    errors.append(f"C-SDT-08: {nid} 有 transition 缺少 on 守卫表达式")
                continue
            parsed = _parse_guard(expr)
            if parsed is None:
                errors.append(
                    f"C-SDT-08: {nid} 的守卫 '{expr}' 不符合可求值语法 "
                    "<var> <op> <value>（var ∈ exit/status/verdict/passRate/retries）"
                )
            elif allowed_vars and parsed[0] not in allowed_vars:
                errors.append(
                    f"C-SDT-08: {nid}（{ntype}）的守卫变量 '{parsed[0]}' 非法，"
                    f"该节点类型允许: {sorted(allowed_vars)}"
                )

        # C-SDT-10 (LAW-3 declared-not-inferred): a glob input must never be
        # the only signal that a node depends on many artifacts. Scripts do not
        # interpret globs; the model must declare consumesAllArtifacts.
        globs = [i for i in node.get("inputs", []) if "**" in str(i)]
        delivery_globs = [g for g in globs if not str(g).startswith("docs/input/")]
        if delivery_globs and node.get("consumesAllArtifacts") is not True:
            errors.append(
                f"C-SDT-10: {nid} 的 inputs 含交付目录 glob {delivery_globs}，"
                "必须同时显式声明 consumesAllArtifacts: true（脚本不解释 glob 语义）"
            )
        if node.get("consumesAllArtifacts") is True and ntype != "role-dispatch":
            errors.append(f"C-SDT-10: {nid} 非 role-dispatch 节点不得声明 consumesAllArtifacts")

    # C-SDT-05
    declared: set[str] = set()
    for ph in process.get("phases", []):
        for nid in ph.get("nodes", []):
            declared.add(nid)
            if nid not in nodes:
                errors.append(f"C-SDT-05: phases 引用了未定义节点 {nid}")
            elif nodes[nid].get("phase") != ph["phase"]:
                errors.append(
                    f"C-SDT-05: {nid} 的 phase='{nodes[nid].get('phase')}' "
                    f"与 phases 声明 '{ph['phase']}' 不一致"
                )
    for nid, node in nodes.items():
        if node.get("type") == "terminal":
            continue
        if nid not in declared:
            warnings.append(f"C-SDT-05: {nid} 未出现在任何 phase 的 nodes 列表中")

    # C-SDT-07 reachability from entry
    entry = process.get("entry")
    if entry not in nodes:
        errors.append(f"C-SDT-07: entry '{entry}' 未定义")
    else:
        seen: set[str] = set()
        stack = [entry]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in nodes:
                continue
            seen.add(cur)
            for tr in nodes[cur].get("transitions", []):
                tgt = tr.get("to")
                if tgt in nodes:
                    stack.append(tgt)
                elif tgt == "SP-DONE":
                    seen.add("SP-DONE")
                elif tgt == "SP-HALT":
                    seen.add("SP-HALT")
        done = process["terminals"]["done"]
        if done not in seen:
            errors.append(f"C-SDT-07: 从 entry '{entry}' 无法到达 '{done}'")
        orphans = sorted(set(nodes) - seen)
        for o in orphans:
            errors.append(f"C-SDT-07: 节点 {o} 从 entry 不可达（孤立节点）")

    if ontology is None:
        warnings.append("assets/config/skill-ontology.json 不存在，本体约束未校验")
    for twin in ("skill-process.yaml", "skill-ontology.yaml"):
        if not (skill_root / "assets" / "config" / twin).is_file():
            warnings.append(f"人类编辑孪生缺失：assets/config/{twin}")

    # C-SDT-11 (LAW-4 no-inference): every guard variable must have a NATIVE
    # field to read from. If a guard says verdict==PASS, the schema must define
    # `verdict`; otherwise the script would be forced to infer it.
    guard_field_sources = {
        "verdict": ("schemas/quality-gate.schema.json", "verdict"),
        "exit": ("schemas/evidence-ledger.schema.json", "exitCode"),
        "status": ("schemas/evidence-ledger.schema.json", "status"),
        "retries": ("schemas/evidence-ledger.schema.json", "retryCount"),
    }
    used_vars: set[str] = set()
    for node in process["nodes"]:
        for tr in node.get("transitions", []):
            parsed = _parse_guard(tr.get("on", ""))
            if parsed:
                used_vars.add(parsed[0])
    for var in sorted(used_vars):
        src = guard_field_sources.get(var)
        if src is None:
            continue  # passRate reads a documented machine-readable report line
        schema_rel, field = src
        schema_path = skill_root / schema_rel
        if not schema_path.is_file():
            errors.append(f"C-SDT-11: 守卫变量 '{var}' 依赖的 schema 缺失：{schema_rel}")
            continue
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"C-SDT-11: {schema_rel} 不是合法 JSON ({exc})")
            continue
        if field not in json.dumps(schema, ensure_ascii=False):
            errors.append(
                f"C-SDT-11: 守卫变量 '{var}' 需要原生字段 {schema_rel}#/{field}，"
                "但 schema 未定义——禁止由其他字段反推（LAW-4）"
            )

    # C-SDT-09: ontology relations must be materialisable into a real graph.
    try:
        graph = build_graph(skill_root)
        producers: dict[str, list[str]] = {}
        for edge in graph["edges"]:
            if edge["predicate"] == "produces" and edge["subject"].startswith("node:"):
                producers.setdefault(edge["object"], []).append(edge["subject"])
        for art, prods in sorted(producers.items()):
            if len(prods) > 1:
                errors.append(f"C-SDT-09: 交付物 {art} 有多个生产节点 {prods}，所有权不唯一")
        consumed = {e["object"] for e in graph["edges"] if e["predicate"] == "requires"}
        for art_id in sorted(a["id"] for a in graph["nodes"] if a["kind"] == "artifact"):
            if art_id not in consumed:
                warnings.append(f"C-SDT-09: {art_id} 无任何下游消费边（requires），确认是否终端产物")
    except Exception as exc:  # noqa: BLE001 - graph failure is a model failure
        errors.append(f"C-SDT-09: 本体图物化失败 ({exc})")

    return {
        "tool": "next_step --check",
        "processId": process.get("processId"),
        "nodeCount": len(nodes),
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# Materialised ontology graph (缺口1) + impact query
# --------------------------------------------------------------------------

def _strip_doc_number(name: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)*-", "", name)


def build_graph(skill_root: Path) -> dict:
    """Materialise ontology relations into a traversable property graph.

    Until now REL-SDT-* (Role produces Artifact, Artifact requiredBy Role…)
    were declarations nobody could walk. This expands them into concrete
    nodes/edges so questions like 「任务清单缺失会阻塞谁」 become graph queries.
    """
    process = load_process(skill_root)
    g_nodes: list[dict] = []
    g_edges: list[dict] = []
    seen_roles: set[str] = set()
    artifact_alias: dict[str, str] = {}  # stripped basename -> artifact id

    for node in process["nodes"]:
        nid = node["nodeId"]
        g_nodes.append({
            "id": f"node:{nid}", "kind": "process-node", "name": node.get("name"),
            "type": node.get("type"), "phase": node.get("phase"),
            "skippable": node.get("skippable"),
        })
        role = node.get("role")
        if role:
            if role not in seen_roles:
                seen_roles.add(role)
                g_nodes.append({"id": f"role:{role}", "kind": "role", "name": role})
            g_edges.append({"subject": f"node:{nid}", "predicate": "dispatches",
                            "object": f"role:{role}"})
        for out in node.get("outputs", []) + node.get("conditionalOutputs", []):
            art = out.get("artifact")
            if not art:
                continue
            art_id = f"artifact:{art}"
            if art_id not in {n["id"] for n in g_nodes}:
                g_nodes.append({"id": art_id, "kind": "artifact", "name": art,
                                "paths": out.get("paths", [])})
            g_edges.append({"subject": f"node:{nid}", "predicate": "produces",
                            "object": art_id})
            if role:
                g_edges.append({"subject": f"role:{role}", "predicate": "produces",
                                "object": art_id})
            for p in out.get("paths", []):
                artifact_alias[_strip_doc_number(Path(p).name)] = art_id
        for nxt in _successors(node):
            g_edges.append({"subject": f"node:{nid}", "predicate": "precedes",
                            "object": f"node:{nxt}"})

    # `requires` edges resolved AFTER all artifacts are known.
    # LAW-3 (declared-not-inferred): a node that consumes every delivery
    # artifact MUST say so with `consumesAllArtifacts: true` in the process
    # model. We do NOT interpret glob strings like "docs/**" — guessing what a
    # glob means is exactly the kind of script-side judgement this design bans.
    all_artifacts = sorted(set(artifact_alias.values()))
    for node in process["nodes"]:
        nid = node["nodeId"]
        if node.get("consumesAllArtifacts") is True:
            for art_id in all_artifacts:
                g_edges.append({"subject": f"node:{nid}",
                                "predicate": "requires", "object": art_id})
        for inp in node.get("inputs", []):
            art_id = artifact_alias.get(_strip_doc_number(Path(inp).name))
            if art_id:
                g_edges.append({"subject": f"node:{nid}",
                                "predicate": "requires", "object": art_id})

    return {"graphId": "GRAPH-SDT-MATERIALISED",
            "source": ["assets/config/skill-process.json",
                       "assets/config/skill-ontology.json"],
            "nodes": g_nodes, "edges": g_edges}


def impact(skill_root: Path, query: str) -> dict:
    """Downstream impact closure for an artifact / role / process node."""
    graph = build_graph(skill_root)
    ids = {n["id"] for n in graph["nodes"]}
    by_pred: dict[str, list[dict]] = {}
    for e in graph["edges"]:
        by_pred.setdefault(e["predicate"], []).append(e)

    # Normalise the query into a graph id.
    q = query.strip()
    if f"node:{q}" in ids:
        subject, kind = f"node:{q}", "process-node"
    elif f"role:{q}" in ids:
        subject, kind = f"role:{q}", "role"
    elif f"artifact:{q}" in ids:
        subject, kind = f"artifact:{q}", "artifact"
    elif q in ids:
        subject, kind = q, q.split(":", 1)[0]
    else:
        return {"tool": "next_step --impact", "query": q, "found": False,
                "hint": sorted(i for i in ids if q in i)[:10]}

    # Seed nodes whose progress is directly broken by the query subject.
    if kind == "artifact":
        seeds = {e["subject"] for e in by_pred.get("requires", [])
                 if e["object"] == subject}
    elif kind == "role":
        seeds = {e["subject"] for e in by_pred.get("dispatches", [])
                 if e["object"] == subject}
    else:
        seeds = {subject}

    # Downstream closure over precedes.
    succ: dict[str, list[str]] = {}
    for e in by_pred.get("precedes", []):
        succ.setdefault(e["subject"], []).append(e["object"])
    impacted: set[str] = set()
    stack = list(seeds)
    while stack:
        cur = stack.pop()
        if cur in impacted:
            continue
        impacted.add(cur)
        stack.extend(succ.get(cur, []))

    impacted_roles = sorted({e["object"] for e in by_pred.get("dispatches", [])
                             if e["subject"] in impacted})
    impacted_artifacts = sorted({e["object"] for e in by_pred.get("produces", [])
                                 if e["subject"] in impacted})
    return {
        "tool": "next_step --impact",
        "query": q, "resolvedAs": subject, "kind": kind, "found": True,
        "directConsumers": sorted(seeds),
        "impactedNodes": sorted(impacted),
        "impactedRoles": impacted_roles,
        "impactedArtifacts": impacted_artifacts,
    }


# --------------------------------------------------------------------------
# Pointer persistence (缺口3): write side of externalised state
# --------------------------------------------------------------------------

def record_pointer(project_root: Path, report: dict) -> str | None:
    """Persist the resolved pointer into the evidence ledger (processPointer).

    The replay stays authoritative — this is a durable trace so rework
    re-entries and fired edges are visible on the graph history, not just
    recomputable. No ledger file, no write (we never create ledgers here).
    """
    rel = report.get("ledgerPath")
    if not rel:
        return None
    path = project_root / rel
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ledger["processPointer"] = {
        "currentNode": report.get("currentNode"),
        "state": report.get("state"),
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "traversedPath": report.get("traversedPath", []),
        "reworkedNodes": report.get("reworkedNodes", []),
    }
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return rel


# --------------------------------------------------------------------------
# --mermaid : derived view
# --------------------------------------------------------------------------

def render_mermaid(skill_root: Path, wrap_markdown: bool = False) -> str:
    process = load_process(skill_root)
    nodes = {n["nodeId"]: n for n in process["nodes"]}
    shape = {"gate": ("{{", "}}"), "role-dispatch": ("[", "]"), "terminal": ("([", "])")}

    lines = [
        "%% AUTO-GENERATED by scripts/next_step.py --mermaid -- DO NOT EDIT BY HAND.",
        f"%% source: assets/config/skill-process.json ({process.get('processId')} "
        f"v{process.get('version')})",
        "flowchart TD",
    ]
    for nid, node in nodes.items():
        open_b, close_b = shape.get(node.get("type"), ("[", "]"))
        label = f"{nid}<br/>{node['name']}"
        lines.append(f"    {nid.replace('-', '_')}{open_b}\"{label}\"{close_b}")

    lines.append("")
    for nid, node in nodes.items():
        src = nid.replace("-", "_")
        for tr in node.get("transitions", []):
            tgt = tr.get("to", "")
            on = tr.get("on", "")
            if tgt == "REWORK":
                target_id = f"{src}_REWORK"
                lines.append(f'    {target_id}[/"返工：{tr.get("reworkTarget", "定向回调")}"/]')
                lines.append(f'    {src} -.->|"{on}"| {target_id}')
            else:
                lines.append(f'    {src} -->|"{on}"| {tgt.replace("-", "_")}')

    lines.append("")
    lines.append("    classDef gate fill:#FFA940,stroke:#333,color:#000;")
    lines.append("    classDef term fill:#52C41A,stroke:#333,color:#000;")
    gate_ids = [n.replace("-", "_") for n, v in nodes.items() if v.get("type") == "gate"]
    term_ids = [n.replace("-", "_") for n, v in nodes.items() if v.get("type") == "terminal"]
    if gate_ids:
        lines.append(f"    class {','.join(gate_ids)} gate;")
    if term_ids:
        lines.append(f"    class {','.join(term_ids)} term;")
    diagram = "\n".join(lines)

    if not wrap_markdown:
        return diagram

    return "\n".join([
        "# Skill Delivery Process — Flowchart(派生视图）",
        "",
        "> 🔴 本文件由 `python scripts/next_step.py --mermaid-out` 自动生成，"
        "**禁止手工维护**。",
        "> 流程真理源：`assets/config/skill-process.json`（人类编辑孪生："
        "`assets/config/skill-process.yaml`）。",
        "> 改流程请改真理源后重新生成本文件。",
        "",
        "图形语义：六边形 = 门禁节点（跑脚本），矩形 = 角色派发节点，"
        "圆角 = 终止节点，虚线 = 返工边。",
        "",
        "```mermaid",
        diagram,
        "```",
    ])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_human(report: dict) -> None:
    state = report.get("state")
    icon = {"actionable": "[NEXT]", "halted": "[HALT]", "ready-for-done": "[DONE?]"}.get(state, "[?]")
    prog = report["progress"]
    print(f"{icon} {report.get('currentNode')} {report.get('nodeName')}")
    print(f"       process: {report.get('processId')} v{report.get('processVersion')}")
    print(f"       ledger : {report.get('ledgerPath') or '(未找到证据账本，按全新交付处理)'}")
    print(f"       progress: 已完成 {prog['completed']} / 跳过 {prog['skipped']} / "
          f"待办 {prog['pending']}（适用节点 {prog['applicableTotal']}，"
          f"不适用 {prog['notApplicable']}）")
    print(f"       action : {report.get('action')}")
    for reason in report.get("unmet", []) or []:
        print(f"       - [未满足] {reason}")
    for out in report.get("expectedOutputs", []) or []:
        print(f"       - [产出] {out['artifact']} -> {' | '.join(out['paths'])}")
    if report.get("postcondition"):
        print(f"       - [后置校验] {report['postcondition']}")
    if report.get("entryPrecondition"):
        print(f"       - [准入前置] {report['entryPrecondition']}")
    if report.get("parallelPrecondition"):
        print(f"       - [并行前置] {report['parallelPrecondition']}")
    if report.get("skippable") and report.get("conditionSummary"):
        print(f"       - [条件角色] 客观条件：{report['conditionSummary']}"
              f"（依据 {report.get('conditionRef')}）")
    for th_k, th_v in (report.get("hardThresholds") or {}).items():
        print(f"       - [硬指标] {th_k} = {th_v}")
    if report.get("notes"):
        print(f"       - [注意] {report['notes']}")
    for b in report.get("blockedBy", []) or []:
        print(f"       - [阻塞] {b}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the current delivery process node and next action.")
    parser.add_argument("--skill-root", default=".", help="Skill root directory")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--check", action="store_true",
                        help="Closed-world consistency check of the process/ontology models")
    parser.add_argument("--mermaid", action="store_true",
                        help="Emit the derived mermaid flowchart view")
    parser.add_argument("--mermaid-out", help="Write the mermaid view to this path")
    parser.add_argument("--graph", action="store_true",
                        help="Emit the materialised ontology graph as JSON")
    parser.add_argument("--graph-out", help="Write the materialised graph to this path")
    parser.add_argument("--impact", metavar="X",
                        help="Downstream impact query for an artifact/role/node "
                             "(e.g. 任务清单 / backend-engineer / SP-06)")
    parser.add_argument("--record-pointer", action="store_true",
                        help="Persist the resolved pointer into the evidence ledger "
                             "(processPointer field)")
    args = parser.parse_args(argv)

    skill_root = Path(args.skill_root).resolve()
    if not skill_root.is_dir():
        print(f"error: skill root not found: {skill_root}", file=sys.stderr)
        return 3

    try:
        if args.check:
            report = check_models(skill_root)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(f"Process model check: {report['status'].upper()} "
                      f"({report['nodeCount']} nodes)")
                for e in report["errors"]:
                    print(f"  - [ERROR] {e}")
                for w in report["warnings"]:
                    print(f"  - [WARN ] {w}")
            return 0 if report["status"] == "pass" else 1

        if args.mermaid or args.mermaid_out:
            if args.mermaid_out:
                out = Path(args.mermaid_out)
                if not out.is_absolute():
                    out = skill_root / out
                out.parent.mkdir(parents=True, exist_ok=True)
                wrap = out.suffix.lower() == ".md"
                out.write_text(render_mermaid(skill_root, wrap_markdown=wrap) + "\n",
                               encoding="utf-8")
                print(f"mermaid view written to {out}")
            else:
                print(render_mermaid(skill_root))
            return 0

        if args.graph or args.graph_out:
            graph = build_graph(skill_root)
            payload = json.dumps(graph, ensure_ascii=False, indent=2)
            if args.graph_out:
                out = Path(args.graph_out)
                if not out.is_absolute():
                    out = skill_root / out
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(payload + "\n", encoding="utf-8")
                print(f"materialised graph written to {out} "
                      f"({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)")
            else:
                print(payload)
            return 0

        if args.impact:
            report = impact(skill_root, args.impact)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            elif not report["found"]:
                print(f"[IMPACT] '{report['query']}' 未在图中找到；相近候选: {report['hint']}")
            else:
                print(f"[IMPACT] {report['resolvedAs']}（{report['kind']}）")
                print(f"       直接消费节点: {', '.join(report['directConsumers']) or '无'}")
                print(f"       波及节点({len(report['impactedNodes'])}): "
                      + ", ".join(report["impactedNodes"]))
                print(f"       波及角色({len(report['impactedRoles'])}): "
                      + ", ".join(report["impactedRoles"]))
                print(f"       波及产物({len(report['impactedArtifacts'])}): "
                      + ", ".join(report["impactedArtifacts"]))
            return 0 if report["found"] else 1

        project_root = Path(args.project_root).resolve()
        if not project_root.is_dir():
            print(f"error: project root not found: {project_root}", file=sys.stderr)
            return 3
        report = resolve(skill_root, project_root)
        if args.record_pointer:
            written = record_pointer(project_root, report)
            report["pointerRecorded"] = written
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_human(report)
            if args.record_pointer:
                print(f"       - [指针已记录] {report.get('pointerRecorded') or '(无台账，未写入)'}")
        return 1 if report.get("state") == "halted" else 0

    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
