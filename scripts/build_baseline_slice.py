#!/usr/bin/env python3
"""Baseline slice selector for software-development-team.

Given a capability id (CAP-*), compute exactly which baseline-package files a
development slice must receive -- WITHOUT letting the AI guess. The selection is
pure set arithmetic over the traceability fields already declared in
docs/input/01-能力目录.md (capability_id -> process_id / entity_id / rule_id /
state_id / question_id), per references/development-baseline-contract.md §6.

LAW-3 (declared-not-inferred): slice membership is derived from declared IDs,
never from filename heuristics. LAW-10: models are read-only references.

Fixed global inputs (every slice):
    00-项目概述.md, 01-能力目录.md, models/spec/model-spec.json,
    models/baseline-manifest.json

Slice-specific inputs (driven by the capability's linked IDs):
    related BPMN (by process_id), related OWL (by entity_id), 02/03/04/05,
    07 questions touching the capability, related graph query results.

Usage:
    python scripts/build_baseline_slice.py --project-root <proj> --capability CAP-XXX
    python scripts/build_baseline_slice.py --project-root <proj> --capability CAP-XXX --json

Exit codes: 0 = slice resolved, 1 = capability not found, 3 = usage / no input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FIXED_GLOBAL = [
    "00-项目概述.md",
    "01-能力目录.md",
    "models/spec/model-spec.json",
    "models/baseline-manifest.json",
]

ID_RE = re.compile(r"\b(CAP|PROC|ND|ENT|RULE|ST|IF|Q)-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


def _discover(input_dir: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for key in ("00", "01", "02", "03", "04", "05", "06", "07"):
        matches = sorted(input_dir.glob(f"{key}-*.md"))
        if matches:
            found[key] = matches[0]
    return found


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _capability_row(text: str, capability: str) -> dict[str, list[str]] | None:
    """Find the 01 table row for `capability` and bucket its IDs by prefix.

    Column-agnostic: we bucket every id token found in the row by its prefix,
    so the selector does not depend on exact column ordering -- only on the
    fact that the row belongs to the requested capability.
    """
    headers: list[str] | None = None
    for raw in text.splitlines():
        if not raw.strip().startswith("|"):
            headers = None
            continue
        cells = _split_row(raw)
        if set("".join(cells)) <= set("-: "):
            continue  # separator row
        if headers is None:
            headers = cells
            continue
        if capability not in cells:
            continue
        # This is the capability's row. Bucket IDs by prefix.
        buckets: dict[str, list[str]] = {}
        for m in ID_RE.finditer(raw):
            tok = m.group(0)
            prefix = m.group(1)
            if tok == capability:
                continue
            buckets.setdefault(prefix, [])
            if tok not in buckets[prefix]:
                buckets[prefix].append(tok)
        return buckets
    return None


def _bpmn_for_processes(models: Path, process_ids: list[str]) -> list[str]:
    """BPMN files whose declared node/process ids intersect the slice."""
    out: list[str] = []
    bpmn_dir = models / "bpmn"
    if not bpmn_dir.is_dir() or not process_ids:
        return out
    wanted = set(process_ids)
    for bp in sorted(bpmn_dir.glob("*.bpmn")):
        try:
            text = bp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        ids = set(re.findall(r'id="([^"]+)"', text))
        if ids & wanted:
            out.append(bp.relative_to(models.parent).as_posix())
    return out


def _owl_for_entities(models: Path, entity_ids: list[str]) -> list[str]:
    """OWL files whose class local-names intersect the slice entities."""
    out: list[str] = []
    owl_dir = models / "ontology"
    if not owl_dir.is_dir() or not entity_ids:
        return out
    wanted = set(entity_ids)
    for of in sorted(owl_dir.glob("*.owl")):
        try:
            text = of.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        locals_ = {v.split("#")[-1].rsplit("/", 1)[-1]
                   for v in re.findall(r'(?:about|ID)="([^"]+)"', text)}
        if locals_ & wanted:
            out.append(of.relative_to(models.parent).as_posix())
    return out


def build_slice(project_root: Path, input_rel: str, capability: str) -> dict:
    input_dir = project_root / input_rel
    if not input_dir.is_dir():
        return {"tool": "build_baseline_slice", "capability": capability,
                "found": False, "error": f"{input_rel} 不存在"}

    files = _discover(input_dir)
    if "01" not in files:
        return {"tool": "build_baseline_slice", "capability": capability,
                "found": False, "error": "01-能力目录.md 缺失，无法解析能力关联"}

    text = files["01"].read_text(encoding="utf-8", errors="ignore")
    buckets = _capability_row(text, capability)
    if buckets is None:
        all_caps = sorted(set(re.findall(r"\bCAP-[A-Za-z0-9-]+", text)))
        return {"tool": "build_baseline_slice", "capability": capability,
                "found": False, "error": f"{capability} 未在 01-能力目录.md 中定义",
                "knownCapabilities": all_caps}

    models = input_dir / "models"
    process_ids = buckets.get("PROC", [])
    entity_ids = buckets.get("ENT", [])

    # Owner markdown files relevant to this slice, only if the capability links
    # to that dimension (LAW-3: presence is declared, not assumed).
    slice_md: list[str] = []
    if entity_ids:
        slice_md += [files[k].name for k in ("02",) if k in files]
    if buckets.get("ST"):
        slice_md += [files[k].name for k in ("03",) if k in files]
    if buckets.get("RULE"):
        slice_md += [files[k].name for k in ("04",) if k in files]
    if process_ids:
        slice_md += [files[k].name for k in ("05",) if k in files]
    if buckets.get("Q") and "07" in files:
        slice_md.append(files["07"].name)

    return {
        "tool": "build_baseline_slice",
        "capability": capability,
        "found": True,
        "linkedIds": {k: v for k, v in sorted(buckets.items())},
        "fixedGlobalInputs": FIXED_GLOBAL,
        "sliceInputs": {
            "ownerDocs": slice_md,
            "bpmn": _bpmn_for_processes(models, process_ids),
            "owl": _owl_for_entities(models, entity_ids),
            "graphQueries": ["models/graph/sparql-results.json"]
            if (models / "graph" / "sparql-results.json").is_file() else [],
        },
        "note": "切片内容由 01-能力目录.md 的追溯字段机械推导（LAW-3）；"
                "模型只读（LAW-10）；固定全局输入每个切片都必须提供。",
    }


def _print_human(report: dict) -> None:
    if not report.get("found"):
        print(f"[SLICE] {report['capability']}: 未解析 —— {report.get('error')}")
        if report.get("knownCapabilities"):
            print(f"        已知能力: {', '.join(report['knownCapabilities'])}")
        return
    print(f"[SLICE] {report['capability']}")
    linked = report["linkedIds"]
    print("       关联 ID: " + (", ".join(f"{k}×{len(v)}" for k, v in linked.items()) or "无"))
    print("       固定全局输入:")
    for f in report["fixedGlobalInputs"]:
        print(f"         - {f}")
    si = report["sliceInputs"]
    print("       切片相关输入:")
    for label, key in (("owner 文档", "ownerDocs"), ("BPMN", "bpmn"),
                       ("OWL", "owl"), ("图查询", "graphQueries")):
        vals = si.get(key) or []
        if vals:
            print(f"         - {label}: {', '.join(vals)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute the baseline-package slice for a capability.")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--input-dir", default="docs/input",
                        help="Input directory relative to project root")
    parser.add_argument("--capability", required=True, help="Capability id, e.g. CAP-TASK-CREATE")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(f"error: project root not found: {project_root}", file=sys.stderr)
        return 3

    report = build_slice(project_root, args.input_dir.replace("\\", "/"), args.capability)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0 if report.get("found") else 1


if __name__ == "__main__":
    raise SystemExit(main())
