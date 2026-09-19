"""Validate exact requirement-symbol-test coverage from a TraceBridge."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    from .code_intelligence_models import load_json_object
    from .materialize_trace_links import load_requirement_catalog
except ImportError:
    from code_intelligence_models import load_json_object
    from materialize_trace_links import load_requirement_catalog


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    verdict: str
    findings: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {"gateId": self.gate_id, "verdict": self.verdict, "findings": list(self.findings)}


def validate_traceability(requirements_file: Path, snapshot: Mapping[str, object], trace_bridge: Mapping[str, object]) -> GateResult:
    # @trace FR-004 AC-004
    _known, required, requirements_hash = load_requirement_catalog(requirements_file)
    findings: list[dict[str, object]] = []
    if trace_bridge.get("manifestHash") != snapshot.get("manifestHash") or trace_bridge.get("sourceDigest") != snapshot.get("sourceDigest") or trace_bridge.get("requirementsHash") != requirements_hash:
        findings.append({"code": "TRACE_BRIDGE_STALE", "subjects": [], "remediation": "Re-materialize the trace bridge from the current snapshot and requirements baseline."})
    rejected = trace_bridge.get("rejected", [])
    if isinstance(rejected, list):
        for item in rejected:
            if isinstance(item, Mapping):
                findings.append({"code": str(item.get("reasonCode", "TRACE_SCHEMA_INVALID")), "subjects": [item.get("declaration", {})], "remediation": "Fix the explicit declaration and re-materialize the bridge."})
    implementation: dict[str, int] = {identifier: 0 for identifier in required}
    tests: dict[str, set[str]] = {identifier: set() for identifier in required}
    links = trace_bridge.get("links", [])
    snapshot_ids = {str(symbol.get("symbolId")) for symbol in snapshot.get("symbols", []) if isinstance(symbol, Mapping)} if isinstance(snapshot.get("symbols"), list) else set()
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, Mapping) or link.get("status") != "exact":
                continue
            symbol = link.get("symbolRef", {})
            if not isinstance(symbol, Mapping) or str(symbol.get("symbolId")) not in snapshot_ids:
                findings.append({"code": "SYMBOL_NOT_FOUND", "subjects": [link.get("traceLinkId")], "remediation": "Re-materialize the bridge from the current snapshot."})
                continue
            for identifier in link.get("requirementIds", []) if isinstance(link.get("requirementIds"), list) else []:
                if identifier not in required:
                    continue
                if link.get("role") == "implementation":
                    implementation[identifier] += 1
                elif link.get("role") == "test" and link.get("testId"):
                    tests[identifier].add(str(link["testId"]))
    missing_impl = sorted(identifier for identifier, count in implementation.items() if count == 0)
    missing_tests = sorted(identifier for identifier, values in tests.items() if not values)
    if missing_impl:
        findings.append({"code": "MISSING_IMPLEMENTATION_LINK", "subjects": missing_impl, "remediation": "Add an exact @trace declaration to a unique implementation symbol."})
    if missing_tests:
        findings.append({"code": "MISSING_TEST_LINK", "subjects": missing_tests, "remediation": "Add an exact @trace and unique @test-id declaration to an executed test symbol."})
    return GateResult("C-CODE-04", "PASS" if not findings else "BLOCK", tuple(findings))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--trace-bridge", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = validate_traceability(Path(args.requirements), load_json_object(Path(args.snapshot)), load_json_object(Path(args.trace_bridge)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {"gateId": "C-CODE-04", "verdict": "BLOCK", "findings": [{"code": "TRACE_SCHEMA_INVALID", "subjects": [], "remediation": type(exc).__name__}]}
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
