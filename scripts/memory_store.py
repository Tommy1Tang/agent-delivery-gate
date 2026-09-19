#!/usr/bin/env python3
"""M1/M2/M3: Unified project memory store for the software-development-team skill.

Provides read/write/query capabilities for three memory types:
  M1 — Team Memory: project-level preferences and conventions
  M2 — Failure Patterns: recurring failure fingerprints for prevention
  M3 — ADR Store: append-only architecture decision records

Storage location: <project_root>/.qoder/skill-state/
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_STATE_DIR = ".qoder/skill-state"
TEAM_MEMORY_FILE = "team-memory.json"
FAILURE_PATTERNS_FILE = "failure-patterns.json"
ADR_STORE_FILE = "adr-store.jsonl"

MAX_DELIVERY_HISTORY = 20
MAX_FAILURE_PATTERNS = 200
MAX_MATCHED_PATTERNS = 5


def _state_dir(project_root: Path) -> Path:
    return project_root / SKILL_STATE_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stack_signature(stack_snapshot: dict | None) -> str:
    """Create a stable hash of selectedAdapters for stack-level matching."""
    if not stack_snapshot:
        return "unknown"
    adapters = sorted(stack_snapshot.get("selectedAdapters", []))
    return hashlib.sha256("|".join(adapters).encode()).hexdigest()[:12]


def _project_key(project_root: Path) -> str:
    """Create a stable key for the project (uses last 2 dir components)."""
    parts = project_root.resolve().parts
    return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1] if parts else "unknown"


# ─── M1: Team Memory ────────────────────────────────────────────────────────────


def _default_team_memory(project_root: Path, stack_snapshot: dict | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "projectKey": _project_key(project_root),
        "stackSignature": _stack_signature(stack_snapshot),
        "preferences": {},
        "conventions": [],
        "deliveryHistory": [],
        "updatedAt": _now_iso(),
    }


def load_team_memory(project_root: Path) -> dict:
    """Load team memory for a project. Returns default if not exists."""
    f = _state_dir(project_root) / TEAM_MEMORY_FILE
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return _default_team_memory(project_root)


def save_team_memory(project_root: Path, memory: dict) -> Path:
    """Persist team memory to disk."""
    d = _state_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    f = d / TEAM_MEMORY_FILE
    memory["updatedAt"] = _now_iso()
    f.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def set_preference(memory: dict, key: str, value, scope: str = "project",
                   source: str = "inferred", rationale: str = "") -> dict:
    """Set or update a preference in team memory."""
    memory["preferences"][key] = {
        "value": value,
        "scope": scope,
        "source": source,
        "rationale": rationale,
        "updatedAt": _now_iso(),
    }
    return memory


def add_convention(memory: dict, category: str, rule: str,
                   examples: list[str] | None = None) -> dict:
    """Add a convention if not already recorded (dedup by rule text)."""
    existing_rules = {c["rule"] for c in memory.get("conventions", [])}
    if rule in existing_rules:
        return memory  # Already exists
    conv_id = f"CONV-{len(memory.get('conventions', [])) + 1:03d}"
    memory.setdefault("conventions", []).append({
        "id": conv_id,
        "category": category,
        "rule": rule,
        "examples": examples or [],
        "addedAt": _now_iso(),
    })
    return memory


def record_delivery(memory: dict, delivery_id: str, task_summary: str,
                    outcome: str = "success") -> dict:
    """Append a delivery to history (keeps last MAX_DELIVERY_HISTORY)."""
    history = memory.setdefault("deliveryHistory", [])
    history.append({
        "deliveryId": delivery_id,
        "taskSummary": task_summary[:200],
        "completedAt": _now_iso(),
        "outcome": outcome,
    })
    if len(history) > MAX_DELIVERY_HISTORY:
        memory["deliveryHistory"] = history[-MAX_DELIVERY_HISTORY:]
    return memory


def get_conventions_for_handoff(memory: dict) -> list[str]:
    """Extract convention rules as plain strings for handoff injection."""
    return [c["rule"] for c in memory.get("conventions", [])]


def get_preferences_for_handoff(memory: dict) -> dict[str, object]:
    """Extract preference values as a simple key→value dict for handoff."""
    return {k: v["value"] for k, v in memory.get("preferences", {}).items()}


# ─── M2: Failure Patterns ───────────────────────────────────────────────────────


def _default_failure_patterns() -> dict:
    return {"schemaVersion": 1, "patterns": []}


def load_failure_patterns(project_root: Path) -> dict:
    """Load failure patterns for a project."""
    f = _state_dir(project_root) / FAILURE_PATTERNS_FILE
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return _default_failure_patterns()


def save_failure_patterns(project_root: Path, patterns: dict) -> Path:
    """Persist failure patterns to disk."""
    d = _state_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    f = d / FAILURE_PATTERNS_FILE
    # Cap total patterns
    if len(patterns.get("patterns", [])) > MAX_FAILURE_PATTERNS:
        patterns["patterns"] = patterns["patterns"][-MAX_FAILURE_PATTERNS:]
    f.write_text(json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def _normalize_signature(text: str) -> str:
    """Normalize a failure description into a matchable signature."""
    # Keep alphanumeric + CJK, collapse whitespace
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]", " ", text.lower())
    tokens = sorted(set(cleaned.split()))[:8]  # Top 8 unique tokens
    return "|".join(tokens)


def ingest_failure(patterns: dict, summary: str, category: str = "other",
                   root_cause: str = "", fix_hint: str = "",
                   stack_sig: str = "", evidence_link: str = "") -> dict:
    """Record a failure event. If matching signature exists, increment count."""
    sig = _normalize_signature(summary)
    existing = None
    for p in patterns.get("patterns", []):
        if p.get("signature") == sig:
            existing = p
            break

    now = _now_iso()
    if existing:
        existing["occurrences"] = existing.get("occurrences", 1) + 1
        existing["lastSeenAt"] = now
        if root_cause and not existing.get("rootCause"):
            existing["rootCause"] = root_cause
        if fix_hint and not existing.get("fixHint"):
            existing["fixHint"] = fix_hint
        if stack_sig and stack_sig not in existing.get("stackSignatures", []):
            existing.setdefault("stackSignatures", []).append(stack_sig)
        if evidence_link:
            existing.setdefault("evidenceLinks", []).append(evidence_link)
    else:
        fp_id = f"FP-{len(patterns.get('patterns', [])) + 1:03d}"
        patterns.setdefault("patterns", []).append({
            "id": fp_id,
            "signature": sig,
            "category": category,
            "summary": summary[:300],
            "rootCause": root_cause,
            "fixHint": fix_hint,
            "triggerConditions": [],
            "stackSignatures": [stack_sig] if stack_sig else [],
            "occurrences": 1,
            "firstSeenAt": now,
            "lastSeenAt": now,
            "evidenceLinks": [evidence_link] if evidence_link else [],
        })

    return patterns


def match_failure_patterns(patterns: dict, task_summary: str,
                           stack_sig: str = "", top_k: int = MAX_MATCHED_PATTERNS) -> list[dict]:
    """Find failure patterns relevant to the given task/stack.

    Scoring: +2 for stack signature match, +1 per keyword overlap, +1 per occurrence.
    """
    task_tokens = set(re.sub(r"[^\w\u4e00-\u9fff]", " ", task_summary.lower()).split())
    results: list[tuple[float, dict]] = []

    for p in patterns.get("patterns", []):
        score = 0.0
        # Stack signature match
        if stack_sig and stack_sig in p.get("stackSignatures", []):
            score += 2.0
        # Keyword overlap with signature
        sig_tokens = set(p.get("signature", "").split("|"))
        overlap = task_tokens & sig_tokens
        score += len(overlap)
        # Recurrence boost (log scale)
        import math
        score += math.log1p(p.get("occurrences", 1))
        if score > 0.5:
            results.append((score, p))

    results.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in results[:top_k]]


# ─── M3: ADR Store ──────────────────────────────────────────────────────────────


def load_adr_store(project_root: Path) -> list[dict]:
    """Load all ADR records (JSONL format, one record per line)."""
    f = _state_dir(project_root) / ADR_STORE_FILE
    if not f.is_file():
        return []
    records = []
    try:
        for line in f.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return records


def append_adr(project_root: Path, title: str, context: str, decision: str,
               consequences: dict | None = None, alternatives: list[dict] | None = None,
               delivery_id: str = "", tags: list[str] | None = None) -> dict:
    """Append a new ADR record. Returns the created record."""
    existing = load_adr_store(project_root)
    adr_id = f"ADR-{len(existing) + 1:04d}"
    record = {
        "id": adr_id,
        "title": title,
        "status": "accepted",
        "context": context,
        "decision": decision,
        "consequences": consequences or {"positive": [], "negative": [], "risks": []},
        "alternatives": alternatives or [],
        "supersededBy": None,
        "deliveryId": delivery_id,
        "createdAt": _now_iso(),
        "tags": tags or [],
    }

    d = _state_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    f = d / ADR_STORE_FILE
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def supersede_adr(project_root: Path, old_id: str, new_id: str) -> bool:
    """Mark an existing ADR as superseded by a newer one."""
    records = load_adr_store(project_root)
    found = False
    for r in records:
        if r["id"] == old_id:
            r["status"] = "superseded"
            r["supersededBy"] = new_id
            found = True

    if found:
        d = _state_dir(project_root)
        f = d / ADR_STORE_FILE
        with open(f, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return found


def get_active_adrs(project_root: Path) -> list[dict]:
    """Get only active (non-superseded) ADRs."""
    return [r for r in load_adr_store(project_root) if r.get("status") == "accepted"]


def search_adrs(project_root: Path, keywords: list[str]) -> list[dict]:
    """Search ADRs by keywords in title/context/decision/tags."""
    records = load_adr_store(project_root)
    kw_lower = [k.lower() for k in keywords]
    matched = []
    for r in records:
        searchable = " ".join([
            r.get("title", ""),
            r.get("context", ""),
            r.get("decision", ""),
            " ".join(r.get("tags", [])),
        ]).lower()
        if any(k in searchable for k in kw_lower):
            matched.append(r)
    return matched


# ─── Unified Query for Orchestrator ─────────────────────────────────────────────


def load_project_memory(project_root: Path, stack_snapshot: dict | None = None,
                        task_summary: str = "") -> dict:
    """Load all memory layers for a project, returning a unified context dict.

    This is the main entry point used by orchestrate.py to inject memory into handoffs.
    """
    team = load_team_memory(project_root)
    fp = load_failure_patterns(project_root)
    stack_sig = _stack_signature(stack_snapshot)

    matched_patterns = match_failure_patterns(fp, task_summary, stack_sig)
    active_adrs = get_active_adrs(project_root)

    # Build compact injection payload
    conventions = get_conventions_for_handoff(team)
    preferences = get_preferences_for_handoff(team)
    recent_deliveries = team.get("deliveryHistory", [])[-5:]  # Last 5

    pattern_hints = [
        {"id": p["id"], "summary": p["summary"], "fixHint": p.get("fixHint", ""),
         "occurrences": p.get("occurrences", 1)}
        for p in matched_patterns
    ]

    adr_hints = [
        {"id": a["id"], "title": a["title"], "decision": a["decision"][:200]}
        for a in active_adrs[-10:]  # Last 10 active
    ]

    has_memory = bool(conventions or preferences or pattern_hints or adr_hints)

    # M8: Run conflict arbitration before injection.
    conflict_report = resolve_conflicts(team, project_root)
    # Re-extract conventions after conflict resolution (losers removed).
    if conflict_report.get("resolutions"):
        conventions = get_conventions_for_handoff(team)

    return {
        "hasMemory": has_memory,
        "projectKey": team.get("projectKey", ""),
        "stackSignature": stack_sig,
        "conventions": conventions,
        "preferences": preferences,
        "recentDeliveries": recent_deliveries,
        "failurePatternHints": pattern_hints,
        "adrHints": adr_hints,
        "memoryStats": {
            "totalConventions": len(conventions),
            "totalPreferences": len(preferences),
            "totalFailurePatterns": len(fp.get("patterns", [])),
            "matchedFailurePatterns": len(matched_patterns),
            "totalADRs": len(load_adr_store(project_root)),
            "activeADRs": len(active_adrs),
        },
    }


# ─── M8: Memory Conflict Arbitration ─────────────────────────────────────────────


def detect_convention_conflicts(memory: dict) -> list[dict]:
    """M8: Detect contradictory conventions in team memory."""
    conventions = memory.get("conventions", [])
    if len(conventions) < 2:
        return []

    conflicts: list[dict] = []
    contradiction_pairs = [
        ("中文", "英文"), ("chinese", "english"),
        ("禁止", "允许"), ("禁止", "必须"),
        ("camelCase", "snake_case"), ("camelcase", "snake_case"),
        ("不要", "必须"), ("disable", "enable"),
        ("删除", "保留"), ("remove", "keep"),
    ]

    for i, c1 in enumerate(conventions):
        for c2 in conventions[i + 1:]:
            if c1.get("category") != c2.get("category"):
                continue
            r1, r2 = c1["rule"].lower(), c2["rule"].lower()
            for a, b in contradiction_pairs:
                if (a in r1 and b in r2) or (b in r1 and a in r2):
                    conflicts.append({
                        "type": "convention-contradiction",
                        "ids": [c1["id"], c2["id"]],
                        "rules": [c1["rule"], c2["rule"]],
                        "category": c1.get("category"),
                        "trigger": f"{a} vs {b}",
                    })
    return conflicts


def detect_adr_conflicts(project_root: Path) -> list[dict]:
    """M8: Detect active ADRs that contradict each other."""
    active = get_active_adrs(project_root)
    conflicts: list[dict] = []

    for i, a1 in enumerate(active):
        for a2 in active[i + 1:]:
            shared_tags = set(a1.get("tags", [])) & set(a2.get("tags", []))
            if not shared_tags:
                continue
            d1, d2 = a1["decision"].lower(), a2["decision"].lower()
            signals = [("不使用", "使用"), ("remove", "add"), ("禁止", "允许"), ("删除", "保留")]
            for a, b in signals:
                if (a in d1 and b in d2) or (b in d1 and a in d2):
                    conflicts.append({
                        "type": "adr-contradiction",
                        "ids": [a1["id"], a2["id"]],
                        "titles": [a1["title"], a2["title"]],
                        "sharedTags": list(shared_tags),
                    })
    return conflicts


def resolve_conflicts(memory: dict, project_root: Path) -> dict:
    """M8: Run all conflict detectors and auto-resolve where possible.

    Resolution rules: newer timestamp wins for same-category convention conflicts.
    ADR conflicts are reported but not auto-resolved (require explicit supersede).
    """
    conv_conflicts = detect_convention_conflicts(memory)
    adr_conflicts = detect_adr_conflicts(project_root)
    resolutions: list[dict] = []

    for conflict in conv_conflicts:
        ids = conflict["ids"]
        convs = [c for c in memory.get("conventions", []) if c["id"] in ids]
        if len(convs) == 2:
            t0 = convs[0].get("addedAt", "")
            t1 = convs[1].get("addedAt", "")
            winner = convs[1] if t1 >= t0 else convs[0]
            loser = convs[0] if winner == convs[1] else convs[1]
            resolutions.append({
                "action": "keep-newer",
                "winner": winner["id"],
                "loser": loser["id"],
                "reason": f"Newer '{winner['rule'][:50]}' supersedes '{loser['rule'][:50]}'",
            })
            memory["conventions"] = [c for c in memory.get("conventions", []) if c["id"] != loser["id"]]

    return {
        "conflicts": conv_conflicts + adr_conflicts,
        "resolutions": resolutions,
        "unresolvedCount": len(adr_conflicts),
        "stats": {
            "conventionConflicts": len(conv_conflicts),
            "adrConflicts": len(adr_conflicts),
            "autoResolved": len(resolutions),
        },
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    p_show = sub.add_parser("show", help="Show project memory summary")
    p_show.add_argument("--project-root", default=".", help="Project root")
    p_show.add_argument("--json", action="store_true")

    p_ingest = sub.add_parser("ingest-failure", help="Record a failure pattern")
    p_ingest.add_argument("--project-root", default=".")
    p_ingest.add_argument("--summary", required=True)
    p_ingest.add_argument("--category", default="other")
    p_ingest.add_argument("--fix-hint", default="")

    p_adr = sub.add_parser("add-adr", help="Add an ADR")
    p_adr.add_argument("--project-root", default=".")
    p_adr.add_argument("--title", required=True)
    p_adr.add_argument("--context", required=True)
    p_adr.add_argument("--decision", required=True)

    p_conv = sub.add_parser("add-convention", help="Add a convention")
    p_conv.add_argument("--project-root", default=".")
    p_conv.add_argument("--category", required=True)
    p_conv.add_argument("--rule", required=True)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 0

    pr = Path(args.project_root).resolve()

    if args.cmd == "show":
        ctx = load_project_memory(pr)
        if args.json:
            print(json.dumps(ctx, ensure_ascii=False, indent=2))
        else:
            stats = ctx["memoryStats"]
            print(f"Project Memory: {ctx['projectKey']}")
            print(f"  Stack: {ctx['stackSignature']}")
            print(f"  Conventions: {stats['totalConventions']}")
            print(f"  Preferences: {stats['totalPreferences']}")
            print(f"  Failure Patterns: {stats['matchedFailurePatterns']}/{stats['totalFailurePatterns']} matched")
            print(f"  ADRs: {stats['activeADRs']} active / {stats['totalADRs']} total")
            if ctx["conventions"]:
                print("  Recent conventions:")
                for c in ctx["conventions"][:5]:
                    print(f"    - {c}")

    elif args.cmd == "ingest-failure":
        fp = load_failure_patterns(pr)
        fp = ingest_failure(fp, args.summary, args.category, fix_hint=args.fix_hint)
        save_failure_patterns(pr, fp)
        print(f"Failure pattern ingested: {args.summary[:60]}")

    elif args.cmd == "add-adr":
        record = append_adr(pr, args.title, args.context, args.decision)
        print(f"ADR created: {record['id']} — {record['title']}")

    elif args.cmd == "add-convention":
        tm = load_team_memory(pr)
        tm = add_convention(tm, args.category, args.rule)
        save_team_memory(pr, tm)
        print(f"Convention added: [{args.category}] {args.rule[:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
