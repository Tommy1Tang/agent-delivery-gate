#!/usr/bin/env python3
"""Detect and load project-level design system files for UI consistency.

When a project contains a design system specification (e.g. design.md),
this module extracts its location and key metadata so the Orchestrator can
inject it into UI Designer and Frontend Engineer handoffs as a binding
constraint.  This ensures every delivery uses the SAME color palette,
typography, spacing, layout, and component rules — eliminating cross-run
UI inconsistency.

Usage:
    python design_system_loader.py --project-root /path/to/project [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── File discovery patterns ────────────────────────────────────────────
# Ordered by priority.  First match wins when multiple files exist.
DESIGN_SYSTEM_FILE_PATTERNS: list[str] = [
    # Exact names (root)
    "design.md",
    "design-system.md",
    "design-tokens.md",
    "设计系统.md",
    "设计规范.md",
    # Under docs/
    "docs/design.md",
    "docs/design-system.md",
    "docs/design-tokens.md",
    "docs/设计系统.md",
    "docs/设计规范.md",
    # Under .design/ or design/
    "design/design-system.md",
    ".design/design-system.md",
]

# Glob fallback: catch files like  *.design.md  or  design-*.md
DESIGN_SYSTEM_GLOBS: list[str] = [
    "*.design.md",
    "design-*.md",
    "docs/*.design.md",
    "docs/design-*.md",
]

# ── Token extraction patterns ──────────────────────────────────────────
# These regex patterns extract key design tokens from the file content so
# we can build a fingerprint and summary for handoff injection.

COLOR_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
FONT_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:px|rem|em)\b")
SPACING_RE = re.compile(r"(\d+)\s*px\b")
BORDER_RADIUS_RE = re.compile(r"(?:border[-\s]?radius|圆角)[^:]*:\s*`?(\d+\s*px)`?", re.IGNORECASE)
SHADOW_RE = re.compile(r"box-shadow:\s*([^;]+);", re.IGNORECASE)

# Section heading patterns for structured extraction
SECTION_HEADING_RE = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)


def _file_hash(path: Path) -> str:
    """SHA-256 of file content for change detection."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _extract_colors(text: str) -> list[str]:
    """Extract unique hex color values from design doc."""
    colors = COLOR_HEX_RE.findall(text)
    # Normalize to uppercase, deduplicate, preserve order
    seen: set[str] = set()
    result: list[str] = []
    for c in colors:
        upper = c.upper()
        if upper not in seen:
            seen.add(upper)
            result.append(upper)
    return result


def _extract_sections(text: str) -> list[str]:
    """Extract section headings for structure fingerprint."""
    return SECTION_HEADING_RE.findall(text)


def _extract_key_tokens(text: str) -> dict:
    """Extract a summary of design tokens for handoff metadata."""
    colors = _extract_colors(text)
    sections = _extract_sections(text)

    # Try to identify key semantic categories
    has_typography = any(
        kw in text.lower()
        for kw in ["字体", "font", "排版", "typography", "font-size", "字号"]
    )
    has_spacing = any(
        kw in text.lower()
        for kw in ["间距", "spacing", "padding", "margin", "边距"]
    )
    has_layout = any(
        kw in text.lower()
        for kw in ["布局", "layout", "grid", "网格", "栅格", "flex", "sidebar", "导航"]
    )
    has_color_system = any(
        kw in text.lower()
        for kw in ["色彩", "颜色", "color", "palette", "色值", "主色", "品牌色"]
    )
    has_component_spec = any(
        kw in text.lower()
        for kw in ["组件", "component", "table", "表格", "card", "卡片", "按钮", "button"]
    )
    has_effects = any(
        kw in text.lower()
        for kw in ["圆角", "阴影", "shadow", "radius", "border", "动效", "animation"]
    )

    return {
        "colorCount": len(colors),
        "sampleColors": colors[:10],
        "sectionCount": len(sections),
        "sections": sections[:20],
        "coverage": {
            "colorSystem": has_color_system,
            "typography": has_typography,
            "spacing": has_spacing,
            "layout": has_layout,
            "components": has_component_spec,
            "effects": has_effects,
        },
    }


def detect_design_system(project_root: Path, skill_root: Path | None = None) -> dict | None:
    """Detect a design system file.

    Priority order:
    1. Skill-level: {skill_root}/assets/design.md (always available, shared across projects)
    2. Project-level: {project_root}/design.md etc. (project-specific override)

    Returns a structured dict with file metadata and token summary,
    or None if no design system file is found.
    """
    # Phase 0: Skill-level design system (highest priority)
    if skill_root is not None:
        skill_design = skill_root.resolve() / "assets" / "design.md"
        if skill_design.exists() and skill_design.is_file():
            return _build_result(skill_design, skill_root.resolve(), "assets/design.md", source="skill")

    root = project_root.resolve()

    # Phase 1: Check exact-name patterns (priority order)
    for pattern in DESIGN_SYSTEM_FILE_PATTERNS:
        candidate = root / pattern
        if candidate.exists() and candidate.is_file():
            return _build_result(candidate, root, pattern)

    # Phase 2: Glob fallback
    for glob_pattern in DESIGN_SYSTEM_GLOBS:
        matches = sorted(root.glob(glob_pattern))
        for match in matches:
            if match.is_file() and match.stat().st_size > 50:
                rel = match.relative_to(root).as_posix()
                return _build_result(match, root, rel)

    return None


def _build_result(path: Path, root: Path, rel_path: str, source: str = "project") -> dict:
    """Build the design system detection result."""
    content = path.read_text(encoding="utf-8", errors="replace")
    tokens = _extract_key_tokens(content)
    content_hash = _file_hash(path)

    # Compute completeness score (0-100)
    coverage = tokens["coverage"]
    coverage_count = sum(1 for v in coverage.values() if v)
    completeness = int((coverage_count / len(coverage)) * 100)

    return {
        "detected": True,
        "source": source,
        "filePath": rel_path,
        "absolutePath": str(path),
        "contentHash": content_hash,
        "sizeBytes": path.stat().st_size,
        "lineCount": content.count("\n") + 1,
        "completeness": completeness,
        "tokens": tokens,
        "bindingLevel": _determine_binding_level(completeness, tokens),
        "detectedAt": datetime.now(timezone.utc).isoformat(),
    }


def _determine_binding_level(completeness: int, tokens: dict) -> str:
    """Determine how strictly the design system should be enforced.

    - "strict": comprehensive design system (≥70% coverage) → MUST follow exactly
    - "reference": partial design system (30-69%) → SHOULD follow, fill gaps
    - "hint": minimal design system (<30%) → reference only, create full system
    """
    if completeness >= 70:
        return "strict"
    if completeness >= 30:
        return "reference"
    return "hint"


def build_handoff_binding(detection_result: dict) -> dict:
    """Build the designSystemBinding payload for handoff injection.

    This is the structured context injected into UI Designer and Frontend
    Engineer handoffs to ensure they follow the project's design system.
    """
    if not detection_result or not detection_result.get("detected"):
        return {"bound": False}

    binding_level = detection_result["bindingLevel"]
    file_path = detection_result["filePath"]
    tokens = detection_result["tokens"]
    coverage = tokens["coverage"]

    constraints: list[str] = []

    if binding_level == "strict":
        constraints = [
            f"MANDATORY: Read and follow '{file_path}' as the single source of truth for all visual design decisions.",
            "All color values (primary, semantic, neutral) MUST be taken from the design system file — no freestyle colors.",
            "Typography scale (font sizes, weights, line heights) MUST match the design system specification.",
            "Spacing system, border radius, and shadow values MUST match the design system specification.",
            "Layout structure (sidebar width, header height, content area) MUST follow the design system specification.",
            "Component visual specifications (table density, card styles, button variants) MUST follow the design system.",
            "When the design system specifies exact pixel values or hex codes, use them verbatim — do not approximate.",
            "If the design system is silent on a topic, follow Element Plus defaults and document the gap.",
        ]
    elif binding_level == "reference":
        covered = [k for k, v in coverage.items() if v]
        uncovered = [k for k, v in coverage.items() if not v]
        constraints = [
            f"REFERENCE: Read '{file_path}' and adopt its specifications for covered areas: {', '.join(covered)}.",
            f"For uncovered areas ({', '.join(uncovered)}), create specifications consistent with the design system's visual language.",
            "Color palette and primary brand color MUST be taken from the design system file if defined.",
            "Layout patterns MUST follow the design system file if defined.",
            "Document any design decisions that extend beyond the design system file.",
        ]
    else:  # hint
        constraints = [
            f"HINT: '{file_path}' provides partial design guidance. Read it for directional input.",
            "Create a complete design system that is consistent with the hints provided.",
            "Document all design decisions and their relationship to the hint file.",
        ]

    return {
        "bound": True,
        "bindingLevel": binding_level,
        "designSystemFile": file_path,
        "contentHash": detection_result["contentHash"],
        "completeness": detection_result["completeness"],
        "tokenSummary": {
            "sampleColors": tokens.get("sampleColors", []),
            "coverage": coverage,
        },
        "constraints": constraints,
        "hardRules": [
            "Cross-run consistency: identical design.md content hash → identical visual output.",
            "Brand color lock: primary color from design system is immutable without BREAKING CHANGE process.",
            "Token precedence: design system file tokens override UI Designer default suggestions.",
            "Layout fidelity: structural specifications (grid, sidebar, header) must be pixel-accurate.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Path to project root")
    parser.add_argument("--skill-root", default=None, help="Path to skill root (checks assets/design.md)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    skill = Path(args.skill_root).resolve() if args.skill_root else None
    result = detect_design_system(root, skill)

    if args.json:
        print(json.dumps(result or {"detected": False}, ensure_ascii=False, indent=2))
    else:
        if result:
            print(f"Design system detected: {result['filePath']}")
            print(f"  Binding level: {result['bindingLevel']}")
            print(f"  Completeness: {result['completeness']}%")
            print(f"  Content hash: {result['contentHash']}")
            print(f"  Colors found: {result['tokens']['colorCount']}")
            print(f"  Sections: {result['tokens']['sectionCount']}")
            coverage = result["tokens"]["coverage"]
            covered = [k for k, v in coverage.items() if v]
            print(f"  Covered areas: {', '.join(covered) if covered else 'none'}")

            binding = build_handoff_binding(result)
            print(f"\n  Handoff binding level: {binding['bindingLevel']}")
            print(f"  Constraints ({len(binding['constraints'])}):")
            for c in binding["constraints"]:
                print(f"    - {c}")
        else:
            print("No design system file detected.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
