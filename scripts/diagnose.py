#!/usr/bin/env python3
"""一键环境诊断脚本 — 面向完全不懂技术的小白用户

检查开发环境的所有关键环节，输出通俗易懂的中文诊断报告。
每个问题都给出具体的"解决方法"，不使用技术术语。

Usage:
    python scripts/diagnose.py
    python scripts/diagnose.py --project-root d:/dev/my-project
    python scripts/diagnose.py --fix  # 尝试自动修复可修复的问题
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_SERVER_IP = os.environ.get("DEPLOY_SERVER_IP", "")

# 诊断结果等级
PASS = "✅"
WARN = "⚠️"
FAIL = "❌"
INFO = "ℹ️"


class DiagnosticResult:
    def __init__(self, name: str, status: str, message: str, fix: str = ""):
        self.name = name
        self.status = status
        self.message = message
        self.fix = fix


def check_network(server_ip: str) -> list[DiagnosticResult]:
    """检查网络连通性"""
    results = []

    # 基础网络
    try:
        sock = socket.create_connection((server_ip, 3000), timeout=5)
        sock.close()
        results.append(DiagnosticResult(
            "网络连接", PASS, f"可以连接到服务器 {server_ip}"
        ))
    except (socket.timeout, ConnectionRefusedError, OSError):
        results.append(DiagnosticResult(
            "网络连接", FAIL,
            f"无法连接到服务器 {server_ip}",
            "请检查：\n"
            "  1. 电脑是否连接了公司内网（WiFi 或网线）\n"
            "  2. 如果在家办公，VPN 是否已连接\n"
            "  3. 请在浏览器中试试能否打开代码托管地址(由 DEPLOY_SERVER_IP 配置)"
        ))
        return results

    # Gitea
    try:
        urlopen(f"http://{server_ip}:3000/api/v1/version", timeout=5)
        results.append(DiagnosticResult("Gitea 代码托管", PASS, "服务正常运行"))
    except Exception:
        results.append(DiagnosticResult(
            "Gitea 代码托管", FAIL, "服务未响应",
            "请联系管理员检查服务器上 Gitea 容器是否正常运行"
        ))

    # Jenkins
    try:
        urlopen(f"http://{server_ip}:8090/login", timeout=5)
        results.append(DiagnosticResult("Jenkins 构建服务", PASS, "服务正常运行"))
    except Exception:
        results.append(DiagnosticResult(
            "Jenkins 构建服务", FAIL, "服务未响应",
            "请联系管理员检查服务器上 Jenkins 容器是否正常运行"
        ))

    # PostgreSQL
    try:
        sock = socket.create_connection((server_ip, 5432), timeout=5)
        sock.close()
        results.append(DiagnosticResult("PostgreSQL 数据库", PASS, "端口可达"))
    except Exception:
        results.append(DiagnosticResult(
            "PostgreSQL 数据库", WARN, "5432 端口不可达",
            "PostgreSQL 可能限制了远程访问。如果您只是部署（不在本地调试数据库），这不影响使用"
        ))

    return results


def check_dev_tools() -> list[DiagnosticResult]:
    """检查开发工具安装情况"""
    results = []

    tools = [
        ("Git", "git", ["--version"], "版本管理工具"),
        ("Python", "python", ["--version"], "脚本运行环境"),
        ("Node.js", "node", ["-v"], "前端构建工具"),
        ("Java (JDK)", "java", ["-version"], "后端编译工具"),
        ("Maven", "mvn", ["-version"], "Java 构建工具"),
    ]

    for name, cmd, args, desc in tools:
        if shutil.which(cmd):
            try:
                result = subprocess.run([cmd] + args, capture_output=True, text=True, timeout=10)
                version = (result.stdout or result.stderr).strip().split("\n")[0][:60]
                results.append(DiagnosticResult(f"{name} ({desc})", PASS, version))
            except Exception:
                results.append(DiagnosticResult(f"{name} ({desc})", WARN, "已安装但无法获取版本"))
        else:
            results.append(DiagnosticResult(
                f"{name} ({desc})", WARN,
                "未安装",
                f"运行 quick-start.bat 可自动安装，或手动安装后重新打开终端"
            ))

    return results


def check_git_config(server_ip: str) -> list[DiagnosticResult]:
    """检查 Git 配置"""
    results = []

    if not shutil.which("git"):
        results.append(DiagnosticResult("Git 配置", FAIL, "Git 未安装", "请先安装 Git"))
        return results

    # 检查 credential helper
    try:
        result = subprocess.run(["git", "config", "--global", "credential.helper"],
                                capture_output=True, text=True, timeout=5)
        helper = result.stdout.strip()
        if helper:
            results.append(DiagnosticResult("Git 凭据管理", PASS, f"使用 {helper}"))
        else:
            results.append(DiagnosticResult(
                "Git 凭据管理", WARN, "未配置",
                "运行 quick-start.bat 可自动配置，配置后推送代码无需输入密码"
            ))
    except Exception:
        pass

    # 检查默认分支
    try:
        result = subprocess.run(["git", "config", "--global", "init.defaultBranch"],
                                capture_output=True, text=True, timeout=5)
        branch = result.stdout.strip()
        if branch == "main":
            results.append(DiagnosticResult("Git 默认分支", PASS, "main"))
        else:
            results.append(DiagnosticResult(
                "Git 默认分支", WARN, f"当前为 '{branch or 'master'}'，建议设为 'main'",
                "运行 quick-start.bat 可自动配置"
            ))
    except Exception:
        pass

    return results


def check_project(project_root: Path, server_ip: str) -> list[DiagnosticResult]:
    """检查项目配置"""
    results = []

    if not project_root or not project_root.exists():
        results.append(DiagnosticResult("项目目录", INFO, "未指定项目路径，跳过项目检查"))
        return results

    # .env 文件
    env_file = project_root / ".env"
    if env_file.exists():
        results.append(DiagnosticResult("项目配置 (.env)", PASS, "已存在"))
    else:
        results.append(DiagnosticResult(
            "项目配置 (.env)", WARN, "不存在",
            "首次执行开发任务时会自动生成，无需手动创建"
        ))

    # .gitignore 包含 .env
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8", errors="ignore")
        if ".env" in content:
            results.append(DiagnosticResult("安全检查 (.gitignore)", PASS, ".env 已被排除"))
        else:
            results.append(DiagnosticResult(
                "安全检查 (.gitignore)", FAIL,
                ".env 未被排除，密码可能被提交到代码仓库！",
                "请在 .gitignore 文件中添加一行: .env"
            ))
    
    # Git remote
    if (project_root / ".git").exists():
        try:
            result = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True,
                                    cwd=str(project_root), timeout=5)
            if server_ip in result.stdout:
                results.append(DiagnosticResult("Git 远程仓库", PASS, "已配置指向 Gitea"))
            elif result.stdout.strip():
                results.append(DiagnosticResult("Git 远程仓库", WARN, "已配置但未指向 Gitea",
                    "首次部署时会自动配置"))
            else:
                results.append(DiagnosticResult("Git 远程仓库", INFO, "未配置",
                    "首次部署时会自动配置"))
        except Exception:
            pass

    # Jenkinsfile
    if (project_root / "Jenkinsfile").exists():
        results.append(DiagnosticResult("CI/CD 配置 (Jenkinsfile)", PASS, "已存在"))
    else:
        results.append(DiagnosticResult(
            "CI/CD 配置 (Jenkinsfile)", INFO, "不存在",
            "首次部署时会自动生成，无需手动创建"
        ))

    return results


def print_report(all_results: dict[str, list[DiagnosticResult]]):
    """打印诊断报告"""
    print("")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║           开发环境一键诊断报告                            ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print("")

    total_issues = 0

    for category, results in all_results.items():
        print(f"  【{category}】")
        for r in results:
            print(f"    {r.status} {r.name}: {r.message}")
            if r.status in (FAIL, WARN) and r.fix:
                total_issues += 1
        print("")

    # 需要处理的问题汇总
    issues = []
    for results in all_results.values():
        for r in results:
            if r.status == FAIL and r.fix:
                issues.append(r)

    warnings = []
    for results in all_results.values():
        for r in results:
            if r.status == WARN and r.fix:
                warnings.append(r)

    if issues:
        print("  ═══════════════════════════════════════════")
        print("  ⛔ 必须解决的问题：")
        print("  ═══════════════════════════════════════════")
        for i, r in enumerate(issues, 1):
            print(f"\n  问题 {i}: {r.name}")
            print(f"  现象: {r.message}")
            print(f"  解决方法:")
            for line in r.fix.split("\n"):
                print(f"    {line}")
        print("")

    if warnings:
        print("  ───────────────────────────────────────────")
        print("  ⚠️  建议处理（不影响核心功能）：")
        print("  ───────────────────────────────────────────")
        for r in warnings:
            print(f"    • {r.name}: {r.fix.split(chr(10))[0]}")
        print("")

    if not issues and not warnings:
        print("  🎉 恭喜！开发环境一切正常，可以开始使用了！")
        print("")
        print("  使用方式：")
        print("    • 对 Qoder 说你想做什么项目即可")
        print("    • 开发完成后说「部署到生产环境」即可自动上线")
    elif not issues:
        print("  ✅ 核心环境正常，可以正常使用")
    
    print("")


def main():
    parser = argparse.ArgumentParser(description="开发环境一键诊断")
    parser.add_argument("--server-ip", default=DEFAULT_SERVER_IP, help="服务器IP")
    parser.add_argument("--project-root", default=None, help="项目根目录路径")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else None

    all_results = {
        "网络与服务器": check_network(args.server_ip),
        "开发工具": check_dev_tools(),
        "Git 配置": check_git_config(args.server_ip),
    }

    if project_root:
        all_results["项目状态"] = check_project(project_root, args.server_ip)

    if args.json:
        output = {}
        for cat, results in all_results.items():
            output[cat] = [{"name": r.name, "status": r.status, "message": r.message, "fix": r.fix}
                          for r in results]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_report(all_results)


if __name__ == "__main__":
    main()
