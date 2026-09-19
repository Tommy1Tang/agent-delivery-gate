#!/usr/bin/env python3
"""部署后健康监控脚本 — 检查所有已部署项目的运行状态

可由 Jenkins 定时任务或 cron 调度，周期性检查所有项目容器的健康状态。
发现异常时输出告警信息，并尝试自动重启故障容器。

Usage:
    DEPLOY_SERVER_IP=<host> python scripts/health_monitor.py
    python scripts/health_monitor.py --auto-restart  # 自动重启异常容器
    python scripts/health_monitor.py --json          # JSON 格式输出
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_SERVER_IP = os.environ.get("DEPLOY_SERVER_IP", "")


def get_deployed_projects(server_ip: str) -> list[dict]:
    """从 .deploy-ports 注册表获取已部署项目列表"""
    # 尝试从端口注册表读取
    registry_path = Path(__file__).parent / "port_registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            projects = []
            for slug, info in registry.get("projects", {}).items():
                projects.append({
                    "slug": slug,
                    "backend_port": info.get("backend_port", 8080),
                    "frontend_port": info.get("frontend_port", 3100),
                })
            return projects
        except (json.JSONDecodeError, IOError):
            pass
    return []


def check_project_health(server_ip: str, project: dict) -> dict:
    """检查单个项目的健康状态"""
    slug = project["slug"]
    backend_port = project["backend_port"]
    frontend_port = project["frontend_port"]

    result = {
        "slug": slug,
        "backend_port": backend_port,
        "frontend_port": frontend_port,
        "backend_status": "unknown",
        "frontend_status": "unknown",
        "backend_response_ms": -1,
        "frontend_response_ms": -1,
    }

    # 检查后端健康
    backend_endpoints = [
        f"http://{server_ip}:{backend_port}/actuator/health",
        f"http://{server_ip}:{backend_port}/health",
        f"http://{server_ip}:{backend_port}/api/health",
    ]

    for endpoint in backend_endpoints:
        start = time.time()
        try:
            req = Request(endpoint, method="GET")
            req.add_header("User-Agent", "health-monitor/1.0")
            with urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                latency = (time.time() - start) * 1000
                result["backend_status"] = "healthy"
                result["backend_response_ms"] = round(latency, 1)
                break
        except (HTTPError, URLError, OSError):
            continue

    if result["backend_status"] == "unknown":
        result["backend_status"] = "unhealthy"

    # 检查前端可达性
    start = time.time()
    try:
        req = Request(f"http://{server_ip}:{frontend_port}/", method="GET")
        with urlopen(req, timeout=10) as resp:
            latency = (time.time() - start) * 1000
            result["frontend_status"] = "healthy"
            result["frontend_response_ms"] = round(latency, 1)
    except (HTTPError, URLError, OSError):
        result["frontend_status"] = "unhealthy"

    return result


def attempt_restart(slug: str, server_ip: str) -> bool:
    """尝试通过 SSH 重启故障项目容器（需要服务器上有 docker compose）"""
    # 在服务器本地执行时直接 docker restart
    try:
        # 尝试重启后端容器
        result = subprocess.run(
            ["docker", "restart", f"{slug}-backend"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def print_human_report(results: list[dict], server_ip: str):
    """输出面向人类的状态报告"""
    print("")
    print("=" * 60)
    print("  项目健康状态监控报告")
    print(f"  服务器：{server_ip}")
    print(f"  检测时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print("")

    if not results:
        print("  暂无已部署项目")
        return

    healthy_count = 0
    unhealthy = []

    for r in results:
        be_icon = "✅" if r["backend_status"] == "healthy" else "❌"
        fe_icon = "✅" if r["frontend_status"] == "healthy" else "❌"

        be_latency = f" ({r['backend_response_ms']}ms)" if r["backend_response_ms"] > 0 else ""
        fe_latency = f" ({r['frontend_response_ms']}ms)" if r["frontend_response_ms"] > 0 else ""

        print(f"  📦 {r['slug']}")
        print(f"     后端 {be_icon} :{r['backend_port']}{be_latency}")
        print(f"     前端 {fe_icon} :{r['frontend_port']}{fe_latency}")
        print("")

        if r["backend_status"] == "healthy" and r["frontend_status"] == "healthy":
            healthy_count += 1
        else:
            unhealthy.append(r)

    print(f"  总计：{len(results)} 个项目，{healthy_count} 个正常，{len(unhealthy)} 个异常")

    if unhealthy:
        print("")
        print("  ⚠️ 异常项目：")
        for r in unhealthy:
            issues = []
            if r["backend_status"] != "healthy":
                issues.append("后端服务无响应")
            if r["frontend_status"] != "healthy":
                issues.append("前端无法访问")
            print(f"    • {r['slug']}: {', '.join(issues)}")
            print(f"      [解决方法] 在服务器上运行: docker restart {r['slug']}-backend")

    print("")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="项目健康状态监控")
    parser.add_argument("--server-ip", default=DEFAULT_SERVER_IP, help="服务器IP")
    parser.add_argument("--auto-restart", action="store_true", help="自动重启异常容器")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    projects = get_deployed_projects(args.server_ip)
    results = []

    for project in projects:
        result = check_project_health(args.server_ip, project)
        results.append(result)

        # 自动重启
        if args.auto_restart and result["backend_status"] == "unhealthy":
            print(f"  [AUTO-RESTART] 正在重启 {project['slug']}...")
            if attempt_restart(project["slug"], args.server_ip):
                print(f"  [OK] {project['slug']} 已重启")
                # 等待启动后重新检查
                time.sleep(15)
                result = check_project_health(args.server_ip, project)
                results[-1] = result

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_human_report(results, args.server_ip)

    # 退出码：有异常时返回 1
    unhealthy = [r for r in results if r["backend_status"] != "healthy"]
    sys.exit(1 if unhealthy else 0)


if __name__ == "__main__":
    main()
