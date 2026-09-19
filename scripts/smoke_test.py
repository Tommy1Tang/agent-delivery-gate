#!/usr/bin/env python3
"""
Smoke Test 前置门禁（S2-1）

用途：在质量门禁角色派发前，验证项目能否编译/构建。结果写入 stdout JSON 并返回非零退出码以阻断 pipeline。

支持的项目类型（自动探测）：
- Maven (pom.xml) -> mvn -q -DskipTests compile
- Gradle (build.gradle / build.gradle.kts) -> gradle -q compileJava -x test
- npm (package.json with build script) -> npm run build
- TypeScript (tsconfig.json) -> npx tsc --noEmit

调用：
    python scripts/smoke_test.py --project-root <path> [--json]

退出码：
    0  全部 smoke 通过
    1  至少一个 smoke 失败
    2  使用错误
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


def detect_targets(root: Path) -> List[Dict[str, Any]]:
    """根据项目结构识别需要执行的 smoke 命令。"""
    targets: List[Dict[str, Any]] = []

    # Backend - Maven
    for pom in root.rglob("pom.xml"):
        if "target" in pom.parts or "node_modules" in pom.parts:
            continue
        targets.append({
            "kind": "maven-compile",
            "cwd": str(pom.parent),
            "cmd": ["mvn", "-q", "-DskipTests", "compile"],
        })

    # Backend - Gradle
    for gradle in list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts")):
        if "build" in gradle.parts or "node_modules" in gradle.parts:
            continue
        targets.append({
            "kind": "gradle-compile",
            "cwd": str(gradle.parent),
            "cmd": ["gradle", "-q", "compileJava", "-x", "test"],
        })

    # Frontend - npm build
    for pkg in root.rglob("package.json"):
        if "node_modules" in pkg.parts or "dist" in pkg.parts:
            continue
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scripts = data.get("scripts", {}) or {}
        if "build" in scripts:
            targets.append({
                "kind": "npm-build",
                "cwd": str(pkg.parent),
                "cmd": ["npm", "run", "build"],
            })
        elif "type-check" in scripts or "typecheck" in scripts:
            tc = "type-check" if "type-check" in scripts else "typecheck"
            targets.append({
                "kind": "npm-typecheck",
                "cwd": str(pkg.parent),
                "cmd": ["npm", "run", tc],
            })

    return targets


def run_target(target: Dict[str, Any], timeout: int = 600) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            target["cmd"],
            cwd=target["cwd"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            shell=False,
        )
        elapsed_ms = int((time.time() - started) * 1000)
        ok = proc.returncode == 0
        output = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        # 限制 output 长度避免淹没 ledger
        if len(output) > 4000:
            output = output[:2000] + "\n...[truncated]...\n" + output[-2000:]
        return {
            "kind": target["kind"],
            "cwd": target["cwd"],
            "cmd": " ".join(target["cmd"]),
            "status": "pass" if ok else "fail",
            "exitCode": proc.returncode,
            "elapsedMs": elapsed_ms,
            "output": output,
        }
    except FileNotFoundError as exc:
        return {
            "kind": target["kind"],
            "cwd": target["cwd"],
            "cmd": " ".join(target["cmd"]),
            "status": "skipped",
            "reason": f"command not found: {exc}",
        }
    except subprocess.TimeoutExpired:
        return {
            "kind": target["kind"],
            "cwd": target["cwd"],
            "cmd": " ".join(target["cmd"]),
            "status": "fail",
            "reason": f"timeout after {timeout}s",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test gate (S2-1)")
    parser.add_argument("--project-root", required=True, help="项目根目录")
    parser.add_argument("--timeout", type=int, default=600, help="单个 smoke 命令超时秒数")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"[smoke_test] project root not found: {root}", file=sys.stderr)
        return 2

    targets = detect_targets(root)
    if not targets:
        result = {
            "status": "skipped",
            "reason": "no smoke target detected (no pom.xml / build.gradle / package.json)",
            "projectRoot": str(root),
            "targets": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    results = [run_target(t, timeout=args.timeout) for t in targets]
    failed = [r for r in results if r["status"] == "fail"]

    summary = {
        "status": "fail" if failed else "pass",
        "projectRoot": str(root),
        "targetCount": len(targets),
        "passCount": sum(1 for r in results if r["status"] == "pass"),
        "failCount": len(failed),
        "skipCount": sum(1 for r in results if r["status"] == "skipped"),
        "targets": results,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
