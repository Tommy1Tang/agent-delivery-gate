from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import next_step
from scripts.orchestrate import initial_ledger
from scripts import validate_delivery as delivery
from scripts.validate_delivery import _scan_placeholders, derive_role_policy
from scripts.materialize_trace_links import load_requirement_catalog
from scripts.validate_code_traceability import main as traceability_main, validate_traceability
from scripts.write_evidence_ledger import parse_role_run
from tests.code_intelligence.helpers import clone, snapshot, trace


class DeliveryPolicyTests(unittest.TestCase):
    def test_role_policy_is_derived_from_process(self) -> None:
        process = json.loads((Path(__file__).parents[2] / "assets" / "config" / "skill-process.json").read_text(encoding="utf-8"))
        policy = derive_role_policy(process)
        self.assertEqual(
            policy["objectiveSkippableRoles"],
            {
                "data-engineer",
                "performance-engineer",
                "ui-designer",
                "execution-engineer",
                "backend-engineer",
                "frontend-engineer",
            },
        )
        self.assertIn("data-contract-designer", policy["mandatoryRoles"])
        self.assertIn("architect", policy["mandatoryRoles"])
        self.assertIn("quality-gate-engineer", policy["mandatoryRoles"])
        self.assertIn("browser-e2e-engineer", policy["mandatoryRoles"])
        self.assertIn("supervisor-auditor", policy["mandatoryRoles"])

    def test_role_policy_requires_skippable_and_skipped_acceptance(self) -> None:
        process = {"nodes": [{"type": "role-dispatch", "role": "role-a", "skippable": True, "satisfiedBy": {"acceptStatuses": ["completed"]}}]}
        policy = derive_role_policy(process)
        self.assertNotIn("role-a", policy["objectiveSkippableRoles"])
        self.assertIn("role-a", policy["mandatoryRoles"])

    def test_placeholder_heading_is_legal_but_bare_body_token_blocks(self) -> None:
        for governed_heading in (
            "## 待确认项",
            "## 发布风险和待确认项",
            "## 风险与待确认项",
        ):
            self.assertEqual(_scan_placeholders(f"{governed_heading}\n\n当前无阻塞项。"), [])
        tokens = _scan_placeholders("## 风险\n\n接口字段待确认，请补充负责人。")
        self.assertIn("待确认", tokens)

    def test_orchestrator_and_writer_emit_the_same_role_run_contract(self) -> None:
        plan = {
            "taskSummary": "contract",
            "createdAt": "2026-08-29T00:00:00Z",
            "deliveryId": "delivery-1",
            "route": ["backend-engineer"],
            "handoffs": [{"roleId": "backend-engineer", "expectedOutputs": ["scripts/app.py"]}],
            "requiredDocuments": [],
        }
        ledger = initial_ledger(plan)
        planned = ledger["roleRuns"][0]
        completed = parse_role_run("backend-engineer|completed|independent-session|done|1|0|")

        self.assertEqual(ledger["deliveryStatus"], "in-progress")
        self.assertEqual(ledger["deliveryGateEvidence"]["status"], "fail")
        self.assertEqual(planned["durationMs"], 0)
        self.assertIsNone(planned["changeSet"])
        self.assertEqual(completed["changeSet"], {"modified": [], "created": [], "deleted": []})

    def test_draft_202012_schema_accepts_planned_and_completed_role_shapes(self) -> None:
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("Draft 2020-12 validator is not installed")
        root = Path(__file__).parents[2]
        schema = json.loads((root / "schemas" / "evidence-ledger.schema.json").read_text(encoding="utf-8"))
        registry = Registry()
        for path in (root / "schemas").glob("*.schema.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in value:
                registry = registry.with_resource(value["$id"], Resource.from_contents(value))
        plan = {
            "taskSummary": "contract", "createdAt": "2026-08-29T00:00:00Z", "deliveryId": "delivery-1",
            "route": ["backend-engineer"],
            "handoffs": [{"roleId": "backend-engineer", "expectedOutputs": ["scripts/app.py"]}],
            "requiredDocuments": [],
        }
        ledger = initial_ledger(plan)
        validator = Draft202012Validator(schema, registry=registry)
        self.assertEqual(list(validator.iter_errors(ledger)), [])
        ledger["roleRuns"].append(parse_role_run("backend-engineer|completed|independent-session|done|1|0|"))
        self.assertEqual(list(validator.iter_errors(ledger)), [])
        ledger["roleRuns"][-1]["changeSet"] = None
        self.assertTrue(any("changeSet" in error.json_path for error in validator.iter_errors(ledger)))

    def test_next_step_public_graph_pointer_and_fail_closed_guards(self) -> None:
        skill_root = Path(__file__).parents[2]
        checked = next_step.check_models(skill_root)
        graph = next_step.build_graph(skill_root)
        impacted = next_step.impact(skill_root, "backend-engineer")
        missing = next_step.impact(skill_root, "definitely-missing")
        mermaid = next_step.render_mermaid(skill_root, wrap_markdown=True)
        self.assertEqual(checked["status"], "pass")
        self.assertGreater(len(graph["nodes"]), 20)
        self.assertTrue(impacted["found"])
        self.assertFalse(missing["found"])
        self.assertIn("```mermaid", mermaid)

        self.assertTrue(next_step._eval_guard("exit != 0", {"exit": "nonzero"}))
        self.assertFalse(next_step._eval_guard("exit == 0", {"exit": "nonzero"}))
        self.assertIsNone(next_step._eval_guard("exit == 2", {"exit": "nonzero"}))
        self.assertTrue(next_step._eval_guard("passRate >= 100", {"passRate": 100.0}))
        self.assertIsNone(next_step._eval_guard("status > completed", {"status": "completed"}))
        self.assertIsNone(next_step._eval_guard("not a guard", {}))

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            fresh = next_step.resolve(skill_root, project)
            self.assertEqual(fresh["state"], "actionable")
            ledger_path = project / "evidence-ledger.json"
            ledger_path.write_text(json.dumps({"deliveryStatus": "halted-pending-user", "roleRuns": [], "commands": []}), encoding="utf-8")
            halted = next_step.resolve(skill_root, project)
            self.assertEqual(halted["state"], "halted")
            self.assertEqual(next_step.record_pointer(project, halted), "evidence-ledger.json")
            recorded = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(recorded["processPointer"]["currentNode"], "SP-HALT")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(next_step.main(["--skill-root", str(skill_root), "--check", "--json"]), 0)
                self.assertEqual(next_step.main(["--skill-root", str(skill_root), "--impact", "missing", "--json"]), 1)

    def test_next_step_guard_satisfaction_and_all_cli_views(self) -> None:
        skill_root = Path(__file__).parents[2]
        gate = {
            "nodeId": "G", "type": "gate", "satisfiedBy": {"commandContains": "pytest", "requirePass": True},
            "transitions": [{"on": "exit == 0", "to": "N"}, {"on": "exit != 0", "to": "REWORK"}],
        }
        passing_ledger = {"commands": [{"command": "python -m pytest", "status": "pass", "exitCode": 0, "retryCount": 2}]}
        ctx = next_step._guard_context(skill_root, gate, passing_ledger)
        self.assertEqual((ctx["exit"], ctx["retries"]), (0, 2))
        self.assertEqual(next_step._fired_transition(skill_root, gate, passing_ledger), "exit == 0 -> N")
        self.assertEqual(next_step._occurrences(passing_ledger, gate), 1)
        self.assertEqual(next_step._node_satisfied(skill_root, {}, gate, passing_ledger), (True, []))
        failed = {"commands": [{"command": "pytest", "status": "fail"}]}
        self.assertFalse(next_step._node_satisfied(skill_root, {}, gate, failed)[0])
        self.assertFalse(next_step._node_satisfied(skill_root, {}, {"type": "gate", "satisfiedBy": {}}, {})[0])

        role_node = {
            "nodeId": "R", "type": "role-dispatch", "role": "quality-gate-engineer",
            "satisfiedBy": {"roleRun": "quality-gate-engineer", "acceptStatuses": ["completed", "skipped"]},
            "outputs": [{"artifact": "report", "paths": ["docs/report.md"]}],
        }
        ledger = {
            "roleRuns": [{"roleId": "quality-gate-engineer", "status": "skipped", "reasonForSkip": "objective-conditions-met"}],
            "qualityGates": [{"verdict": "PASS"}, {"verdict": "BLOCK"}],
        }
        role_ctx = next_step._guard_context(skill_root, role_node, ledger)
        self.assertEqual(role_ctx["verdict"], "BLOCK")
        satisfied, unmet = next_step._node_satisfied(skill_root, {}, role_node, ledger)
        self.assertFalse(satisfied)
        self.assertTrue(any("objectiveConditionsRef" in item for item in unmet))
        ledger["roleRuns"][0]["objectiveConditionsRef"] = "condition 1"
        self.assertTrue(next_step._node_satisfied(skill_root, {}, role_node, ledger)[0])
        self.assertEqual(next_step._node_applicable(skill_root, {"when": "always"}, None), (True, "always"))
        self.assertFalse(next_step._node_applicable(skill_root, {"when": "input-contract-mode"}, None)[0])
        self.assertTrue(next_step._node_applicable(skill_root, {"when": "conditional", "role": "x"}, None)[0])
        self.assertTrue(next_step._node_applicable(skill_root, {"when": "future"}, None)[0])
        self.assertEqual(next_step._occurrences(None, role_node), 0)
        self.assertIsNone(next_step.record_pointer(skill_root, {}))

        process = {
            "entry": "A", "nodes": [
                {"nodeId": "A", "type": "gate", "transitions": [{"to": "B"}, {"to": "SP-HALT"}, {"to": "REWORK"}]},
                {"nodeId": "B", "type": "role-dispatch", "transitions": [{"to": "C"}]},
                {"nodeId": "C", "type": "gate", "transitions": [{"to": "B"}]},
            ],
        }
        self.assertEqual({n["nodeId"] for n in next_step._traversal_order(process)}, {"A", "B", "C"})
        self.assertEqual(next_step._successors(process["nodes"][0]), ["B"])

        with tempfile.TemporaryDirectory() as raw:
            out_root = Path(raw)
            stdout, stderr = io.StringIO(), io.StringIO()
            commands = [
                ["--skill-root", str(skill_root), "--check"],
                ["--skill-root", str(skill_root), "--mermaid"],
                ["--skill-root", str(skill_root), "--mermaid-out", str(out_root / "flow.md")],
                ["--skill-root", str(skill_root), "--graph"],
                ["--skill-root", str(skill_root), "--graph-out", str(out_root / "graph.json")],
                ["--skill-root", str(skill_root), "--impact", "backend-engineer"],
                ["--skill-root", str(skill_root), "--impact", "not-found"],
                ["--skill-root", str(skill_root), "--project-root", str(out_root)],
                ["--skill-root", str(out_root / "missing")],
                ["--skill-root", str(skill_root), "--project-root", str(out_root / "missing")],
            ]
            with redirect_stdout(stdout), redirect_stderr(stderr):
                codes = [next_step.main(command) for command in commands]
            self.assertEqual(codes[:6], [0] * 6)
            self.assertEqual(codes[6:], [1, 0, 3, 3])
            self.assertTrue((out_root / "flow.md").is_file())
            self.assertTrue((out_root / "graph.json").is_file())

    def test_traceability_public_api_and_cli_cover_pass_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            requirements = root / "requirements.json"
            requirements.write_text(json.dumps({"knownIds": ["FR-001"], "requiredIds": ["FR-001"]}), encoding="utf-8")
            _known, _required, requirements_hash = load_requirement_catalog(requirements)
            snap = snapshot()
            bridge = trace()
            bridge["requirementsHash"] = requirements_hash
            passed = validate_traceability(requirements, snap, bridge)
            self.assertEqual(passed.verdict, "PASS")
            stale = clone(bridge)
            stale["manifestHash"] = "sha256:" + "0" * 64
            stale["rejected"] = [{"reasonCode": "UNKNOWN_REQUIREMENT_ID", "declaration": {"line": 1}}]
            stale["links"][0]["symbolRef"]["symbolId"] = "sha256:" + "9" * 64
            failed = validate_traceability(requirements, snap, stale)
            self.assertEqual(failed.verdict, "BLOCK")
            self.assertIn("TRACE_BRIDGE_STALE", {row["code"] for row in failed.findings})

            snapshot_path = root / "snapshot.json"
            bridge_path = root / "bridge.json"
            snapshot_path.write_text(json.dumps(snap), encoding="utf-8")
            bridge_path.write_text(json.dumps(bridge), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(traceability_main(["--requirements", str(requirements), "--snapshot", str(snapshot_path), "--trace-bridge", str(bridge_path), "--json"]), 0)
                self.assertEqual(traceability_main(["--requirements", str(requirements), "--snapshot", str(root / "missing.json"), "--trace-bridge", str(bridge_path)]), 1)

    def test_delivery_validator_exercises_schema_content_and_cli_fail_closed(self) -> None:
        skill_root = Path(__file__).parents[2]
        actual_blockers = delivery.validate_content_gates(skill_root, skill_root)
        # The repository under test may itself be at any delivery phase; the
        # fail-closed assertions below use an isolated fixture instead of
        # coupling this unit test to the workspace's current blocker list.
        self.assertIsInstance(actual_blockers, list)
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            docs = project / "docs"
            docs.mkdir()
            (docs / "单元测试报告.md").write_text("单元测试覆盖率：91%\n", encoding="utf-8")
            (docs / "集成测试报告.md").write_text("集成测试覆盖率：81%\n", encoding="utf-8")
            (docs / "E2E测试报告.md").write_text("E2E测试通过率：100%\nE2E测试总数：1\ntrace screenshot stdout\n", encoding="utf-8")
            (docs / "E2E测试用例.md").write_text("case\n", encoding="utf-8")
            plan = {
                "taskSummary": "delivery", "createdAt": "2026-08-29T00:00:00Z", "deliveryId": "delivery-1",
                "route": ["backend-engineer"], "handoffs": [{"roleId": "backend-engineer", "expectedOutputs": []}], "requiredDocuments": [],
            }
            ledger = initial_ledger(plan)
            (docs / "evidence-ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            blockers = delivery.validate_content_gates(project, skill_root)
            self.assertIsInstance(blockers, list)
            result = delivery.validate_delivery(skill_root, project, False, True)
            self.assertEqual(result["status"], "fail")
            self.assertTrue(result["blockingReasons"])
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(delivery.main(["--skill-root", str(skill_root), "--project-root", str(project), "--no-strict"]), 2)
                self.assertEqual(delivery.main(["--skill-root", str(skill_root), "--project-root", str(project), "--json"]), 1)

            self.assertEqual(delivery.check_file(project, "docs/单元测试报告.md")[0], True)
            self.assertEqual(delivery.check_file(project, "docs/missing.md")[0], False)
            self.assertEqual(delivery._scan_unit_coverage("单元测试覆盖率：90.5%"), 90.5)
            self.assertEqual(delivery._scan_integration_coverage("集成测试覆盖率：80%"), 80.0)
            self.assertEqual(delivery._scan_e2e_pass_rate("E2E测试通过率：100%"), 100.0)
            self.assertEqual(delivery._scan_e2e_total("E2E测试总数：1"), 1)
            self.assertEqual(
                delivery._scan_e2e_evidence("trace: trace.zip\nscreenshot: shot.png\nstdout: run.log"),
                [],
            )
            for helper in (
                delivery._check_coverage_artifacts, delivery._check_db_migration_alignment,
                delivery._check_agent_timing_format, delivery._check_completeness_markers,
                delivery._reconcile_changeset_with_disk, delivery._check_enhancement_declarations,
                delivery._check_phases_consistency, delivery._check_parallel_conditions,
                delivery._check_epic_completeness, delivery._check_input_contract_gate,
                delivery._check_owl_traceability,
            ):
                self.assertIsInstance(helper(project), list)
            self.assertIsInstance(delivery._check_process_node_coverage(project, skill_root), list)
            for reason in (
                "deliveryStatus missing", "coverage-artifact missing", "temporal consistency", "database-migration",
                "build fail", "agent-timing", "end-of-doc", "fallbackTrigger", "enhancement-declaration",
                "phase-consistency", "parallel-condition", "unknown reason",
            ):
                self.assertTrue(delivery._suggest_fix(reason))

    def test_delivery_gate_self_execution_exemption_is_narrow(self) -> None:
        report = {
            "state": "actionable",
            "currentNode": "SP-18",
            "nodeType": "gate",
            "progress": {"pending": 1},
            "unmet": ["证据账本中没有包含 'validate_delivery' 的命令记录"],
            "downstreamPending": [],
            "blockedBy": [],
        }
        self.assertTrue(delivery._is_self_executing_delivery_gate(report))

        for key, value in (
            ("currentNode", "SP-17"),
            ("nodeType", "role-dispatch"),
            ("progress", {"pending": 2}),
            ("unmet", ["validate_delivery command missing", "another unmet condition"]),
            ("downstreamPending", ["SP-19"]),
            ("blockedBy", ["SP-17"]),
        ):
            altered = dict(report)
            altered[key] = value
            self.assertFalse(delivery._is_self_executing_delivery_gate(altered), key)

    def test_delivery_policy_reports_rich_tampering_and_cross_artifact_drift(self) -> None:
        skill_root = Path(__file__).parents[2]
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            docs = project / "docs"
            docs.mkdir()
            bad_docs = {
                "代码评审.md": "verdict: BLOCK\n有条件通过\n<!-- END-OF-DOC -->",
                "安全评审.md": "BUILD FAILURE\nverdict: BLOCK\n",
                "单元测试报告.md": "BUILD FAILURE\n单元测试实现：0个\n单元测试覆盖率：10%\nTODO",
                "集成测试报告.md": "BUILD FAILURE\n集成测试覆盖率：20%",
                "E2E测试用例.md": "case",
                "E2E测试报告.md": "BUILD FAILURE\nverdict: BLOCK\n有条件通过\nE2E测试通过率：50%\nE2E测试总数：0",
                "监督审计.md": "有条件通过",
                "需求规格书.md": "${UNFILLED}",
                "执行日志.md": "ran",
                "数据设计说明书.md": "| users | table |\n| orders | table |",
            }
            for name, content in bad_docs.items():
                (docs / name).write_text(content, encoding="utf-8")
            ledger = {
                "taskName": "tamper", "createdAt": "2099-01-01T00:00:00Z",
                "deliveryStatus": "halted-user-cancel",
                "deliveryGateEvidence": {"strictMode": False, "status": "fail"},
                "observability": {"reworkCount": 12, "reworkPerRootCause": {"qa": 7}},
                "roleRuns": [
                    {"roleId": "browser-e2e-engineer", "status": "skipped", "reasonForSkip": "invented"},
                    {"roleId": "backend-engineer", "status": "skipped", "reasonForSkip": "objective-conditions-met"},
                    {"roleId": "backend-engineer", "status": "completed", "retryCount": 1,
                     "expectedOutputs": ["src/**"], "changeSet": {"created": ["missing.py", 3], "modified": [], "deleted": ["kept.py"]}},
                    {"roleId": "frontend-engineer", "status": "completed", "sessionMode": "single-session-fallback",
                     "changeSet": {"created": [], "modified": [], "deleted": []}},
                ],
                "enhancementDeclarations": {
                    "totalCount": 2, "unfulfilledCount": 2, "waivedCount": 0,
                    "declarations": [{"target": "backend-engineer"}],
                },
                "phases": [
                    {"phaseId": "p1", "status": "completed", "rollbackScope": ["x"]},
                    {"phaseId": "p2", "receivedFrom": "wrong"},
                ],
                "epics": [
                    {"epicId": "E1", "specFile": "docs/missing-epic.md", "dependsOnEpics": ["E2"]},
                    {"epicId": "E2", "dependsOnEpics": ["E1"]},
                ],
                "eventLog": [
                    {"roleId": "frontend-engineer", "eventType": "role-start", "timestamp": "2026-01-01T00:00:00Z"},
                    {"roleId": "frontend-engineer", "eventType": "role-complete", "timestamp": "2026-01-01T01:00:00Z"},
                    {"roleId": "backend-engineer", "eventType": "role-start", "timestamp": "2026-01-01T00:15:00Z"},
                    {"roleId": "backend-engineer", "eventType": "role-complete", "timestamp": "2026-01-01T00:45:00Z"},
                ],
            }
            (project / "kept.py").write_text("kept", encoding="utf-8")
            (docs / "evidence-ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            blockers = delivery.validate_content_gates(project, skill_root)
            joined = "\n".join(blockers)
            for token in (
                "verdict = BLOCK", "BUILD FAILURE", "coverage 10.0%", "E2E pass-rate 50.0%",
                "placeholder content", "halted-user-cancel", "strictMode=false", "reworkCount",
                "reasonForSkip", "mandatory role", "fallbackTrigger", "expectedOutput",
                "changeSet-drift", "enhancement-declaration", "phase-consistency",
                "parallel-condition", "epic-completeness", "database-migration", "agent-timing",
            ):
                self.assertIn(token, joined)

            # Temporal, migration, timing and completeness success/failure variants.
            for index in range(3):
                path = docs / f"old-{index}.md"
                path.write_text("old", encoding="utf-8")
                os.utime(path, (1, 1))
            self.assertTrue(delivery._check_ledger_temporal_consistency(project, ledger))
            self.assertEqual(delivery._check_ledger_temporal_consistency(project, {}), [])
            self.assertEqual(delivery._check_ledger_temporal_consistency(project, {"createdAt": "bad"}), [])

            migrations = project / "migrations"
            migrations.mkdir()
            self.assertEqual(delivery._check_db_migration_alignment(project), [])
            (migrations / "001.sql").write_text("create table unrelated(id int);", encoding="utf-8")
            self.assertTrue(delivery._check_db_migration_alignment(project))
            (docs / "agent-timing.md").write_text("no table", encoding="utf-8")
            self.assertTrue(delivery._check_agent_timing_format(project))
            (docs / "agent-timing.md").write_text("| role | start |\n|---|---|\n| one | never |", encoding="utf-8")
            self.assertGreaterEqual(len(delivery._check_agent_timing_format(project)), 1)

            self.assertTrue(delivery._reconcile_changeset_with_disk(project))
            self.assertTrue(delivery._check_enhancement_declarations(project))
            self.assertTrue(delivery._check_phases_consistency(project))
            self.assertTrue(delivery._check_parallel_conditions(project))
            self.assertTrue(delivery._check_epic_completeness(project))

    def test_delivery_helper_matrix_covers_absent_clean_and_malformed_states(self) -> None:
        skill_root = Path(__file__).parents[2]
        for scanner in (
            delivery._scan_unit_coverage, delivery._scan_integration_coverage,
            delivery._scan_e2e_pass_rate, delivery._scan_e2e_total,
        ):
            self.assertIsNone(scanner("no machine-readable metric"))
        self.assertTrue(delivery._scan_block_verdict("结论：不通过"))
        self.assertTrue(delivery._scan_build_failure("build failed"))
        self.assertTrue(delivery._scan_zero_test_impl("覆盖率：0%"))
        self.assertTrue(delivery._scan_conditional_pass("原则性通过"))
        self.assertGreaterEqual(len(delivery._scan_e2e_evidence("plain prose")), 2)
        with self.assertRaisesRegex(ValueError, "nodes"):
            delivery.derive_role_policy({"nodes": {}})
        with self.assertRaisesRegex(ValueError, "declare role"):
            delivery.derive_role_policy({"nodes": [{"type": "role-dispatch"}]})

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docs = root / "docs"
            docs.mkdir()
            (docs / "01-alias.md").write_text("content", encoding="utf-8")
            (docs / "02-empty.md").write_text("", encoding="utf-8")
            self.assertEqual(delivery.check_file(root, "docs/alias.md"), (True, "present"))
            self.assertEqual(delivery.check_file(root, "docs/empty.md"), (False, "empty"))
            self.assertIsNone(delivery._resolve_doc_alias(root, "src/not-doc.txt"))
            self.assertIsNone(delivery._resolve_doc_alias(root, "docs/missing.md"))
            self.assertEqual(delivery._read_text(root, "docs/alias.md"), "content")
            self.assertIsNone(delivery._read_text(root, "docs/missing.md"))

            self.assertEqual(delivery._check_coverage_artifacts(root), [
                "coverage-artifact: unit/integration test report claims passing coverage but no real coverage artifact found on disk (checked: jacoco/lcov/htmlcov/.coverage/coverage.xml). Run tests with coverage enabled and verify output files exist before declaring coverage numbers."
            ])
            (root / "coverage.xml").write_text("<coverage/>", encoding="utf-8")
            self.assertEqual(delivery._check_coverage_artifacts(root), [])
            self.assertEqual(delivery._check_ledger_temporal_consistency(root, {"createdAt": "2026-01-01T00:00:00Z"}), [])

            # Data design branches: no tables, matching migration, and no migration content.
            (docs / "05-数据设计说明书.md").write_text("prose only", encoding="utf-8")
            migrations = root / "migrations"
            migrations.mkdir()
            self.assertEqual(delivery._check_db_migration_alignment(root), [])
            (docs / "05-数据设计说明书.md").write_text("| users | table |", encoding="utf-8")
            self.assertEqual(delivery._check_db_migration_alignment(root), [])
            (migrations / "001.sql").write_text("create table users(id int);", encoding="utf-8")
            self.assertEqual(delivery._check_db_migration_alignment(root), [])

            (docs / "agent-timing.md").write_text(
                "| role | start |\n|---|---|\n| a | 2026-01-01T00:00 |\n| b | 2026-01-01T01:00 |",
                encoding="utf-8",
            )
            self.assertEqual(delivery._check_agent_timing_format(root), [])
            for name in ("需求规格书.md", "详细设计说明书.md"):
                (docs / name).write_text("complete\n<!-- END-OF-DOC -->", encoding="utf-8")
            self.assertEqual(delivery._check_completeness_markers(root), [])

            # Empty ledgers make every optional cross-artifact check a clean no-op.
            (docs / "evidence-ledger.json").write_text(json.dumps({"roleRuns": []}), encoding="utf-8")
            for helper in (
                delivery._reconcile_changeset_with_disk, delivery._check_enhancement_declarations,
                delivery._check_phases_consistency, delivery._check_parallel_conditions,
                delivery._check_epic_completeness,
            ):
                self.assertEqual(helper(root), [])

            ontology = root / "docs" / "input" / "models" / "ontology"
            ontology.mkdir(parents=True)
            (ontology / "domain.owl").write_text("owl", encoding="utf-8")
            self.assertEqual(delivery._check_owl_traceability(root), [])
            domain = root / "docs" / "input" / "02-domain.md"
            domain.write_text("ENT-USER", encoding="utf-8")
            self.assertTrue(delivery._check_owl_traceability(root))
            (docs / "05-数据设计说明书.md").write_text("table ENT-USER", encoding="utf-8")
            self.assertEqual(delivery._check_owl_traceability(root), [])

            malformed_skill = root / "malformed-skill"
            (malformed_skill / "schemas").mkdir(parents=True)
            (malformed_skill / "schemas" / "evidence-ledger.schema.json").write_text("{broken", encoding="utf-8")
            self.assertTrue(delivery._validate_evidence_ledger_schema(malformed_skill, {}))

    def test_content_gate_clean_and_missing_metric_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docs = root / "docs"
            docs.mkdir()
            clean_docs = {
                "代码评审.md": "verdict: PASS\n<!-- END-OF-DOC -->",
                "安全评审.md": "verdict: PASS\n<!-- END-OF-DOC -->",
                "单元测试报告.md": "单元测试覆盖率：93.7%\n<!-- END-OF-DOC -->",
                "集成测试报告.md": "集成测试覆盖率：84.0%\n<!-- END-OF-DOC -->",
                "E2E测试用例.md": "P0 case\n<!-- END-OF-DOC -->",
                "E2E测试报告.md": "verdict: PASS\nE2E测试通过率：100%\nE2E测试总数：1\ntrace: run.zip\nscreenshot: shot.png\nstdout: run.log\n<!-- END-OF-DOC -->",
                "监督审计.md": "python scripts/validate_delivery.py\nstatus: pass\n<!-- END-OF-DOC -->",
            }
            for name, content in clean_docs.items():
                (docs / name).write_text(content, encoding="utf-8")
            (root / "coverage.xml").write_text("<coverage/>", encoding="utf-8")
            ledger = {
                "deliveryStatus": "completed",
                "deliveryGateEvidence": {"status": "pass", "blockingReasons": [], "runAt": "2026-08-29T00:00:00Z", "strictMode": True},
                "observability": {"reworkCount": 0, "reworkPerRootCause": {}},
                "roleRuns": [
                    None,
                    {"roleId": "", "status": "planned"},
                    {"roleId": "browser-e2e-engineer", "status": "completed", "changeSet": {"modified": [], "created": [], "deleted": []}},
                    {"roleId": "optional", "status": "skipped", "reasonForSkip": "user-approved"},
                    {"roleId": "fallback", "status": "completed", "sessionMode": "single-session-fallback", "changeSet": {"modified": [], "created": [], "deleted": []}},
                ],
                "fallbackTrigger": {"fallbackReason": "tool unavailable", "fallbackApprover": "user", "fallbackTimestamp": "2026-08-29T00:00:00Z"},
            }
            (docs / "evidence-ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            blockers = delivery.validate_content_gates(root, None)
            joined = "\n".join(blockers)
            self.assertNotIn("unit-test coverage", joined)
            self.assertNotIn("integration-test coverage", joined)
            self.assertNotIn("E2E pass-rate", joined)
            self.assertNotIn("mandatory role 'browser-e2e-engineer'", joined)
            self.assertNotIn("fallbackTrigger is missing", joined)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docs = root / "docs"
            docs.mkdir()
            (docs / "单元测试报告.md").write_text("report without metric", encoding="utf-8")
            (docs / "集成测试报告.md").write_text("report without metric", encoding="utf-8")
            (docs / "E2E测试用例.md").write_text("case", encoding="utf-8")
            (docs / "E2E测试报告.md").write_text("plain prose", encoding="utf-8")
            joined = "\n".join(delivery.validate_content_gates(root, None))
            self.assertIn("coverage field is missing", joined)
            self.assertIn("pass-rate field is missing", joined)
            self.assertIn("case-total field is missing", joined)
            self.assertIn("ledger file not found", joined)

    def test_delivery_orchestrator_aggregates_fail_warn_pass_and_optional_absence(self) -> None:
        def module(name: str, **members):
            value = types.ModuleType(name)
            for key, member in members.items():
                setattr(value, key, member)
            return value

        def status_module(name: str, function_name: str, result: dict):
            return module(name, **{function_name: lambda *_args, **_kwargs: dict(result)})

        memory = module(
            "memory_store",
            load_failure_patterns=lambda _root: {},
            save_failure_patterns=lambda _root, _value: None,
            ingest_failure=lambda value, *_args, **_kwargs: value,
        )
        skill_root = Path(__file__).parents[2]
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            docs = project / "docs"
            docs.mkdir()
            (docs / "orchestration-plan.json").write_text(json.dumps({"deliveryId": "d1", "stackDetection": {"selectedAdapters": ["python"]}}), encoding="utf-8")

            base_patches = (
                patch.object(delivery, "load_config", return_value={"artifacts": {"requiredDocuments": ["docs/required.md"]}}),
                patch.object(delivery, "_read_evidence_ledger", return_value={}),
                patch.object(delivery, "validate_content_gates", return_value=[]),
            )
            fail_modules = {
                "validate_code_intelligence": status_module("validate_code_intelligence", "validate_phase", {"status": "fail", "applicability": "code", "blockingReasons": ["C01"], "unknownReasons": ["U01"]}),
                "validate_doc_structure": status_module("validate_doc_structure", "validate_doc_structure", {"status": "fail", "blockingReasons": ["shape"]}),
                "preflight_env_check": status_module("preflight_env_check", "preflight_env_check", {"status": "not-ready", "blocking": ["python missing"]}),
                "contract_drift_check": status_module("contract_drift_check", "check_contract_drift", {"status": "fail", "blockingReasons": ["contract"]}),
                "requirement_drift_check": status_module("requirement_drift_check", "check_requirement_drift", {"status": "fail", "blockingReasons": ["requirement"]}),
                "trace_requirements": status_module("trace_requirements", "trace_requirements", {"status": "fail", "sourceReqCount": 2, "gaps": [{"id": "FR-1"}]}),
                "memory_store": memory,
            }
            with base_patches[0], base_patches[1], base_patches[2], patch.object(delivery, "check_file", return_value=(False, "missing")), patch.dict(sys.modules, fail_modules):
                failed = delivery.validate_delivery(skill_root, project, True, True)
            self.assertEqual(failed["status"], "fail")
            self.assertEqual(next(row for row in failed["checks"] if row["name"] == "PRD Sync Gate")["status"], "fail")

            warn_modules = {
                "validate_code_intelligence": status_module("validate_code_intelligence", "validate_phase", {"status": "pass", "applicability": "code"}),
                "validate_doc_structure": status_module("validate_doc_structure", "validate_doc_structure", {"status": "pass"}),
                "preflight_env_check": status_module("preflight_env_check", "preflight_env_check", {"status": "ready"}),
                "contract_drift_check": status_module("contract_drift_check", "check_contract_drift", {"status": "warn", "coveragePct": 70}),
                "requirement_drift_check": status_module("requirement_drift_check", "check_requirement_drift", {"status": "warn", "reason": "partial"}),
                "trace_requirements": status_module("trace_requirements", "trace_requirements", {"status": "warn", "gaps": [{}]}),
                "memory_store": memory,
            }
            with base_patches[0], base_patches[1], base_patches[2], patch.object(delivery, "check_file", return_value=(True, "present")), patch.dict(sys.modules, warn_modules):
                warned = delivery.validate_delivery(skill_root, project, False, False, strict_mode=False)
            self.assertEqual(warned["status"], "pass")
            self.assertEqual(next(row for row in warned["checks"] if row["name"] == "PRD Sync Gate")["status"], "warn")

            pass_modules = {
                "validate_code_intelligence": status_module("validate_code_intelligence", "validate_phase", {"status": "pass", "applicability": "docs-only"}),
                "validate_doc_structure": status_module("validate_doc_structure", "validate_doc_structure", {"status": "pass"}),
                "preflight_env_check": status_module("preflight_env_check", "preflight_env_check", {"status": "ready"}),
                "contract_drift_check": status_module("contract_drift_check", "check_contract_drift", {"status": "pass"}),
                "requirement_drift_check": status_module("requirement_drift_check", "check_requirement_drift", {"status": "pass"}),
                "trace_requirements": status_module("trace_requirements", "trace_requirements", {"status": "pass", "gaps": []}),
                "memory_store": memory,
            }
            with base_patches[0], base_patches[1], base_patches[2], patch.object(delivery, "check_file", return_value=(True, "present")), patch.dict(sys.modules, pass_modules):
                passed = delivery.validate_delivery(skill_root, project, True, False, strict_mode=False)
            self.assertEqual(passed["status"], "pass")
            self.assertEqual(next(row for row in passed["checks"] if row["name"] == "PRD Sync Gate")["status"], "pass")

            optional_absent = dict(pass_modules)
            optional_absent.update({name: None for name in ("validate_doc_structure", "preflight_env_check", "contract_drift_check", "requirement_drift_check", "trace_requirements", "memory_store")})
            with base_patches[0], base_patches[1], base_patches[2], patch.object(delivery, "check_file", return_value=(True, "present")), patch.dict(sys.modules, optional_absent):
                skipped = delivery.validate_delivery(skill_root, project, False, False, strict_mode=False)
            self.assertEqual(skipped["status"], "pass")
            self.assertEqual(next(row for row in skipped["checks"] if row["name"] == "PRD Sync Gate")["status"], "not-run")

        suggestions = {
            "input-contract traceability broken": "上游追溯链",
            "input-contract gate failed": "validate_input_contract.py",
            "E2E missing": "Browser E2E Engineer",
            "E2E evidence insufficient": "real tests",
            "verdict = BLOCK": "Re-dispatch",
            "有条件通过": "PASS or BLOCK",
            "placeholder content": "placeholder",
            "evidence-ledger missing": "write_evidence_ledger.py",
            "deliveryStatus halted": "halted",
            "rework cap": "cap exceeded",
            "validate_delivery 监督审计": "paste the exact",
        }
        for reason, expected in suggestions.items():
            with self.subTest(reason=reason):
                self.assertIn(expected, delivery._suggest_fix(reason))


if __name__ == "__main__":
    unittest.main()
