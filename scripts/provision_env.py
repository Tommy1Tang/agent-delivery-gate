#!/usr/bin/env python3
"""Auto-installer for the pinned dev toolchain baseline (Windows-first).

Companion to scripts/preflight_env_check.py and
references/environment-provisioning.md. Detects which of the four pinned
toolchains (JDK 17 / Node.js 22 / Maven 3 / Python 3.12) are missing or
version-mismatched, installs them silently via winget (nvm-windows for Node
when another Node version already exists), refreshes PATH from the registry,
re-verifies, and emits a JSON provisioning report for the evidence ledger
(`envProvisioning` field).

HARD RULE: PostgreSQL 16 and Redis are NEVER installed on the dev machine (neither
native nor local Docker). Dev machines connect to the deployment-server
instances. This script refuses any such request.

When winget is unavailable (LTSC/Server/group policy), it automatically
switches to direct official downloads (python.org / git-for-windows /
aka.ms JDK / nodejs.org / archive.apache.org) — zips are extracted under
%USERPROFILE%\\tools and registered on the user PATH.

Usage:
    python scripts/provision_env.py [--dry-run] [--report-out report.json]

Exit code 0 = all toolchains verified ready; 1 = at least one toolchain still
failing after retries (delivery must halt: deliveryStatus = halted-pending-user).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

# Import version checks from the preflight script (same directory).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preflight_env_check import (  # noqa: E402
    _check_git, _check_java, _check_maven, _check_node, _check_python, _which,
    refresh_path_from_registry,
)

INSTALL_TIMEOUT = 900  # seconds per install attempt
MAX_RETRIES = 3
WINGET_SILENT = ["--silent", "--accept-package-agreements", "--accept-source-agreements"]

# Toolchains this script will never install. Requests must be routed to the
# deployment server instead (environment-provisioning.md red line).
FORBIDDEN_LOCAL = {"postgres", "postgresql", "pg_ctl", "redis", "redis-server"}

# Fallback when winget is unavailable (Windows LTSC/Server, group policy):
# download official installers/zips directly. Only needs network access.
TOOLS_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "tools"
DIRECT_INSTALLERS = {
    "git": {
        "url": "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe",
        "kind": "exe",
        "args": ["/VERYSILENT", "/NORESTART", "/SP-"],
    },
    "java": {
        "url": "https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.zip",
        "kind": "zip",
        "bin_subdir": "bin",
        "set_home": "JAVA_HOME",
    },
    "node": {
        "url": "https://nodejs.org/dist/v22.20.0/node-v22.20.0-win-x64.zip",
        "kind": "zip",
        "bin_subdir": "",
    },
    "maven": {
        "url": "https://archive.apache.org/dist/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.zip",
        "kind": "zip",
        "bin_subdir": "bin",
    },
    "python": {
        "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe",
        "kind": "exe",
        "args": ["/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0"],
    },
}


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "provision-env/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _add_to_user_path(entry: str, set_var: tuple | None = None) -> None:
    """Persist a PATH entry (and optional env var like JAVA_HOME) in
    HKCU\\Environment, and make both visible to this process immediately."""
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                current, vtype = winreg.QueryValueEx(key, "Path")
            except OSError:
                current, vtype = "", winreg.REG_EXPAND_SZ
            parts = [p for p in current.split(";") if p]
            if entry.lower() not in (p.lower() for p in parts):
                winreg.SetValueEx(key, "Path", 0, vtype or winreg.REG_EXPAND_SZ,
                                  ";".join(parts + [entry]))
            if set_var:
                winreg.SetValueEx(key, set_var[0], 0, winreg.REG_SZ, set_var[1])
    if set_var:
        os.environ[set_var[0]] = set_var[1]
    os.environ["PATH"] = entry + ";" + os.environ.get("PATH", "")


def _direct_install(tool: str) -> tuple[bool, str]:
    """Install a toolchain without any package manager: download the official
    installer/zip, run silently or extract under %USERPROFILE%\\tools."""
    spec = DIRECT_INSTALLERS.get(tool)
    if not spec:
        return False, f"no direct installer defined for {tool}"
    log: list[str] = [f"direct-download {spec['url']}"]
    try:
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / Path(spec["url"].split("?")[0]).name
            _download(spec["url"], pkg)
            if spec["kind"] == "exe":
                ok, out = _run([str(pkg)] + list(spec.get("args", [])))
                log.append(out[-200:] if out else f"installer exit ok={ok}")
                return ok, "\n".join(log)
            # zip: extract and register on the user PATH
            TOOLS_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(pkg) as zf:
                tops = {n.split("/")[0] for n in zf.namelist() if n.strip("/")}
                zf.extractall(TOOLS_DIR)
            top_dir = TOOLS_DIR / sorted(tops)[0]
            bin_dir = top_dir / spec["bin_subdir"] if spec.get("bin_subdir") else top_dir
            set_home = (spec["set_home"], str(top_dir)) if spec.get("set_home") else None
            _add_to_user_path(str(bin_dir), set_home)
            log.append(f"extracted to {top_dir}; user PATH += {bin_dir}")
            return True, "\n".join(log)
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        return False, "\n".join(log + [f"FAILED: {str(e)[:300]}"])


def _run(cmd: list[str], timeout: int = INSTALL_TIMEOUT) -> tuple[bool, str]:
    try:
        # winget emits UTF-8 regardless of console codepage; never let a
        # GBK-console default crash the reader threads.
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        out = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, out[-1000:]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, str(e)[:300]


_python_user_scope_tried = False


def _python_install_commands() -> list[list[str]]:
    """Try user scope first (no UAC on fresh machines); later retry attempts
    fall back to default scope for environments where user scope is
    unsupported. Mirrors the fallback in bootstrap_env.ps1."""
    global _python_user_scope_tried
    if not _python_user_scope_tried:
        _python_user_scope_tried = True
        return [["winget", "install", "Python.Python.3.12", "--scope", "user"] + WINGET_SILENT]
    return [["winget", "install", "Python.Python.3.12"] + WINGET_SILENT]


def _node_install_commands() -> list[list[str]]:
    """Prefer nvm when any Node already exists (never uninstall/overwrite)."""
    if _which("nvm"):
        return [["nvm", "install", "22"], ["nvm", "use", "22"]]
    if _which("node"):
        # Another Node version is installed: isolate via nvm-windows.
        return [
            ["winget", "install", "CoreyButler.NVMforWindows"] + WINGET_SILENT,
            ["nvm", "install", "22"],
            ["nvm", "use", "22"],
        ]
    return [["winget", "install", "OpenJS.NodeJS.LTS", "--version", "22.20.0"] + WINGET_SILENT]


# tool key -> (display name, check fn returning {"issues": [...]}, install command builder)
TOOLCHAINS = {
    "git": (
        "Git 2+",
        lambda: _check_git(),
        lambda: [["winget", "install", "Git.Git"] + WINGET_SILENT],
    ),
    "java": (
        "JDK 17",
        lambda: _check_java(),
        lambda: [["winget", "install", "Microsoft.OpenJDK.17"] + WINGET_SILENT],
    ),
    "node": (
        "Node.js 22",
        lambda: _check_node(Path(".")),
        _node_install_commands,
    ),
    "maven": (
        "Maven 3",
        lambda: _check_maven(Path(".")),
        lambda: [["winget", "install", "Apache.Maven"] + WINGET_SILENT],
    ),
    "python": (
        "Python 3.12",
        lambda: _check_python(Path(".")),
        _python_install_commands,
    ),
}


def _version_issues(check_result: dict) -> list[str]:
    """Only tool-availability/version issues matter here, not project hints."""
    hints = ("node_modules absent", "no .venv/venv")
    return [i for i in check_result.get("issues", []) if not any(h in i for h in hints)]


def provision(dry_run: bool = False) -> dict:
    global _python_user_scope_tried
    _python_user_scope_tried = False

    # Tools installed in an earlier session may exist only in the registry
    # PATH, not this process's PATH — refresh once before detecting, so we
    # don't "install" (or dry-run-plan) something that is already there.
    refresh_path_from_registry()

    report: dict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dryRun": dry_run,
        "forbiddenLocalInstalls": sorted(FORBIDDEN_LOCAL),
        "tools": [],
        "allReady": False,
    }

    # Install mode: winget when available, otherwise direct official
    # downloads (Windows LTSC/Server or group-policy-blocked winget).
    mode = "winget"
    if os.name == "nt" and not _which("winget"):
        mode = "direct"
    report["installMode"] = mode

    for key, (display, check_fn, cmds_fn) in TOOLCHAINS.items():
        entry: dict = {"tool": key, "baseline": display, "actions": [], "status": "ready"}
        issues = _version_issues(check_fn())
        if not issues:
            entry["detail"] = "already satisfies baseline"
            report["tools"].append(entry)
            continue

        entry["detectedIssues"] = issues
        if dry_run:
            entry["status"] = "would-install"
            if mode == "direct":
                entry["plannedCommands"] = [f"direct-download {DIRECT_INSTALLERS[key]['url']}"]
            else:
                entry["plannedCommands"] = [" ".join(c) for c in cmds_fn()]
            report["tools"].append(entry)
            continue

        entry["status"] = "failed"
        for attempt in range(1, MAX_RETRIES + 1):
            attempt_log: dict = {"attempt": attempt, "commands": []}
            if mode == "direct":
                ok, out = _direct_install(key)
                attempt_log["commands"].append(
                    {"cmd": f"direct-install {key}", "ok": ok, "output": out[-300:]}
                )
                all_ok = ok
                entry["actions"].append(attempt_log)
                refresh_path_from_registry()
                if not _version_issues(check_fn()):
                    entry["status"] = "installed"
                    break
                if not all_ok and attempt == MAX_RETRIES:
                    break
                continue
            all_ok = True
            for cmd in cmds_fn():
                # Safety net: never let a command install PostgreSQL/Redis locally.
                if any(tok.lower() in FORBIDDEN_LOCAL or "postgres" in tok.lower() or "redis" in tok.lower()
                       for tok in cmd):
                    attempt_log["commands"].append(
                        {"cmd": " ".join(cmd), "ok": False, "note": "REFUSED — local PostgreSQL/Redis install forbidden"}
                    )
                    all_ok = False
                    continue
                ok, out = _run(cmd)
                attempt_log["commands"].append({"cmd": " ".join(cmd), "ok": ok, "output": out[-300:]})
                all_ok = all_ok and ok
            entry["actions"].append(attempt_log)

            refresh_path_from_registry()
            if not _version_issues(check_fn()):
                entry["status"] = "installed"
                break
            if not all_ok and attempt == MAX_RETRIES:
                break

        report["tools"].append(entry)

    report["allReady"] = all(t["status"] in ("ready", "installed") for t in report["tools"])
    if not report["allReady"] and not dry_run:
        report["nextAction"] = (
            "set deliveryStatus = halted-pending-user and ask the user; "
            "changing the tech stack remains forbidden"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect and print planned install commands without executing")
    parser.add_argument("--report-out", help="Write the JSON provisioning report to this path")
    args = parser.parse_args()

    report = provision(dry_run=args.dry_run)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report_out:
        Path(args.report_out).write_text(text, encoding="utf-8")

    if "fatal" in report:
        return 1
    return 0 if report["allReady"] or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
