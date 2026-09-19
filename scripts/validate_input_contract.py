#!/usr/bin/env python3
"""Mechanical validation of the upstream PRD input contract (`docs/input/`).

Turns the "输入完整性门禁" of references/prd-input-contract.md from a prompt-level
instruction into a machine-checkable exit code. The two things an LLM cannot do
reliably by eye are exactly what this script does mechanically:

1. Cross-reference every ID citation (SC/ROLE/PROC/ND/ENT/REL/ST/R/IF/EX/EV/Q/CAP)
   against its owning definition file -> broken traceability links.
2. Per-capability Must-level completeness (business goal, trigger role, input,
   output, happy path, >=1 error path, Given/When/Then acceptance, out-of-scope).

Usage:
    python scripts/validate_input_contract.py --project-root <dir>
    python scripts/validate_input_contract.py --project-root <dir> --json
    python scripts/validate_input_contract.py --project-root <dir> \
        --gap-list-out docs/输入缺口清单.md

Exit codes: 0 = pass, 1 = partial, 2 = fail, 3 = usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# --------------------------------------------------------------------------
# Contract constants
# --------------------------------------------------------------------------

# Owner file (by numeric prefix) -> {exact header cell: ID prefix it defines}.
# Definition detection is file-scoped AND requires an EXACT header match, so
# reference columns such as "关联 rule_id" or "触发节点 node_id" are never
# mistaken for definitions.
OWNER_SPEC: dict[str, dict[str, str]] = {
    "00": {"scenario_id": "SC", "role_id": "ROLE"},
    "01": {"capability_id": "CAP"},
    "02": {"entity_id": "ENT", "relation_id": "REL"},
    "03": {"state_id": "ST"},
    "04": {"rule_id": "RULE"},
    "05": {"process_id": "PROC", "node_id": "ND",
           "exception_id": "EX", "interface_id": "IF"},
    "06": {"evidence_id": "EV"},
    "07": {"question_id": "Q"},
}

# Which file owns each prefix (inverse of OWNER_SPEC), for error messages.
PREFIX_OWNER: dict[str, str] = {
    prefix: file_key
    for file_key, spec in OWNER_SPEC.items()
    for prefix in spec.values()
}

ALWAYS_REQUIRED = ["00", "01", "02"]
RECOMMENDED = ["05"]
# Referencing an ID whose owner file is optional and absent is advisory only.
OPTIONAL_OWNERS = {"06", "07"}

# The prefix set is deliberately PREFIX-FREE: no prefix is a prefix of another
# (RULE / ROLE / REL all differ at the 2nd character). That makes matching
# order-independent and immune to the classic `R-` vs `ROLE-` collision, and it
# also means internal PRD numbering (FR-/BR-/NFR-/AC-) can never be captured.
ID_PATTERN = re.compile(
    r"\b(CAP|ENT|EV|EX|IF|ND|PROC|REL|ROLE|RULE|SC|ST|Q)-([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)"
)

# Guard: assert at import time that the prefix set stays prefix-free, so a future
# edit that reintroduces an ambiguous prefix fails loudly instead of silently.
_PREFIXES = ("CAP", "ENT", "EV", "EX", "IF", "ND", "PROC", "REL", "ROLE", "RULE", "SC", "ST", "Q")
_AMBIGUOUS = [(a, b) for a in _PREFIXES for b in _PREFIXES if a != b and b.startswith(a)]
if _AMBIGUOUS:  # pragma: no cover - configuration error, not runtime state
    raise AssertionError(f"ID prefixes must be prefix-free, found collisions: {_AMBIGUOUS}")

# Literal strings shipped in the templates. Their presence means "not filled in".
TEMPLATE_LITERALS = [
    "异常条件 1", "异常条件 2", "处理方式",
    "一句话说明", "谁触发这个能力", "触发时需要的数据",
    "能力执行后产生的结果", "涉及哪些领域对象", "从哪些流程节点抽象而来",
    "同上格式", "每个 capability 复制以下模板填写",
]

CAP_REQUIRED_FIELDS = ["业务目标", "触发角色", "输入", "输出"]


# --------------------------------------------------------------------------
# Text / table helpers
# --------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _strip_fences(text: str) -> str:
    """Blank out fenced code blocks while preserving line numbering."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def _norm_cell(cell: str) -> str:
    return cell.replace("`", "").replace("**", "").strip()


def _is_sep_row(line: str) -> bool:
    body = line.strip().strip("|")
    return bool(body) and "-" in body and set(body) <= set("-: |")


def _split_row(line: str) -> list[str]:
    return [_norm_cell(c) for c in line.strip().strip("|").split("|")]


def _parse_tables(text: str) -> list[dict]:
    """Parse GitHub-flavoured markdown tables into header/row dicts."""
    tables: list[dict] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and _is_sep_row(lines[i + 1]):
            headers = _split_row(line)
            rows: list[dict] = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                if not _is_sep_row(lines[j]):
                    cells = _split_row(lines[j])
                    row: dict = {"_line": j + 1}
                    for k, head in enumerate(headers):
                        row[head] = cells[k] if k < len(cells) else ""
                    rows.append(row)
                j += 1
            tables.append({"headers": headers, "rows": rows})
            i = j
        else:
            i += 1
    return tables


def _find_header(headers: list[str], key: str) -> str | None:
    """Fuzzy header lookup, used for reading VALUES (not definitions)."""
    for h in headers:
        if key in h:
            return h
    return None


def _is_placeholder(token: str) -> bool:
    return "xxx" in token.lower()


def _has_content(value: str) -> bool:
    """True when a cell/field carries real content rather than a placeholder."""
    if not value:
        return False
    cleaned = re.sub(r"（[^）]*）", "", value)
    cleaned = re.sub(r"\([^)]*\)", "", cleaned).strip()
    if not cleaned or cleaned in {"-", "—", "/", "待补充", "TBD", "TODO"}:
        return False
    if _is_placeholder(cleaned):
        return False
    return not any(lit in cleaned for lit in TEMPLATE_LITERALS)


# --------------------------------------------------------------------------
# Baseline package checks (C-INPUT-01..04)
#
# LAW-9: upstream BPMN/OWL are business-layer models and must NOT be downgraded
# into markdown. LAW-10: they are read-only SEMANTIC references, never gate
# verdicts -- so we only do SET COMPARISON here (stdlib ElementTree), never
# semantic reasoning, and SHACL/reasoning violations become warnings only.
# --------------------------------------------------------------------------

MODELS_DIR = "models"
MANIFEST_REL = "models/baseline-manifest.json"
SPEC_REL = "models/spec/model-spec.json"

# BPMN flow elements whose ids should mirror 05 的 ND-* nodes.
_BPMN_NODE_TAGS = {
    "task", "userTask", "serviceTask", "scriptTask", "manualTask",
    "businessRuleTask", "sendTask", "receiveTask", "callActivity",
    "subProcess", "exclusiveGateway", "inclusiveGateway", "parallelGateway",
    "eventBasedGateway", "complexGateway",
}


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _bpmn_node_ids(path: Path) -> set[str]:
    """Collect ids of BPMN flow nodes. Set comparison only -- no semantics."""
    ids: set[str] = set()
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return ids
    for el in root.iter():
        if _localname(el.tag) in _BPMN_NODE_TAGS:
            nid = el.get("id")
            if nid:
                ids.add(nid)
    return ids


def _owl_class_ids(path: Path) -> set[str]:
    """Collect OWL class local names from rdf:about / rdf:ID."""
    ids: set[str] = set()
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return ids
    rdf_ns = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
    for el in root.iter():
        if _localname(el.tag) not in ("Class", "NamedIndividual"):
            continue
        for attr in (f"{rdf_ns}about", f"{rdf_ns}ID", "about", "ID"):
            val = el.get(attr)
            if val:
                ids.add(val.split("#")[-1].rstrip("/").rsplit("/", 1)[-1])
                break
    return ids


def _check_baseline(input_dir: Path, defs: dict[str, set[str]],
                    files: dict[str, Path]) -> tuple[list[str], list[str], dict]:
    """Return (blocking, warnings, summary) for the baseline package."""
    blocking: list[str] = []
    warnings: list[str] = []
    models = input_dir / MODELS_DIR
    summary: dict = {"present": models.is_dir()}
    if not models.is_dir():
        return blocking, warnings, summary

    # ---- C-INPUT-01: manifest content hashes -----------------------------
    manifest_path = input_dir / MANIFEST_REL
    if not manifest_path.is_file():
        blocking.append(
            f"C-INPUT-01: {MODELS_DIR}/ 存在但 {MANIFEST_REL} 缺失，"
            "无法确认各文件属于同一基线")
        return blocking, warnings, summary
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        blocking.append(f"C-INPUT-01: {MANIFEST_REL} 不是合法 JSON ({exc})")
        return blocking, warnings, summary

    summary["baselineId"] = manifest.get("baselineId")
    listed: set[str] = set()
    for entry in manifest.get("files", []):
        rel = entry.get("path")
        expected = entry.get("sha256")
        if not rel or not expected:
            blocking.append(f"C-INPUT-01: manifest 条目缺少 path 或 sha256: {entry}")
            continue
        listed.add(rel.replace("\\", "/"))
        target = input_dir / rel
        if not target.is_file():
            blocking.append(f"C-INPUT-01: manifest 声明的文件不存在：{rel}")
            continue
        actual = _sha256(target)
        if actual != expected:
            blocking.append(
                f"C-INPUT-01: {rel} 内容哈希不匹配（manifest={expected[:12]}…, "
                f"实际={actual[:12]}…）——文件被独立修改，基线不自洽")
    summary["filesListed"] = len(listed)

    # Untracked model files: the package must be complete, not partially pinned.
    for path in sorted(models.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(input_dir).as_posix()
        if rel == MANIFEST_REL:  # manifest never lists itself
            continue
        if rel not in listed:
            blocking.append(f"C-INPUT-01: {rel} 未被 manifest 收录，无法校验版本")

    # ---- C-INPUT-02: 05 ND-* set == BPMN flow-node id set ----------------
    bpmn_files = sorted((models / "bpmn").glob("*.bpmn")) if (models / "bpmn").is_dir() else []
    summary["bpmnFiles"] = len(bpmn_files)
    if bpmn_files:
        bpmn_ids: set[str] = set()
        for bp in bpmn_files:
            bpmn_ids |= _bpmn_node_ids(bp)
        nd_ids = {i for i in defs.get("ND", set())}
        summary["bpmnNodeIds"] = len(bpmn_ids)
        if "05" not in files:
            warnings.append("C-INPUT-02: 提供了 BPMN 但 05-*.md 缺失，无法校验流程投影一致性")
        else:
            only_md = sorted(nd_ids - bpmn_ids)
            only_bpmn = sorted(i for i in bpmn_ids - nd_ids if i.startswith("ND-"))
            for i in only_md[:10]:
                blocking.append(
                    f"C-INPUT-02: {i} 定义于 05-*.md 但 BPMN 中无对应节点（流程投影漂移）")
            for i in only_bpmn[:10]:
                blocking.append(
                    f"C-INPUT-02: BPMN 节点 {i} 未在 05-*.md 中定义（流程投影漂移）")

    # ---- C-INPUT-03: 02 ENT-* subset of OWL classes ----------------------
    owl_files = sorted((models / "ontology").glob("*.owl")) if (models / "ontology").is_dir() else []
    summary["owlFiles"] = len(owl_files)
    if owl_files:
        owl_ids: set[str] = set()
        for of in owl_files:
            owl_ids |= _owl_class_ids(of)
        summary["owlClassIds"] = len(owl_ids)
        if "02" not in files:
            warnings.append("C-INPUT-03: 提供了 OWL 但 02-*.md 缺失，无法校验领域投影一致性")
        else:
            missing = sorted(defs.get("ENT", set()) - owl_ids)
            for i in missing[:10]:
                blocking.append(
                    f"C-INPUT-03: {i} 定义于 02-*.md 但 OWL 中无对应类（领域投影漂移）")

    # ---- C-INPUT-04: model-spec.json is the authoritative spec source ----
    spec_path = input_dir / SPEC_REL
    if not spec_path.is_file():
        blocking.append(f"C-INPUT-04: {SPEC_REL} 缺失，基线包无规范源")
    else:
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            blocking.append(f"C-INPUT-04: {SPEC_REL} 不是合法 JSON ({exc})")
            spec = None
        if spec is not None:
            for spec_key, prefix, owner in (
                ("capabilities", "CAP", "01"),
                ("processes", "PROC", "05"),
                ("entities", "ENT", "02"),
            ):
                raw_items = spec.get(spec_key)
                if raw_items is None:
                    continue
                spec_ids = {
                    (it.get("id") if isinstance(it, dict) else it)
                    for it in raw_items
                }
                spec_ids = {s for s in spec_ids if isinstance(s, str)}
                md_ids = defs.get(prefix, set())
                if owner not in files:
                    warnings.append(
                        f"C-INPUT-04: model-spec.json 声明了 {spec_key} 但 {owner}-*.md 缺失")
                    continue
                for i in sorted(spec_ids - md_ids)[:10]:
                    blocking.append(
                        f"C-INPUT-04: {i} 在 model-spec.json 的 {spec_key} 中声明，"
                        f"但未定义于 {owner}-*.md（规范源与投影不一致）")
                for i in sorted(md_ids - spec_ids)[:10]:
                    blocking.append(
                        f"C-INPUT-04: {i} 定义于 {owner}-*.md 但未在 model-spec.json "
                        f"的 {spec_key} 中声明（规范源与投影不一致）")

    # ---- SHACL / reasoning reports: WARNINGS ONLY (LAW-10) ---------------
    graph_dir = models / "graph"
    if graph_dir.is_dir():
        for name, label in (("graph-validation-report.json", "SHACL 校验"),
                            ("reasoning-report.json", "推理校验")):
            rp = graph_dir / name
            if not rp.is_file():
                continue
            try:
                data = json.loads(rp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                warnings.append(f"{label}报告 {name} 无法解析，已忽略")
                continue
            violations = data.get("violations") or data.get("results") or []
            if isinstance(violations, list) and violations:
                warnings.append(
                    f"{label}报告含 {len(violations)} 条 violation（仅提示，"
                    "不参与 verdict 判定：LAW-10 推理结论不得当门禁判据）")

    return blocking, warnings, summary


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def _discover(input_dir: Path) -> dict[str, Path]:
    """Map numeric prefix -> actual file, tolerating renamed suffixes."""
    found: dict[str, Path] = {}
    if not input_dir.is_dir():
        return found
    for key in OWNER_SPEC:
        matches = sorted(input_dir.glob(f"{key}-*.md"))
        if matches:
            found[key] = matches[0]
    return found


def _collect_definitions(files: dict[str, Path], raw: dict[str, str]) -> dict[str, set[str]]:
    defs: dict[str, set[str]] = {p: set() for p in PREFIX_OWNER}
    for key, spec in OWNER_SPEC.items():
        if key not in files:
            continue
        for table in _parse_tables(_strip_fences(raw[key])):
            for header in table["headers"]:
                prefix = spec.get(header)  # exact match only
                if not prefix:
                    continue
                for row in table["rows"]:
                    value = row.get(header, "")
                    for token in value.replace("、", ",").replace("/", ",").split(","):
                        token = token.strip()
                        if token and not _is_placeholder(token) and ID_PATTERN.fullmatch(token):
                            defs[prefix].add(token)
    # Capability headings (### CAP-xxx) also count as definitions.
    if "01" in files:
        for m in re.finditer(r"^###\s+(CAP-[A-Za-z0-9-]+)", raw["01"], re.M):
            if not _is_placeholder(m.group(1)):
                defs["CAP"].add(m.group(1))
    return defs


def _collect_references(files: dict[str, Path], raw: dict[str, str]) -> dict[str, dict[str, set[str]]]:
    refs: dict[str, dict[str, set[str]]] = {p: {} for p in PREFIX_OWNER}
    for key, path in files.items():
        for lineno, line in enumerate(_strip_fences(raw[key]).splitlines(), start=1):
            for m in ID_PATTERN.finditer(line):
                token = m.group(0)
                if _is_placeholder(token):
                    continue
                prefix = m.group(1)
                refs[prefix].setdefault(token, set()).add(f"{path.name}:{lineno}")
    return refs


# --------------------------------------------------------------------------
# Per-file Must-level checks
# --------------------------------------------------------------------------

def _section_bodies(text: str, prefix: str) -> dict[str, str]:
    """Split '### <PREFIX>-xxx' detail sections into id -> body."""
    bodies: dict[str, str] = {}
    matches = list(re.finditer(rf"^###\s+({prefix}-[A-Za-z0-9-]+)", text, re.M))
    for idx, m in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        bodies[m.group(1)] = text[m.end():end]
    return bodies


def _bullet_field(body: str, label: str) -> str | None:
    m = re.search(rf"^\s*[-*]\s*\*\*{re.escape(label)}\*\*\s*[：:]\s*(.*)$", body, re.M)
    return m.group(1) if m else None


def _block_after(body: str, marker: str) -> str:
    """Text between **marker** and the next **bold** marker / heading."""
    m = re.search(rf"\*\*{re.escape(marker)}\*\*\s*[：:]?", body)
    if not m:
        return ""
    rest = body[m.end():]
    stop = re.search(r"^\s*(?:\*\*[^*]+\*\*|#{2,6}\s|---\s*$)", rest, re.M)
    return rest[:stop.start()] if stop else rest


def _filled_list_items(block: str, numbered: bool) -> int:
    pattern = r"^\s*\d+\.\s*(.+)$" if numbered else r"^\s*[-*]\s*(.+)$"
    return sum(1 for m in re.finditer(pattern, block, re.M) if _has_content(m.group(1)))


def _check_capabilities(raw01: str) -> tuple[dict, list[str], list[str]]:
    """Return (summary, must_gaps, warnings)."""
    gaps: list[str] = []
    warnings: list[str] = []
    overview_rows: list[dict] = []
    headers: list[str] = []

    for table in _parse_tables(_strip_fences(raw01)):
        if "capability_id" in table["headers"]:
            headers = table["headers"]
            overview_rows = [r for r in table["rows"]
                             if _has_content(r.get("capability_id", ""))]
            break

    summary = {"total": 0, "must": 0, "mustComplete": 0, "mustIncomplete": []}
    if not overview_rows:
        gaps.append("01-能力目录: 能力总览表缺失或无有效 capability_id 行")
        return summary, gaps, warnings

    pri_h = _find_header(headers, "优先级")
    node_h = _find_header(headers, "node_id")
    type_h = _find_header(headers, "类型")
    bodies = _section_bodies(raw01, "CAP")
    summary["total"] = len(overview_rows)

    for row in overview_rows:
        cap = row["capability_id"]
        priority = row.get(pri_h, "") if pri_h else ""
        if not any(k in priority for k in ("Must", "Should", "Could")):
            gaps.append(f"01-能力目录: {cap} 缺 MoSCoW 优先级（当前值 '{priority}'）")

        node_val = row.get(node_h, "") if node_h else ""
        type_val = row.get(type_h, "") if type_h else ""
        is_global = ("全局" in node_val or "横切" in node_val or "横切" in type_val)
        if not is_global and not _has_content(node_val):
            gaps.append(f"01-能力目录: {cap} 未关联 node_id，也未标注为全局/横切能力")

        if "Must" not in priority:
            continue
        summary["must"] += 1

        body = bodies.get(cap)
        if body is None:
            gaps.append(f"01-能力目录: {cap} 为 Must 级但缺少 '### {cap}' 详细描述段")
            summary["mustIncomplete"].append(cap)
            continue

        missing: list[str] = []
        for label in CAP_REQUIRED_FIELDS:
            val = _bullet_field(body, label)
            if val is None or not _has_content(val):
                missing.append(label)

        if _filled_list_items(_block_after(body, "正常流程"), numbered=True) < 2:
            missing.append("正常流程(>=2 步)")
        if _filled_list_items(_block_after(body, "异常流程"), numbered=False) < 1:
            missing.append("异常流程(>=1 条)")
        if _filled_list_items(_block_after(body, "不包含"), numbered=False) < 1:
            missing.append("不包含范围")

        acc = _block_after(body, "验收标准")
        gherkin_ok = all(
            any(_has_content(m.group(1))
                for m in re.finditer(rf"^\s*{kw}\b(.*)$", acc, re.M))
            for kw in ("Given", "When", "Then")
        )
        if not gherkin_ok:
            missing.append("验收标准(Given/When/Then 需有实际内容)")

        if missing:
            gaps.append(f"01-能力目录: Must 能力 {cap} 不完整 -> 缺 {', '.join(missing)}")
            summary["mustIncomplete"].append(cap)
        else:
            summary["mustComplete"] += 1

    if summary["must"] == 0:
        warnings.append("01-能力目录: 没有任何 Must 级能力，请确认优先级分级是否遗漏")
    return summary, gaps, warnings


def _check_entities(raw02: str) -> list[str]:
    gaps: list[str] = []
    tables = _parse_tables(_strip_fences(raw02))
    ent_rows: list[dict] = []
    ent_headers: list[str] = []
    rel_rows: list[dict] = []
    rel_headers: list[str] = []
    for t in tables:
        if "entity_id" in t["headers"] and not ent_rows:
            ent_headers, ent_rows = t["headers"], [
                r for r in t["rows"] if _has_content(r.get("entity_id", ""))]
        if "relation_id" in t["headers"] and not rel_rows:
            rel_headers, rel_rows = t["headers"], [
                r for r in t["rows"] if _has_content(r.get("relation_id", ""))]

    if not ent_rows:
        gaps.append("02-领域模型: 实体清单缺失或无有效 entity_id 行")
        return gaps

    uid_h = _find_header(ent_headers, "唯一标识")
    attr_bodies = _section_bodies(raw02, "ENT")
    for row in ent_rows:
        ent = row["entity_id"]
        if uid_h and not _has_content(row.get(uid_h, "")):
            gaps.append(f"02-领域模型: {ent} 未声明唯一标识")
        body = attr_bodies.get(ent)
        if body is None:
            gaps.append(f"02-领域模型: {ent} 缺少字段属性表（'### {ent}' 段）")
            continue
        field_table = next(
            (t for t in _parse_tables(body)
             if _find_header(t["headers"], "字段") and _find_header(t["headers"], "类型")),
            None,
        )
        if field_table is None:
            gaps.append(f"02-领域模型: {ent} 属性表缺少 字段/类型 列")
        elif not _find_header(field_table["headers"], "必填"):
            gaps.append(f"02-领域模型: {ent} 属性表缺少 必填 列")

    card_h = _find_header(rel_headers, "基数") if rel_headers else None
    for row in rel_rows:
        if card_h and not _has_content(row.get(card_h, "")):
            gaps.append(f"02-领域模型: 关系 {row['relation_id']} 未声明基数")
    return gaps


def _check_states(raw03: str) -> list[str]:
    gaps: list[str] = []
    table = next((t for t in _parse_tables(_strip_fences(raw03))
                  if "state_id" in t["headers"]), None)
    if table is None:
        gaps.append("03-状态机: 状态转换表缺失或缺少 state_id 列")
        return gaps
    from_h = _find_header(table["headers"], "当前状态")
    to_h = _find_header(table["headers"], "目标状态")
    ev_h = _find_header(table["headers"], "触发事件")
    node_h = _find_header(table["headers"], "触发节点")
    role_h = _find_header(table["headers"], "触发角色")
    rows = [r for r in table["rows"] if _has_content(r.get("state_id", ""))]
    if not rows:
        gaps.append("03-状态机: 状态转换表无有效 state_id 行")
    for row in rows:
        sid = row["state_id"]
        for label, h in (("当前状态", from_h), ("目标状态", to_h), ("触发事件", ev_h)):
            if not h or not _has_content(row.get(h, "")):
                gaps.append(f"03-状态机: {sid} 缺 {label}")
        by_node = node_h and _has_content(row.get(node_h, ""))
        by_role = role_h and _has_content(row.get(role_h, ""))
        if not (by_node or by_role):
            gaps.append(f"03-状态机: {sid} 缺触发节点或触发角色（至少需其一）")
    return gaps


def _check_rules(raw04: str) -> list[str]:
    gaps: list[str] = []
    table = next((t for t in _parse_tables(_strip_fences(raw04))
                  if "rule_id" in t["headers"]), None)
    if table is None:
        gaps.append("04-业务规则: 规则总览表缺失或缺少 rule_id 列")
        return gaps
    type_h = _find_header(table["headers"], "类型")
    bodies = _section_bodies(raw04, "RULE")
    rows = [r for r in table["rows"] if _has_content(r.get("rule_id", ""))]
    if not rows:
        gaps.append("04-业务规则: 规则总览表无有效 rule_id 行")
    for row in rows:
        rid = row["rule_id"]
        if type_h and not _has_content(row.get(type_h, "")):
            gaps.append(f"04-业务规则: {rid} 缺规则类型")
        body = bodies.get(rid)
        if body is None:
            gaps.append(f"04-业务规则: {rid} 缺少详细描述段（'### {rid}'）")
            continue
        for marker in ("输入条件", "输出结果"):
            block = _block_after(body, marker)
            tables = _parse_tables(block)
            filled = any(
                any(_has_content(v) for k, v in r.items() if k != "_line")
                for t in tables for r in t["rows"]
            )
            if not filled:
                gaps.append(f"04-业务规则: {rid} 的「{marker}」为空")
    return gaps


def _check_scope(raw00: str) -> list[str]:
    m = re.search(r"^#{2,4}\s*.*不包含.*$", raw00, re.M)
    if not m:
        return ["00-项目概述: 缺少「本期不包含」范围外声明章节"]
    rest = raw00[m.end():]
    stop = re.search(r"^#{2,4}\s", rest, re.M)
    block = rest[:stop.start()] if stop else rest
    if _filled_list_items(block, numbered=False) < 1:
        return ["00-项目概述: 「本期不包含」章节为空，范围外事项必须显式声明"]
    return []


def _check_questions(raw07: str) -> list[str]:
    gaps: list[str] = []
    table = next((t for t in _parse_tables(_strip_fences(raw07))
                  if "question_id" in t["headers"]), None)
    if table is None:
        return gaps
    block_h = _find_header(table["headers"], "阻塞程度")
    assume_h = _find_header(table["headers"], "当前假设")
    mock_h = _find_header(table["headers"], "策略")
    if not block_h:
        return gaps
    for row in table["rows"]:
        qid = row.get("question_id", "")
        if not _has_content(qid) or "高" not in row.get(block_h, ""):
            continue
        if not assume_h or not _has_content(row.get(assume_h, "")):
            gaps.append(f"07-待确认问题: 高阻塞问题 {qid} 未标注当前假设")
        if not mock_h or not _has_content(row.get(mock_h, "")):
            gaps.append(f"07-待确认问题: 高阻塞问题 {qid} 未标注 Mock/暂缓策略")
    return gaps


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def validate(project_root: Path, input_rel: str, check_baseline: bool = True) -> dict:
    input_dir = project_root / input_rel
    blocking: list[str] = []
    must_gaps: list[str] = []
    warnings: list[str] = []

    files = _discover(input_dir)
    if not input_dir.is_dir():
        return {
            "tool": "validate_input_contract",
            "inputDir": input_rel,
            "verdict": "not-applicable",
            "filesFound": {},
            "blocking": [],
            "mustGaps": [],
            "warnings": [f"{input_rel} 不存在，上游输入契约模式未启用"],
            "brokenRefs": [], "orphanIds": [], "definedIds": {},
            "capabilitySummary": {},
            "baseline": {"present": False},
            "nextAction": "回退到标准 Progressive Elicitation 流程",
        }

    raw = {k: _read(p) for k, p in files.items()}

    for key in ALWAYS_REQUIRED:
        if key not in files:
            blocking.append(f"{input_rel}/{key}-*.md 缺失（契约要求必须提供）")
        elif not raw[key].strip():
            blocking.append(f"{files[key].name} 为空文件")
    for key in RECOMMENDED:
        if key not in files:
            warnings.append(f"{input_rel}/{key}-*.md 缺失（建议提供，影响端到端路径与 E2E 设计）")

    defs = _collect_definitions(files, raw)
    refs = _collect_references(files, raw)

    # Conditionally-required owner files, driven by actual references.
    for prefix, needed_by in (("ST", "03"), ("RULE", "04")):
        if refs[prefix] and needed_by not in files:
            blocking.append(
                f"{input_rel}/{needed_by}-*.md 缺失，但已有 {len(refs[prefix])} 个 "
                f"{prefix}- 引用（如 {sorted(refs[prefix])[0]}）"
            )

    # Broken traceability links.
    broken: list[dict] = []
    for prefix, id_map in refs.items():
        owner = PREFIX_OWNER[prefix]
        for token, locations in sorted(id_map.items()):
            if token in defs[prefix]:
                continue
            entry = {
                "id": token,
                "prefix": prefix,
                "ownerFile": f"{owner}-*.md",
                "referencedAt": sorted(locations)[:5],
            }
            broken.append(entry)
            msg = (f"追溯链断裂: {token} 被引用于 {', '.join(entry['referencedAt'])}，"
                   f"但未定义于 {owner}-*.md")
            if owner not in files and owner in OPTIONAL_OWNERS:
                warnings.append(msg + "（该定义文件为可选，降级为提示）")
            else:
                blocking.append(msg)

    orphans = sorted(
        f"{token}(定义于 {PREFIX_OWNER[prefix]}-*.md，全库未被引用)"
        for prefix in ("ST", "RULE", "IF", "EX", "REL")
        for token in defs[prefix] - set(refs[prefix])
    )
    warnings.extend(orphans)

    cap_summary: dict = {}
    if "01" in files:
        cap_summary, cap_gaps, cap_warn = _check_capabilities(raw["01"])
        must_gaps.extend(cap_gaps)
        warnings.extend(cap_warn)
    if "00" in files:
        must_gaps.extend(_check_scope(raw["00"]))
    if "02" in files:
        must_gaps.extend(_check_entities(raw["02"]))
    if "03" in files:
        must_gaps.extend(_check_states(raw["03"]))
    if "04" in files:
        must_gaps.extend(_check_rules(raw["04"]))
    if "07" in files:
        must_gaps.extend(_check_questions(raw["07"]))

    # Baseline package (C-INPUT-01..04). Absent models/ => no-op, so the 00-07
    # contract keeps working unchanged for projects without BPMN/OWL assets.
    baseline: dict = {"present": False}
    if check_baseline:
        b_block, b_warn, baseline = _check_baseline(input_dir, defs, files)
        blocking.extend(b_block)
        warnings.extend(b_warn)

    if blocking:
        verdict = "fail"
    elif must_gaps:
        verdict = "partial" if cap_summary.get("mustComplete", 0) > 0 else "fail"
    else:
        verdict = "pass"

    next_action = {
        "pass": "Product Analyst 可跳过 Progressive Elicitation，直接进入 Phase B 全量产出 PRD",
        "partial": "Product Analyst 必须先输出 docs/输入缺口清单.md，仅对完整的 Must 能力生成 PRD 草案",
        "fail": "禁止生成 PRD；以 blocked 状态返回 Orchestrator 并附 docs/输入缺口清单.md",
    }[verdict]

    return {
        "tool": "validate_input_contract",
        "inputDir": input_rel,
        "verdict": verdict,
        "filesFound": {k: files[k].name for k in sorted(files)},
        "definedIds": {p: len(v) for p, v in sorted(defs.items()) if v},
        "brokenRefs": broken,
        "orphanIds": orphans,
        "capabilitySummary": cap_summary,
        "baseline": baseline,
        "blocking": blocking,
        "mustGaps": must_gaps,
        "warnings": warnings,
        "nextAction": next_action,
    }


def render_gap_list(report: dict) -> str:
    v = report["verdict"]
    lines = [
        "# 输入缺口清单",
        "",
        f"- 门禁结论：**{ {'pass': '通过', 'partial': '部分通过', 'fail': '不通过', 'not-applicable': '不适用'}[v] }**",
        f"- 输入目录：`{report['inputDir']}`",
        f"- 校验工具：`scripts/validate_input_contract.py`（机械校验，非人工判断）",
        f"- 后续动作：{report['nextAction']}",
        "",
    ]
    cap = report.get("capabilitySummary") or {}
    if cap:
        lines += [
            "## 能力完整性概览",
            "",
            "| 指标 | 值 |",
            "|------|----|",
            f"| 能力总数 | {cap.get('total', 0)} |",
            f"| Must 级能力 | {cap.get('must', 0)} |",
            f"| Must 完整 | {cap.get('mustComplete', 0)} |",
            f"| Must 不完整 | {', '.join(cap.get('mustIncomplete') or []) or '无'} |",
            "",
        ]
    for title, items, note in (
        ("阻塞项（必须补齐后才能生成 PRD）", report["blocking"], "无阻塞项。"),
        ("Must 级缺口（影响 PRD 完整性）", report["mustGaps"], "无 Must 级缺口。"),
        ("提示项（建议补充，不阻塞）", report["warnings"], "无提示项。"),
    ):
        lines.append(f"## {title}")
        lines.append("")
        if items:
            lines += [f"- {it}" for it in items]
        else:
            lines.append(note)
        lines.append("")
    lines += [
        "## 处理要求",
        "",
        "1. 阻塞项必须由上游补齐后重跑本脚本，AI 不得自行补全。",
        "2. Must 级缺口未关闭前，对应 capability 不得进入 PRD 正文。",
        "3. 任何 AI 推断必须在 PRD 中标注「AI 推断」。",
        "4. 高阻塞待确认问题必须进入 PRD「待确认项」并给出 mock/暂缓策略。",
        "",
    ]
    return "\n".join(lines)


def _print_human(report: dict) -> None:
    icon = {"pass": "[PASS]", "partial": "[PARTIAL]",
            "fail": "[FAIL]", "not-applicable": "[N/A]"}[report["verdict"]]
    print(f"{icon} 输入完整性门禁 verdict = {report['verdict']}")
    print(f"       输入目录: {report['inputDir']}")
    if report["filesFound"]:
        print(f"       已发现文件: {', '.join(report['filesFound'].values())}")
    if report.get("definedIds"):
        stats = ", ".join(f"{p}={n}" for p, n in report["definedIds"].items())
        print(f"       已定义编号: {stats}")
    cap = report.get("capabilitySummary") or {}
    if cap:
        print(f"       能力: 总数={cap.get('total', 0)} Must={cap.get('must', 0)} "
              f"Must完整={cap.get('mustComplete', 0)}")
    bl = report.get("baseline") or {}
    if bl.get("present"):
        print(f"       基线包: id={bl.get('baselineId') or '(未声明)'} "
              f"收录={bl.get('filesListed', 0)} "
              f"BPMN={bl.get('bpmnFiles', 0)}文件/{bl.get('bpmnNodeIds', 0)}节点 "
              f"OWL={bl.get('owlFiles', 0)}文件/{bl.get('owlClassIds', 0)}类")
    for label, items in (("阻塞", report["blocking"]),
                         ("Must缺口", report["mustGaps"]),
                         ("提示", report["warnings"])):
        for item in items:
            print(f"       - [{label}] {item}")
    print(f"       下一步: {report['nextAction']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the upstream PRD input contract in docs/input/.")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--input-dir", default="docs/input",
                        help="Input directory relative to project root")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--report-out", help="Write the JSON report to this path")
    parser.add_argument("--gap-list-out",
                        help="Write the markdown gap list to this path "
                             "(e.g. docs/输入缺口清单.md)")
    parser.add_argument("--baseline", action="store_true",
                        help="Explicitly run the baseline package checks "
                             "(C-INPUT-01..04). On by default when models/ exists.")
    parser.add_argument("--no-baseline", action="store_true",
                        help="Skip baseline package checks (00-07 contract only)")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(f"error: project root not found: {project_root}", file=sys.stderr)
        return 3

    report = validate(project_root, args.input_dir.replace("\\", "/"),
                      check_baseline=not args.no_baseline)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)

    if args.report_out:
        out = Path(args.report_out)
        if not out.is_absolute():
            out = project_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.gap_list_out and report["verdict"] != "not-applicable":
        out = Path(args.gap_list_out)
        if not out.is_absolute():
            out = project_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_gap_list(report), encoding="utf-8")

    return {"pass": 0, "not-applicable": 0, "partial": 1, "fail": 2}[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
