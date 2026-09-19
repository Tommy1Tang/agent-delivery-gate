#!/usr/bin/env python3
"""
设计系统对齐 linter（S2-4）

扫描前端源码，识别违反设计系统的硬编码：
- 硬编码颜色（#hex / rgb() / hsl()）
- 硬编码间距（px / rem，不在允许列表）
- 硬编码字号

调用：
    python scripts/design_system_lint.py --src <frontend-src-dir> [--tokens <tokens.json>]

退出码：
    0  无 P0 违规
    1  含 P0 违规（inline style 中硬编码 + 关键样式硬编码）
    2  使用错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

EXTS = {".vue", ".tsx", ".jsx", ".ts", ".js", ".css", ".scss", ".less"}

# 颜色：#xxx / #xxxxxx / rgb(...) / hsl(...)
COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgb\s*\(|rgba\s*\(|hsl\s*\(|hsla\s*\(")
# 字号
FONT_SIZE_PATTERN = re.compile(r"font-size\s*:\s*\d+(?:\.\d+)?(?:px|rem|em)", re.IGNORECASE)
# 硬编码间距（基于常见属性）
SPACING_PATTERN = re.compile(
    r"(?:margin|padding|gap|top|left|right|bottom|width|height)\s*:\s*\d+(?:\.\d+)?px",
    re.IGNORECASE,
)
# inline style 出现关键属性
INLINE_STYLE_PATTERN = re.compile(r"style\s*=\s*[\"']([^\"']+)[\"']")


def is_inline_style_violation(snippet: str) -> bool:
    return bool(
        COLOR_PATTERN.search(snippet)
        or FONT_SIZE_PATTERN.search(snippet)
        or SPACING_PATTERN.search(snippet)
    )


def scan_file(path: Path) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    # P0: inline style 中含硬编码
    for match in INLINE_STYLE_PATTERN.finditer(text):
        if is_inline_style_violation(match.group(1)):
            line_no = text.count("\n", 0, match.start()) + 1
            findings.append({
                "file": str(path),
                "line": line_no,
                "severity": "P0",
                "rule": "inline-style-hardcoded",
                "snippet": match.group(0)[:200],
            })

    # P1: 颜色硬编码
    for match in COLOR_PATTERN.finditer(text):
        line_no = text.count("\n", 0, match.start()) + 1
        # 跳过 .css/.scss 中的 :root / token 定义
        line_text = text.splitlines()[line_no - 1] if line_no - 1 < len(text.splitlines()) else ""
        if "--" in line_text and ":" in line_text:
            continue  # 是 CSS 变量定义
        findings.append({
            "file": str(path),
            "line": line_no,
            "severity": "P1",
            "rule": "hardcoded-color",
            "snippet": match.group(0),
        })

    # P1: 字号硬编码
    for match in FONT_SIZE_PATTERN.finditer(text):
        line_no = text.count("\n", 0, match.start()) + 1
        findings.append({
            "file": str(path),
            "line": line_no,
            "severity": "P1",
            "rule": "hardcoded-font-size",
            "snippet": match.group(0),
        })

    # P1: 间距硬编码
    for match in SPACING_PATTERN.finditer(text):
        line_no = text.count("\n", 0, match.start()) + 1
        findings.append({
            "file": str(path),
            "line": line_no,
            "severity": "P1",
            "rule": "hardcoded-spacing",
            "snippet": match.group(0),
        })

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Design system alignment lint (S2-4)")
    parser.add_argument("--src", required=True, help="前端源码目录")
    parser.add_argument("--tokens", help="design tokens 文件（可选，预留）")
    args = parser.parse_args()

    src = Path(args.src).resolve()
    if not src.exists():
        print(f"[design_system_lint] src not found: {src}", file=sys.stderr)
        return 2

    findings: List[Dict[str, Any]] = []
    for path in src.rglob("*"):
        if path.suffix.lower() not in EXTS:
            continue
        if "node_modules" in path.parts or "dist" in path.parts:
            continue
        findings.extend(scan_file(path))

    p0 = [f for f in findings if f["severity"] == "P0"]
    p1 = [f for f in findings if f["severity"] == "P1"]

    summary = {
        "status": "block" if p0 else ("warn" if p1 else "pass"),
        "src": str(src),
        "p0Count": len(p0),
        "p1Count": len(p1),
        "findings": findings[:500],  # 截断防止过长
        "truncated": len(findings) > 500,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if p0 else 0


if __name__ == "__main__":
    sys.exit(main())
