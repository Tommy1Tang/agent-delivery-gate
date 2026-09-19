"""Run the public code-intelligence CLI bootstrap and normal-delivery E2E chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence


class E2EFailure(RuntimeError):
    """A public CLI command or its machine-readable assertion failed."""


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise E2EFailure(f"expected JSON object: {path.name}")
    return value


def _write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(root: Path, path: Path, **extra: object) -> dict[str, object]:
    payload = _load(path)
    result: dict[str, object] = {
        "path": path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix(),
        "sha256": _sha256(path),
        "contentHash": payload.get("contentHash"),
    }
    result.update(extra)
    return result


def _runtime(project_root: Path) -> tuple[Path, dict[str, object]]:
    runtime_path = project_root / ".tmp" / "code-intelligence-runtime.json"
    formal_path = project_root / "assets" / "config" / "code-intelligence.json"
    config = _load(runtime_path if runtime_path.is_file() else formal_path)
    provider = config.get("provider")
    if not isinstance(provider, dict):
        raise E2EFailure("provider config is missing")
    executable = str(provider.get("executable", "cgr"))
    resolved = Path(executable) if Path(executable).is_absolute() else Path(shutil.which(executable) or executable)
    if not resolved.is_file():
        raise E2EFailure(f"provider executable is unavailable: {executable}")
    python_name = "python.exe" if os.name == "nt" else "python"
    runtime_python = resolved.parent / python_name
    if not runtime_python.is_file():
        runtime_python = Path(sys.executable)
    return runtime_python.resolve(strict=True), config


def _run_json(
    cases: list[dict[str, object]],
    case_id: str,
    command: Sequence[str],
    predicate: Callable[[Mapping[str, object]], bool],
    *,
    timeout: int = 600,
) -> dict[str, object]:
    started = time.monotonic()
    result = subprocess.run(
        list(command), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False, shell=False, env={**os.environ, "PYTHONUTF8": "1"},
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        cases.append({"caseId": case_id, "status": "FAIL", "exitCode": result.returncode, "durationMs": duration_ms, "evidence": ["stdout was not one JSON object", result.stderr[-500:]]})
        raise E2EFailure(f"{case_id}: non-JSON output") from exc
    passed = result.returncode == 0 and isinstance(payload, dict) and predicate(payload)
    cases.append({
        "caseId": case_id,
        "status": "PASS" if passed else "FAIL",
        "exitCode": result.returncode,
        "durationMs": duration_ms,
        "evidence": [json.dumps(payload, ensure_ascii=False, sort_keys=True)[:1000]],
    })
    if not passed:
        raise E2EFailure(f"{case_id}: public CLI assertion failed")
    return payload


def _script(project_root: Path, name: str) -> str:
    path = (project_root / "scripts" / name).resolve(strict=True)
    path.relative_to(project_root.resolve(strict=True))
    return str(path)


def _normal_code_evidence(
    repository_id: str,
    delivery_id: str,
    before_manifest: dict[str, object],
    before_trace: dict[str, object],
    impact: dict[str, object],
    *,
    after_manifest: dict[str, object] | None = None,
    after_trace: dict[str, object] | None = None,
    index_diff: dict[str, object] | None = None,
) -> dict[str, object]:
    gate_ids = ["C-CODE-01", "C-CODE-02", "C-CODE-03", "C-CODE-05"]
    if after_manifest and after_trace and index_diff:
        gate_ids = [f"C-CODE-0{index}" for index in range(1, 8)]
    code: dict[str, object] = {
        "schemaVersion": "1.0.0",
        "applicability": "applicable",
        "applicabilityEvidence": {"detectedPaths": ["e2e_app.py"], "eligibleFileCount": 2, "changedCodeFileCount": 1, "reason": "E2E normal delivery"},
        "provider": {"name": "code-graph-rag", "version": "0.0.779", "manifestVersion": 1, "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"},
        "startingProcessVersion": "1.1.0",
        "activatedVersion": "1.1.0",
        "repositoryId": repository_id,
        "deliveryId": delivery_id,
        "beforeManifest": before_manifest,
        "beforeTraceBridge": before_trace,
        "preChangeImpactReports": [impact],
        "gateResults": [{"gateId": gate, "verdict": "PASS", "code": "OK", "commandRef": "code_intelligence_e2e.py", "exitCode": 0} for gate in gate_ids],
    }
    if after_manifest and after_trace and index_diff:
        code.update({"afterManifest": after_manifest, "afterTraceBridge": after_trace, "indexDiff": index_diff})
    return code


def run_e2e(project_root: Path, fixture: Path) -> dict[str, object]:
    root = project_root.resolve(strict=True)
    fixture_root = fixture.resolve(strict=True)
    fixture_root.relative_to(root)
    if any(path.is_symlink() for path in fixture_root.rglob("*")):
        raise E2EFailure("symlinked fixture content is forbidden")
    runtime_python, base_config = _runtime(root)
    cases: list[dict[str, object]] = []
    started = time.monotonic()

    try:
        bootstrap_dir = root / "_test_output" / "code-intelligence" / "bootstrap-final-evidence"
        bootstrap_command = [
            str(runtime_python), "-X", "utf8", _script(root, "bootstrap_code_intelligence.py"), "--json", "validate",
            "--inventory", str(bootstrap_dir / "bootstrap-inventory.json"),
            "--baseline-statement", str(bootstrap_dir / "bootstrap-baseline-statement.json"),
            "--activation", str(bootstrap_dir / "bootstrap-activation.json"),
            "--consumed-marker", str(bootstrap_dir / "bootstrap-consumed-marker.json"),
        ]
        _run_json(cases, "E2E-BOOTSTRAP-BUNDLE", bootstrap_command, lambda row: row.get("status") == "pass")
        _run_json(
            cases, "E2E-BOOTSTRAP-DELIVERY-GATE",
            [str(runtime_python), "-X", "utf8", _script(root, "validate_code_intelligence.py"), "--phase", "delivery", "--project-root", str(root), "--ledger", str(root / "docs" / "evidence-ledger.json"), "--config", str(root / "assets" / "config" / "code-intelligence.json"), "--json"],
            lambda row: row.get("status") == "pass" and row.get("mode") == "bootstrap",
        )

        with tempfile.TemporaryDirectory(prefix="code-intelligence-e2e-") as raw:
            workspace = Path(raw) / "repository"
            shutil.copytree(fixture_root, workspace)
            artifacts = workspace / "_e2e_artifacts"
            artifacts.mkdir()
            config = json.loads(json.dumps(base_config))
            excluded = config.setdefault("excludeDirectories", [])
            if not isinstance(excluded, list):
                raise E2EFailure("excludeDirectories must be an array")
            if "_e2e_artifacts" not in excluded:
                excluded.append("_e2e_artifacts")
            config["outputRoot"] = "_e2e_artifacts"
            config_path = workspace / "code-intelligence.json"
            _write(config_path, config)
            requirements = workspace / "requirements.json"
            repository_id = "code-intelligence-e2e-fixture"
            delivery_id = "normal-delivery-after-bootstrap"

            def cli(name: str, *arguments: str) -> list[str]:
                return [str(runtime_python), "-X", "utf8", _script(root, name), *arguments]

            before_dir = artifacts / "before"
            _run_json(cases, "E2E-NORMAL-BEFORE-INDEX", cli("build_code_index.py", "--project-root", str(workspace), "--output-dir", str(before_dir), "--config", str(config_path), "--repository-id", repository_id, "--json"), lambda row: row.get("status") == "SUCCESS")
            before_snapshot_path = before_dir / "normalized" / "code-index-snapshot.json"
            before_manifest_path = before_dir / "normalized" / "code-index-manifest.json"
            before_trace_path = before_dir / "normalized" / "code-trace-bridge.json"
            _run_json(cases, "E2E-NORMAL-BEFORE-TRACE", cli("materialize_trace_links.py", "--project-root", str(workspace), "--snapshot", str(before_snapshot_path), "--requirements", str(requirements), "--output", str(before_trace_path), "--json"), lambda row: row.get("status") == "SUCCESS" and row.get("rejectedCount") == 0)
            _run_json(cases, "E2E-NL-QUERY", cli("query_code_graph.py", "--snapshot", str(before_snapshot_path), "--trace-bridge", str(before_trace_path), "--question", "FR-001 由什么实现?", "--json"), lambda row: row.get("queryStatus") == "ANSWERED" and bool(row.get("symbols")))
            impact_path = artifacts / "impact.json"
            impact_payload = _run_json(cases, "E2E-NORMAL-IMPACT", cli("analyze_code_impact.py", "--snapshot", str(before_snapshot_path), "--trace-bridge", str(before_trace_path), "--file", "e2e_app.py", "--artifact-root", str(artifacts), "--output", "impact.json", "--json"), lambda row: row.get("verdict") == "FOUND")

            before_manifest_ref = _reference(workspace, before_manifest_path)
            before_trace_ref = _reference(workspace, before_trace_path)
            impact_ref = _reference(workspace, impact_path, verdict=impact_payload["verdict"])
            pre_ledger = workspace / "pre-change-ledger.json"
            _write(pre_ledger, {"deliveryId": delivery_id, "changeSet": {"files": ["e2e_app.py"]}, "codeIntelligence": _normal_code_evidence(repository_id, delivery_id, before_manifest_ref, before_trace_ref, impact_ref)})
            _run_json(cases, "E2E-NORMAL-PRECHANGE-GATE", cli("validate_code_intelligence.py", "--phase", "pre-change", "--project-root", str(workspace), "--ledger", str(pre_ledger), "--config", str(config_path), "--json"), lambda row: row.get("status") == "pass" and row.get("mode") == "normal")

            source = workspace / "e2e_app.py"
            original = source.read_text(encoding="utf-8")
            changed = original.replace("E2E_REVISION = 1", "E2E_REVISION = 2")
            if changed == original:
                raise E2EFailure("fixture mutation marker is missing")
            source.write_text(changed, encoding="utf-8")

            after_dir = artifacts / "after"
            _run_json(cases, "E2E-NORMAL-AFTER-INDEX", cli("build_code_index.py", "--project-root", str(workspace), "--output-dir", str(after_dir), "--config", str(config_path), "--repository-id", repository_id, "--json"), lambda row: row.get("status") == "SUCCESS")
            after_snapshot_path = after_dir / "normalized" / "code-index-snapshot.json"
            after_manifest_path = after_dir / "normalized" / "code-index-manifest.json"
            after_trace_path = after_dir / "normalized" / "code-trace-bridge.json"
            _run_json(cases, "E2E-NORMAL-AFTER-TRACE", cli("materialize_trace_links.py", "--project-root", str(workspace), "--snapshot", str(after_snapshot_path), "--requirements", str(requirements), "--output", str(after_trace_path), "--json"), lambda row: row.get("status") == "SUCCESS" and row.get("rejectedCount") == 0)
            change_set_path = artifacts / "change-set.json"
            _write(change_set_path, {"files": ["e2e_app.py"]})
            diff_path = artifacts / "diff.json"
            _run_json(cases, "E2E-NORMAL-RECONCILE", cli("reconcile_code_changes.py", "--before-snapshot", str(before_snapshot_path), "--after-snapshot", str(after_snapshot_path), "--before-trace", str(before_trace_path), "--after-trace", str(after_trace_path), "--impact-report", str(impact_path), "--change-set", str(change_set_path), "--artifact-root", str(artifacts), "--output", "diff.json", "--json"), lambda row: row.get("gateVerdict") == "PASS")

            delivery_ledger = workspace / "delivery-ledger.json"
            delivery_code = _normal_code_evidence(
                repository_id, delivery_id, before_manifest_ref, before_trace_ref, impact_ref,
                after_manifest=_reference(workspace, after_manifest_path),
                after_trace=_reference(workspace, after_trace_path),
                index_diff=_reference(workspace, diff_path),
            )
            _write(delivery_ledger, {"deliveryId": delivery_id, "changeSet": {"files": ["e2e_app.py"]}, "codeIntelligence": delivery_code})
            _run_json(cases, "E2E-NORMAL-DELIVERY-GATE", cli("validate_code_intelligence.py", "--phase", "delivery", "--project-root", str(workspace), "--ledger", str(delivery_ledger), "--config", str(config_path), "--json"), lambda row: row.get("status") == "pass" and row.get("mode") == "normal")
    except (E2EFailure, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"schemaVersion": "1.0.0", "status": "FAIL", "passed": sum(row["status"] == "PASS" for row in cases), "total": len(cases), "passRate": 0.0 if not cases else round(100 * sum(row["status"] == "PASS" for row in cases) / len(cases), 1), "cases": cases, "diagnostics": [type(exc).__name__, str(exc)], "durationMs": int((time.monotonic() - started) * 1000)}
    passed = sum(row["status"] == "PASS" for row in cases)
    return {"schemaVersion": "1.0.0", "status": "PASS", "passed": passed, "total": len(cases), "passRate": round(100 * passed / len(cases), 1), "cases": cases, "diagnostics": [], "durationMs": int((time.monotonic() - started) * 1000)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_e2e(Path(args.project_root), Path(args.fixture))
    except (E2EFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"schemaVersion": "1.0.0", "status": "FAIL", "passed": 0, "total": 0, "passRate": 0.0, "cases": [], "diagnostics": [type(exc).__name__, str(exc)], "durationMs": 0}
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
