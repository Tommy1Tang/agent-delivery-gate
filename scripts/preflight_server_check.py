#!/usr/bin/env python3
"""服务器基础设施可达性预检脚本

在开发流程启动前自动验证所配置的代码托管 / CI / 数据库 / 缓存服务是否可达、
服务是否正常运行。输出通俗易懂的中文诊断报告。

服务器地址从环境变量 `DEPLOY_SERVER_IP`(或 `--server-ip`)读取,不在代码中硬编码。

Usage:
    python scripts/preflight_server_check.py [--server-ip <host>]
    python scripts/preflight_server_check.py --json  # 机器可读输出
"""

from __future__ import annotations

import argparse
import os
import json
import socket
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_SERVER_IP = os.environ.get("DEPLOY_SERVER_IP", "")

# 服务检查清单
SERVICES = [
    {
        "name": "代码托管 (Git server)",
        "port": int(os.environ.get("GIT_SERVER_PORT", "3000")),
        "http_path": "/api/v1/version",
        "required": True,
        "help_if_down": "代码托管服务未启动。请联系管理员检查服务状态。",
    },
    {
        "name": "CI (自动构建)",
        "port": int(os.environ.get("CI_SERVER_PORT", "8090")),
        "http_path": "/login",
        "required": True,
        "help_if_down": "CI 构建服务未启动。请联系管理员检查服务状态。",
    },
    {
        "name": "PostgreSQL (数据库)",
        "port": int(os.environ.get("DB_PORT", "5432")),
        "http_path": None,  # TCP-only check
        "required": True,
        "help_if_down": "PostgreSQL 数据库不可达。可能是防火墙未放行 5432 端口，请联系管理员处理。",
    },
    {
        "name": "Redis (缓存)",
        "port": int(os.environ.get("REDIS_PORT", "6379")),
        "http_path": None,
        "required": False,
        "help_if_down": "Redis 缓存不可达。非致命问题，但可能影响应用性能。",
    },
]


def check_tcp_port(host: str, port: int, timeout: float = 5.0) -> tuple[bool, float]:
    """检测 TCP 端口是否可达，返回 (是否可达, 延迟ms)"""
    start = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        latency = (time.time() - start) * 1000
        return True, latency
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False, -1


def check_http_endpoint(host: str, port: int, path: str, timeout: float = 5.0) -> tuple[bool, int, str]:
    """检测 HTTP 端点是否返回 2xx/3xx，返回 (是否可达, HTTP状态码, 响应摘要)"""
    url = f"http://{host}:{port}{path}"
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", "preflight-check/1.0")
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read(200).decode("utf-8", errors="ignore")
            return True, resp.status, body[:100]
    except HTTPError as e:
        # 4xx/5xx 也算可达（服务运行中）
        return True, e.code, str(e.reason)[:100]
    except (URLError, OSError, socket.timeout):
        return False, 0, ""


def check_network_basic(host: str) -> tuple[bool, str]:
    """基础网络检测：DNS解析 + ping（通过 socket connect to any port）"""
    try:
        ip = socket.gethostbyname(host)
        return True, ip
    except socket.gaierror:
        return False, ""


def run_preflight(server_ip: str) -> dict:
    """执行全部预检，返回结构化结果"""
    results = {
        "server_ip": server_ip,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "network_reachable": False,
        "services": [],
        "all_required_pass": False,
        "all_pass": False,
        "summary": "",
        "user_actions": [],
    }

    # Step 1: 基础网络检测
    net_ok, resolved_ip = check_network_basic(server_ip)
    results["network_reachable"] = net_ok

    if not net_ok:
        results["summary"] = f"无法解析服务器地址 {server_ip}"
        results["user_actions"] = [
            f"请检查您的电脑是否连接到公司内网（WiFi 或网线）",
            f"如果使用 VPN，请确认 VPN 已连接",
            f"尝试在浏览器中访问 http://{server_ip}:3000 看是否能打开",
        ]
        return results

    # Step 2: 逐个检查服务
    required_pass = True
    all_pass = True

    for svc in SERVICES:
        check_result = {
            "name": svc["name"],
            "port": svc["port"],
            "required": svc["required"],
            "tcp_reachable": False,
            "http_ok": None,
            "latency_ms": -1,
            "status": "FAIL",
        }

        # TCP 检测
        tcp_ok, latency = check_tcp_port(server_ip, svc["port"])
        check_result["tcp_reachable"] = tcp_ok
        check_result["latency_ms"] = round(latency, 1) if latency > 0 else -1

        if not tcp_ok:
            check_result["status"] = "FAIL"
            check_result["help"] = svc["help_if_down"]
            if svc["required"]:
                required_pass = False
            all_pass = False
            results["services"].append(check_result)
            results["user_actions"].append(f"[{svc['name']}] {svc['help_if_down']}")
            continue

        # HTTP 检测（如果有 http_path）
        if svc["http_path"]:
            http_ok, status_code, body = check_http_endpoint(server_ip, svc["port"], svc["http_path"])
            check_result["http_ok"] = http_ok
            check_result["http_status"] = status_code
            if http_ok:
                check_result["status"] = "PASS"
            else:
                check_result["status"] = "WARN"
                check_result["help"] = f"端口可达但服务未正常响应，可能正在启动中"
                all_pass = False
        else:
            # 只做 TCP 检测的服务
            check_result["status"] = "PASS"

        results["services"].append(check_result)

    results["all_required_pass"] = required_pass
    results["all_pass"] = all_pass

    # 生成总结
    if all_pass:
        results["summary"] = "所有服务正常，可以开始开发！"
    elif required_pass:
        results["summary"] = "核心服务正常，部分可选服务异常（不影响开发）"
    else:
        results["summary"] = "部分核心服务不可用，请按下方提示处理后重试"

    return results


def print_human_report(results: dict):
    """输出面向小白用户的可读报告"""
    print("")
    print("=" * 60)
    print("  开发环境预检报告")
    print(f"  服务器：{results['server_ip']}")
    print(f"  检测时间：{results['timestamp']}")
    print("=" * 60)
    print("")

    # 网络状态
    if not results["network_reachable"]:
        print("  ❌ 网络不通：无法连接到服务器")
        print("")
        for action in results["user_actions"]:
            print(f"  💡 {action}")
        print("")
        print("=" * 60)
        return

    # 服务状态
    for svc in results["services"]:
        if svc["status"] == "PASS":
            latency = f" ({svc['latency_ms']}ms)" if svc["latency_ms"] > 0 else ""
            print(f"  ✅ {svc['name']}{latency}")
        elif svc["status"] == "WARN":
            print(f"  ⚠️  {svc['name']} — 可能正在启动")
        else:
            print(f"  ❌ {svc['name']} — 不可用")

    print("")
    print(f"  📋 结论：{results['summary']}")
    print("")

    if results["user_actions"]:
        print("  需要处理的问题：")
        for i, action in enumerate(results["user_actions"], 1):
            print(f"    {i}. {action}")
        print("")

    if results["all_required_pass"]:
        print("  ✅ 环境就绪，可以正常开发和部署")
    else:
        print("  ⛔ 环境未就绪，请先解决上述问题")

    print("")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="开发环境服务器预检")
    parser.add_argument("--server-ip", default=DEFAULT_SERVER_IP, help="服务器IP地址")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式（供脚本调用）")
    parser.add_argument("--strict", action="store_true", help="严格模式：任一必需服务失败则退出码=1")
    args = parser.parse_args()

    results = run_preflight(args.server_ip)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_human_report(results)

    if args.strict and not results["all_required_pass"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
