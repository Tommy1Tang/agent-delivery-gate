#!/usr/bin/env python3
"""Run golden orchestration tests for software-development-team.

Case kinds (per-case "kind" field, default "orchestration"):
- orchestration: assert on the plan produced by orchestrate.build_plan
- env-preflight: assert on preflight_env_check reports (toolchain version
  gates, deployment-server PostgreSQL/Redis reachability, localhost-DB guard)
  with simulated tool versions -- no real installs or network access
- env-provision-dry-run: assert on provision_env dry-run install plans
  (pinned versions, nvm routing, no local PostgreSQL/Redis commands ever)
- input-contract: assert on validate_input_contract reports for a synthetic
  docs/input/ fixture (broken traceability links, Must capability completeness,
  conditionally-required owner files) -- pure filesystem, no network
- next-step: assert on next_step.resolve pointer output for a synthetic evidence
  ledger + artifact fixture (which node is current, why it is unmet, halt
  handling, fired transition guards, rework re-entries), on
  next_step.check_models model consistency, on the materialised ontology graph,
  and on downstream impact queries
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from orchestrate import build_plan  # noqa: E402


def _deep_contains(actual: dict | list, expected: dict | list) -> list[str]:
    """Recursively check that 'expected' structure is contained in 'actual'.

    Returns a list of key-path mismatches (empty = pass).
    """
    issues: list[str] = []

    def _check(path: str, act, exp):
        if isinstance(exp, dict):
            if not isinstance(act, dict):
                issues.append(f"{path}: expected dict, got {type(act).__name__}")
                return
            for k, v in exp.items():
                if k not in act:
                    issues.append(f"{path}.{k}: missing key")
                else:
                    _check(f"{path}.{k}", act[k], v)
        elif isinstance(exp, list):
            if not isinstance(act, list):
                issues.append(f"{path}: expected list, got {type(act).__name__}")
                return
            for item in exp:
                if item not in act:
                    issues.append(f"{path}: expected item {item!r} not found in list")
        else:
            if act != exp:
                issues.append(f"{path}: expected {exp!r}, got {act!r}")

    _check("plan", actual, expected)
    return issues


@contextlib.contextmanager
def _patched_env(sim: dict, remote: dict):
    """Patch tool/network probes in the env scripts with simulated values.

    sim keys: "java"/"node"/"mvn"/"python" -> raw version-command output
    (omit key = tool not installed), "py312" -> bool (Windows launcher has
    3.12), "nvm"/"postgres"/"redis-server" -> bool (binary present).
    remote keys: "postgresql"/"redis" -> bool reachable (default True).
    """
    import preflight_env_check as pec
    import provision_env as pv

    def fake_version_output(cmd: str, args: list) -> str | None:
        if cmd == "py":
            return "Python 3.12.0" if sim.get("py312") else None
        return sim.get(cmd)

    def fake_which(cmd: str) -> str | None:
        if cmd in ("postgres", "redis-server", "nvm", "winget"):
            return f"C:/fake/{cmd}" if sim.get(cmd) else None
        if cmd == "npm":
            return "C:/fake/npm" if sim.get("node") else None
        if cmd == "py":
            return "C:/fake/py" if sim.get("py312") else None
        return f"C:/fake/{cmd}" if sim.get(cmd) is not None else None

    def fake_tcp(host: str, port: int, timeout: float = 5.0) -> bool:
        if port == 5432:
            return remote.get("postgresql", True)
        if port == 6379:
            return remote.get("redis", True)
        return False

    originals = (pec._version_output, pec._which, pec._tcp_reachable, pv._which)
    pec._version_output = fake_version_output
    pec._which = fake_which
    pec._tcp_reachable = fake_tcp
    pv._which = fake_which
    try:
        yield pec, pv
    finally:
        pec._version_output, pec._which, pec._tcp_reachable, pv._which = originals


def run_env_preflight_case(case_path: Path, case: dict) -> dict:
    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="golden-env-"))
    try:
        for rel, content in case.get("projectFixture", {}).items():
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        with _patched_env(case.get("simulatedTools", {}), case.get("simulatedRemote", {})) as (pec, _pv):
            report = pec.preflight_env_check(tmp, {}, server_ip="203.0.113.10")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if "expectedStatus" in case and report["status"] != case["expectedStatus"]:
        failures.append(f"status expected '{case['expectedStatus']}' got '{report['status']}'")
    for sub in case.get("expectedBlockingContains", []):
        if not any(sub in b for b in report["blocking"]):
            failures.append(f"no blocking issue contains {sub!r} (blocking={report['blocking']})")
    for sub in case.get("expectedWarningsContains", []):
        if not any(sub in w for w in report["warnings"]):
            failures.append(f"no warning contains {sub!r} (warnings={report['warnings']})")
    for sub in case.get("expectedBlockingNotContains", []):
        if any(sub in b for b in report["blocking"]):
            failures.append(f"blocking unexpectedly contains {sub!r}")
    return {"case": case_path.name, "status": "pass" if not failures else "fail", "failures": failures}


def run_env_provision_case(case_path: Path, case: dict) -> dict:
    failures: list[str] = []
    with _patched_env(case.get("simulatedTools", {}), case.get("simulatedRemote", {})) as (_pec, pv):
        report = pv.provision(dry_run=True)

    tools = {t["tool"]: t for t in report["tools"]}
    for tool, expected in case.get("expectedToolStatus", {}).items():
        actual = tools.get(tool, {}).get("status")
        if actual != expected:
            failures.append(f"tool {tool}: status expected '{expected}' got '{actual}'")
    for tool, subs in case.get("expectedPlannedCommandsContain", {}).items():
        planned = " || ".join(tools.get(tool, {}).get("plannedCommands", []))
        for sub in subs:
            if sub not in planned:
                failures.append(f"tool {tool}: planned commands missing {sub!r} (planned={planned!r})")
    if case.get("assertNoLocalDbCommands"):
        for t in report["tools"]:
            for c in t.get("plannedCommands", []):
                lowered = c.lower()
                if "postgres" in lowered or "redis" in lowered:
                    failures.append(f"planned command must never touch postgresql/redis: {c}")
    return {"case": case_path.name, "status": "pass" if not failures else "fail", "failures": failures}


def run_input_contract_case(case_path: Path, case: dict) -> dict:
    """Regression-test the upstream input contract gate.

    The case ships an `inputFixture` map of `docs/input/<file>` -> markdown
    content, so template/regex regressions (e.g. a renamed header column or a
    reintroduced ambiguous ID prefix) fail loudly here instead of silently
    letting the gate pass everything.
    """
    import validate_input_contract as vic

    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="golden-input-"))
    try:
        for rel, content in case.get("inputFixture", {}).items():
            target = tmp / "docs" / "input" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for rel, content in case.get("projectFixture", {}).items():
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        # Baseline package fixture: files under docs/input/models/**. When
        # `baselineAutoManifest` is set, we compute the correct sha256 manifest
        # so C-INPUT-01 starts clean; `baselineTamper` then edits a file
        # AFTER the manifest is written, to prove the hash gate fires.
        baseline_files = case.get("baselineFixture", {})
        if baseline_files:
            import hashlib
            input_dir = tmp / "docs" / "input"
            for rel, content in baseline_files.items():
                target = input_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            if case.get("baselineAutoManifest"):
                entries = []
                for rel in sorted(baseline_files):
                    if rel == "models/baseline-manifest.json":
                        continue
                    data = (input_dir / rel).read_bytes()
                    entries.append({"path": rel,
                                    "sha256": hashlib.sha256(data).hexdigest(),
                                    "role": "spec-source"
                                    if rel.endswith("model-spec.json") else "projection"})
                (input_dir / "models").mkdir(parents=True, exist_ok=True)
                (input_dir / "models" / "baseline-manifest.json").write_text(
                    json.dumps({"baselineId": case.get("baselineId", "BL-GOLDEN"),
                                "specSource": "models/spec/model-spec.json",
                                "hashAlgorithm": "sha256", "files": entries},
                               ensure_ascii=False, indent=2), encoding="utf-8")
            for rel, content in (case.get("baselineTamper") or {}).items():
                (input_dir / rel).write_text(content, encoding="utf-8")

        report = vic.validate(tmp, "docs/input")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if "expectedVerdict" in case and report["verdict"] != case["expectedVerdict"]:
        failures.append(
            f"verdict expected '{case['expectedVerdict']}' got '{report['verdict']}'"
        )

    for field, key in ("expectedBlockingContains", "blocking"), ("expectedMustGapsContains", "mustGaps"), ("expectedWarningsContains", "warnings"):
        for sub in case.get(field, []):
            if not any(sub in item for item in report[key]):
                failures.append(f"no {key} item contains {sub!r} ({key}={report[key]})")

    bl = case.get("expectedBaseline")
    if isinstance(bl, dict):
        actual_bl = report.get("baseline") or {}
        for k, v in bl.items():
            if actual_bl.get(k) != v:
                failures.append(f"baseline[{k}] expected {v!r} got {actual_bl.get(k)!r}")

    for field, key in (("expectedBlockingNotContains", "blocking"),
                       ("expectedMustGapsNotContains", "mustGaps")):
        for sub in case.get(field, []):
            if any(sub in item for item in report[key]):
                failures.append(f"{key} unexpectedly contains {sub!r}")

    for broken_id in case.get("expectedBrokenRefIds", []):
        if not any(ref["id"] == broken_id for ref in report["brokenRefs"]):
            failures.append(
                f"brokenRefs missing {broken_id!r} "
                f"(got={[r['id'] for r in report['brokenRefs']]})"
            )
    if case.get("expectNoBrokenRefs") and report["brokenRefs"]:
        failures.append(
            f"expected no brokenRefs, got {[r['id'] for r in report['brokenRefs']]}"
        )

    expected_caps = case.get("expectedCapabilitySummary")
    if isinstance(expected_caps, dict):
        actual_caps = report.get("capabilitySummary") or {}
        for k, v in expected_caps.items():
            if actual_caps.get(k) != v:
                failures.append(
                    f"capabilitySummary[{k}] expected {v!r} got {actual_caps.get(k)!r}"
                )

    for prefix in case.get("expectedDefinedPrefixes", []):
        if prefix not in (report.get("definedIds") or {}):
            failures.append(
                f"definedIds missing prefix {prefix!r} (got={report.get('definedIds')})"
            )

    return {"case": case_path.name, "status": "pass" if not failures else "fail",
            "failures": failures}


def run_next_step_case(skill_root: Path, case_path: Path, case: dict) -> dict:
    """Regression-test the process-pointer resolver.

    `ledger` is written to evidence-ledger.json and `projectFixture` lays down
    artifacts, so a change to skill-process.json (renamed node, dropped output,
    broken transition) fails loudly here instead of silently letting the
    Orchestrator skip a node.
    """
    import next_step as ns

    failures: list[str] = []

    if case.get("assertModelConsistent"):
        chk = ns.check_models(skill_root)
        if chk["status"] != "pass":
            failures.append(f"model consistency expected pass, got {chk['status']}: "
                            f"{chk['errors'][:3]}")
        for sub in case.get("expectedCheckWarningsNotContains", []):
            if any(sub in w for w in chk["warnings"]):
                failures.append(f"check warnings unexpectedly contains {sub!r}")

    report = None
    if "ledger" in case or "projectFixture" in case or "expectedCurrentNode" in case:
        tmp = Path(tempfile.mkdtemp(prefix="golden-nextstep-"))
        try:
            for rel, content in case.get("projectFixture", {}).items():
                target = tmp / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            if "ledger" in case:
                (tmp / "evidence-ledger.json").write_text(
                    json.dumps(case["ledger"], ensure_ascii=False), encoding="utf-8")
            report = ns.resolve(skill_root, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if report is not None:
        for key, field in (("expectedState", "state"),
                           ("expectedCurrentNode", "currentNode"),
                           ("expectedNodeType", "nodeType"),
                           ("expectedRole", "role")):
            if key in case and report.get(field) != case[key]:
                failures.append(
                    f"{field} expected {case[key]!r} got {report.get(field)!r}")

        expected_progress = case.get("expectedProgress")
        if isinstance(expected_progress, dict):
            for k, v in expected_progress.items():
                if report["progress"].get(k) != v:
                    failures.append(
                        f"progress[{k}] expected {v!r} got {report['progress'].get(k)!r}")

        for sub in case.get("expectedUnmetContains", []):
            if not any(sub in u for u in report.get("unmet", []) or []):
                failures.append(
                    f"no unmet reason contains {sub!r} (unmet={report.get('unmet')})")
        for sub in case.get("expectedCompletedContains", []):
            if not any(sub in c for c in report.get("completedNodes", [])):
                failures.append(f"completedNodes missing {sub!r} "
                                f"(got={report.get('completedNodes')})")
        for sub in case.get("expectedNotApplicableContains", []):
            if not any(sub in c for c in report.get("notApplicableNodes", [])):
                failures.append(f"notApplicableNodes missing {sub!r} "
                                f"(got={report.get('notApplicableNodes')})")

        # Guard evaluation (C-SDT-08): assert which edge actually fired.
        for node_id, expected_via in (case.get("expectedFiredTransitions") or {}).items():
            hit = next((t for t in report.get("traversedPath", [])
                        if t["node"] == node_id), None)
            if hit is None:
                failures.append(f"traversedPath missing node {node_id!r}")
            elif expected_via is None:
                if hit["via"] is not None:
                    failures.append(f"{node_id} via expected null got {hit['via']!r}")
            elif hit["via"] != expected_via:
                failures.append(
                    f"{node_id} via expected {expected_via!r} got {hit['via']!r}")

        if "expectedReworkedNodes" in case:
            actual_rw = report.get("reworkedNodes", [])
            if sorted(actual_rw) != sorted(case["expectedReworkedNodes"]):
                failures.append(f"reworkedNodes expected "
                                f"{case['expectedReworkedNodes']} got {actual_rw}")

    # Materialised ontology graph assertions (缺口1).
    graph_case = case.get("expectedGraph")
    if isinstance(graph_case, dict):
        graph = ns.build_graph(skill_root)
        kinds: dict[str, int] = {}
        for n in graph["nodes"]:
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        preds: dict[str, int] = {}
        for e in graph["edges"]:
            preds[e["predicate"]] = preds.get(e["predicate"], 0) + 1
        for kind, minimum in (graph_case.get("minNodeKinds") or {}).items():
            if kinds.get(kind, 0) < minimum:
                failures.append(f"graph node kind {kind} expected >= {minimum} "
                                f"got {kinds.get(kind, 0)}")
        for pred, minimum in (graph_case.get("minEdgePredicates") or {}).items():
            if preds.get(pred, 0) < minimum:
                failures.append(f"graph predicate {pred} expected >= {minimum} "
                                f"got {preds.get(pred, 0)}")

    # Impact query assertions (缺口1).
    for query, expect in (case.get("expectedImpact") or {}).items():
        rep = ns.impact(skill_root, query)
        if not rep.get("found"):
            failures.append(f"impact({query!r}) not found (hint={rep.get('hint')})")
            continue
        for field in ("directConsumers", "impactedNodes", "impactedRoles"):
            for want in expect.get(field, []):
                if want not in rep[field]:
                    failures.append(
                        f"impact({query!r}).{field} missing {want!r} (got={rep[field]})")
        for field in ("directConsumersNot", "impactedNodesNot"):
            base = field[:-3]
            for unwanted in expect.get(field, []):
                if unwanted in rep[base]:
                    failures.append(
                        f"impact({query!r}).{base} unexpectedly contains {unwanted!r}")

    return {"case": case_path.name, "status": "pass" if not failures else "fail",
            "failures": failures}


def run_owl_traceability_case(case_path: Path, case: dict) -> dict:
    """Regression-test validate_delivery._check_owl_traceability (gate 23).

    `projectFixture` lays down docs/input/02-*.md, docs/input/models/ontology/
    *.owl and docs/数据设计说明书.md. The gate must fail ONLY when an OWL baseline
    plus modeled entities exist but the data design back-links ZERO of them;
    partial coverage and no-baseline cases must pass (OWL->DB is not 1:1).
    """
    import validate_delivery as vd

    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="golden-owl-"))
    try:
        for rel, content in case.get("projectFixture", {}).items():
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        blocking = vd._check_owl_traceability(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if case.get("expectBlocking"):
        if not blocking:
            failures.append("expected owl-traceability blocking, got none")
        for sub in case.get("expectedBlockingContains", []):
            if not any(sub in b for b in blocking):
                failures.append(f"no blocking item contains {sub!r} (got={blocking})")
    elif blocking:
        failures.append(f"expected no owl-traceability blocking, got {blocking}")

    return {"case": case_path.name, "status": "pass" if not failures else "fail",
            "failures": failures}


def run_case(skill_root: Path, case_path: Path) -> dict:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    kind = case.get("kind", "orchestration")
    if kind == "env-preflight":
        return run_env_preflight_case(case_path, case)
    if kind == "env-provision-dry-run":
        return run_env_provision_case(case_path, case)
    if kind == "input-contract":
        return run_input_contract_case(case_path, case)
    if kind == "next-step":
        return run_next_step_case(skill_root, case_path, case)
    if kind == "owl-traceability":
        return run_owl_traceability_case(case_path, case)
    plan = build_plan(
        skill_root,
        Path(case.get("projectRoot", ".")).resolve(),
        case["taskSummary"],
        case.get("workflowDomains", []),
    )
    failures = []

    # P8-8: Support expected abnormal-status assertions (preflight reject, etc.)
    expected_status = case.get("expectedStatus")
    if expected_status:
        actual_status = plan.get("status", "ok")
        if actual_status != expected_status:
            failures.append(f"status expected '{expected_status}' got '{actual_status}'")
        # For abnormal status cases, structural assertions don't apply
        expected_keys = case.get("expectedPlanContainsKeys", [])
        for key in expected_keys:
            if key not in plan:
                failures.append(f"expected key '{key}' not found in plan")
        return {
            "case": case_path.name,
            "status": "pass" if not failures else "fail",
            "failures": failures,
        }

    for domain in case.get("expectedWorkflowDomains", []):
        if domain not in plan["workflowDomains"]:
            failures.append(f"missing workflow domain: {domain}")
    for role_id in case.get("expectedRouteContains", []):
        if role_id not in plan["route"]:
            failures.append(f"missing route role: {role_id}")
    for doc in case.get("expectedRequiredDocuments", []):
        if doc not in plan["requiredDocuments"]:
            failures.append(f"missing required document: {doc}")
    if "expectedUiAffected" in case and plan["uiAffected"] != case["expectedUiAffected"]:
        failures.append(f"uiAffected expected {case['expectedUiAffected']} got {plan['uiAffected']}")
    if "expectedSecuritySensitive" in case and plan["securitySensitive"] != case["expectedSecuritySensitive"]:
        failures.append(f"securitySensitive expected {case['expectedSecuritySensitive']} got {plan['securitySensitive']}")

    # P4-8: Conditional role flag assertions.
    expected_flags = case.get("expectedConditionalRoleFlags")
    if isinstance(expected_flags, dict):
        actual_flags = plan.get("conditionalRoleFlags", {})
        for role_id, expected_val in expected_flags.items():
            actual_val = actual_flags.get(role_id)
            if actual_val != expected_val:
                failures.append(f"conditionalRoleFlags[{role_id}] expected {expected_val} got {actual_val}")
    # P0-5: Snapshot assertion — verify structural fragments of the plan.
    snapshot = case.get("expectedPlanSnapshot")
    if isinstance(snapshot, dict):
        snap_issues = _deep_contains(plan, snapshot)
        for si in snap_issues:
            failures.append(f"snapshot: {si}")

    return {
        "case": case_path.name,
        "status": "pass" if not failures else "fail",
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, help="Path to the skill root")
    parser.add_argument("--cases-dir", help="Golden case directory")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    cases_dir = Path(args.cases_dir).resolve() if args.cases_dir else skill_root / "tests" / "golden"
    results = [run_case(skill_root, case_path) for case_path in sorted(cases_dir.glob("*.json"))]
    ok = all(result["status"] == "pass" for result in results)
    payload = {"ok": ok, "results": results}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Golden tests: {'PASS' if ok else 'FAIL'}")
        for result in results:
            print(f"- {result['status'].upper()} {result['case']}")
            for failure in result["failures"]:
                print(f"  - {failure}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
