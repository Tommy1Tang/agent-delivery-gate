#!/usr/bin/env python3
"""P7-2: Environment pre-condition validation before role dispatch.

Enforces the pinned toolchain baseline (JDK 17 / Node.js 22 / Maven 3 /
Python 3.12) on the dev machine, verifies the deployment-server PostgreSQL/Redis
instances are reachable (local PostgreSQL/Redis installs are forbidden by
references/environment-provisioning.md), and guards against dev configs
pointing at localhost databases. Outputs an env readiness report so retry
budget is not wasted on environment failures.

Exit code 0 = ready, 1 = not ready (auto-install per environment-provisioning.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# Timeout for subprocess checks (seconds).
CHECK_TIMEOUT = 15

# Deployment server hosting the shared PostgreSQL 16 / Redis instances.
DEFAULT_SERVER_IP = os.environ.get("DEPLOY_SERVER_IP", "")
PG_PORT = 5432
REDIS_PORT = 6379

# Pinned toolchain baseline. Version mismatch is treated the same as missing.
#   git    : major >= 2 (delivery workflow requires Gitea push / commits)
#   java   : major >= 17 (baseline install is JDK 17)
#   node   : major == 22
#   mvn    : major == 3 (Maven 4 is NOT acceptable)
#   python : exactly 3.12
TOOLCHAIN_BASELINE = "Git 2+ / JDK 17 / Node.js 22 / Maven 3 / Python 3.12"

# Patterns that must never appear as datasource/cache hosts in dev configs.
LOCAL_DB_PATTERN = re.compile(
    r"(localhost|127\.0\.0\.1)\s*:\s*(5432|6379)"
)


def _which(cmd: str) -> str | None:
    """Resolve a command to its full path (handles .cmd/.bat on Windows)."""
    return shutil.which(cmd)


def refresh_path_from_registry() -> None:
    """Align this process's PATH with what a fresh shell would see.

    Long-lived agent sessions inherit a stale PATH; tools installed since
    (or registered only in the registry, e.g. via winget/nvm) would be
    misreported as missing. Installers also register new env vars (e.g.
    NVM_HOME) referenced from PATH as unexpanded %VARS%, so import every
    registry env var this process is missing BEFORE expanding PATH.
    """
    if os.name != "nt":
        return
    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, "Environment"),
        ]
        paths: list[str] = []
        for hive, subkey in keys:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    i = 0
                    while True:
                        try:
                            name, value, _vtype = winreg.EnumValue(key, i)
                        except OSError:
                            break
                        i += 1
                        if not isinstance(value, str):
                            continue
                        if name.upper() == "PATH":
                            paths.append(value)
                        elif name.upper() not in (n.upper() for n in os.environ):
                            os.environ[name] = os.path.expandvars(value)
            except OSError:
                continue
        merged = ";".join(os.path.expandvars(p) for p in paths if p)
        os.environ["PATH"] = merged + ";" + os.environ.get("PATH", "")
    except OSError:
        pass


def _run_cmd(cmd: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Run a command and return (success, combined output)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=CHECK_TIMEOUT, cwd=cwd
        )
        out = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, out[:400]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, str(e)[:200]


def _version_output(cmd: str, args: list[str]) -> str | None:
    """Run `<cmd> <args>` via its resolved path and return raw output, or None."""
    path = _which(cmd)
    if not path:
        return None
    ok, out = _run_cmd([path] + args)
    return out if ok or out else None


def _check_git() -> dict:
    """Check Git presence (major >= 2). The delivery workflow depends on it."""
    issues: list[str] = []
    info: dict[str, str] = {}

    out = _version_output("git", ["--version"])
    if out is None:
        issues.append("git not found in PATH -- install Git (winget install Git.Git)")
    else:
        m = re.search(r"git version (\d+)\.(\d+)", out)
        if m:
            info["gitVersion"] = f"{m.group(1)}.{m.group(2)}"
            if int(m.group(1)) < 2:
                issues.append(f"git {info['gitVersion']} is below the 2.x baseline -- install a current Git.Git")
        else:
            issues.append("git found but version unparseable -- verify Git 2.x manually")

    return {"tool": "git", "issues": issues, "info": info}


def _check_java() -> dict:
    """Check JDK presence and major version >= 17."""
    issues: list[str] = []
    info: dict[str, str] = {}

    out = _version_output("java", ["-version"])
    if out is None:
        issues.append("java not found in PATH -- install JDK 17 (winget install Microsoft.OpenJDK.17)")
    else:
        # e.g. openjdk version "17.0.10" / java version "1.8.0_391"
        m = re.search(r'version "(\d+)(?:\.(\d+))?', out)
        if m:
            major = int(m.group(1))
            if major == 1 and m.group(2):  # legacy 1.8 style
                major = int(m.group(2))
            info["javaVersion"] = m.group(0).replace('version "', "")
            if major < 17:
                issues.append(
                    f"java major version {major} does not satisfy JDK 17 baseline -- "
                    "install JDK 17 alongside (do NOT uninstall existing), set JAVA_HOME per session"
                )
        else:
            issues.append("java found but version unparseable -- verify JDK 17 manually")

    return {"tool": "java", "issues": issues, "info": info}


def _check_node(project_root: Path) -> dict:
    """Check Node.js presence and major version == 22."""
    issues: list[str] = []
    info: dict[str, str] = {}

    out = _version_output("node", ["--version"])
    if out is None:
        issues.append("node not found in PATH -- install Node.js 22 (nvm install 22 / winget, see environment-provisioning.md)")
    else:
        m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", out)
        if m:
            info["nodeVersion"] = m.group(0)
            if int(m.group(1)) != 22:
                issues.append(
                    f"node version {m.group(0)} does not satisfy Node.js 22 baseline -- "
                    "use nvm-windows to install/switch to 22 (do NOT uninstall existing)"
                )
        else:
            issues.append("node found but version unparseable -- verify Node.js 22 manually")

    if not _which("npm"):
        issues.append("npm not found in PATH")

    # node_modules hint when a package.json already exists
    for pkg in [project_root / "package.json", project_root / "frontend" / "package.json"]:
        if pkg.exists() and not (pkg.parent / "node_modules").exists():
            issues.append(
                f"package.json exists at {pkg.parent.name}/ but node_modules absent -- run 'npm install'"
            )

    return {"tool": "node", "issues": issues, "info": info}


def _check_maven(project_root: Path) -> dict:
    """Check Maven presence and major version == 3 (Maven 4 not acceptable)."""
    issues: list[str] = []
    info: dict[str, str] = {}

    out = _version_output("mvn", ["--version"])
    if out is None:
        # A project-local wrapper still satisfies the build requirement.
        has_wrapper = any(
            (project_root / p).exists()
            for p in ["mvnw", "mvnw.cmd", "backend/mvnw", "backend/mvnw.cmd"]
        )
        if has_wrapper:
            info["maven"] = "mvn absent but Maven wrapper (mvnw) present"
        else:
            issues.append("mvn not found in PATH -- install Maven 3 (winget install Apache.Maven, verify major == 3)")
    else:
        m = re.search(r"Apache Maven (\d+)\.(\d+)\.(\d+)", out)
        if m:
            info["mavenVersion"] = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            if int(m.group(1)) != 3:
                issues.append(
                    f"Maven {info['mavenVersion']} does not satisfy Maven 3 baseline -- "
                    "install Maven 3.9.x alongside and put it first in PATH"
                )
        else:
            issues.append("mvn found but version unparseable -- verify Maven 3 manually")

    return {"tool": "maven", "issues": issues, "info": info}


def _check_python(project_root: Path) -> dict:
    """Check Python 3.12 availability (default interpreter or `py -3.12`)."""
    issues: list[str] = []
    info: dict[str, str] = {}

    found_312 = False
    for cmd, args in [("python", ["--version"]), ("python3", ["--version"])]:
        out = _version_output(cmd, args)
        if out:
            m = re.search(r"Python (\d+)\.(\d+)\.(\d+)", out)
            if m:
                info.setdefault("pythonVersion", m.group(0))
                if (int(m.group(1)), int(m.group(2))) == (3, 12):
                    found_312 = True
            break
    else:
        out = None

    # Windows launcher may expose 3.12 even when default python is another version.
    if not found_312:
        py_out = _version_output("py", ["-3.12", "--version"])
        if py_out and "3.12" in py_out:
            found_312 = True
            info["python312Via"] = "py -3.12"

    if out is None and not found_312:
        issues.append("python/python3 not found in PATH -- install Python 3.12 (winget install Python.Python.3.12)")
    elif not found_312:
        issues.append(
            f"Python 3.12 unavailable (default is {info.get('pythonVersion', 'unknown')}) -- "
            "install Python 3.12 alongside; create venvs with 'py -3.12 -m venv .venv'"
        )

    # venv hint when a Python project already exists
    if (project_root / "requirements.txt").exists() or (project_root / "pyproject.toml").exists():
        if not (project_root / ".venv").exists() and not (project_root / "venv").exists():
            issues.append("Python project detected but no .venv/venv directory -- create with 'py -3.12 -m venv .venv'")

    return {"tool": "python", "issues": issues, "info": info}


def _tcp_reachable(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _check_remote_services(server_ip: str) -> dict:
    """Verify deployment-server PostgreSQL (required) and Redis (advisory).

    Local PostgreSQL/Redis installs are forbidden -- dev machines must use the
    deployment server instances (environment-provisioning.md red line).
    """
    issues: list[str] = []
    info: dict[str, str] = {"serverIp": server_ip}

    if _tcp_reachable(server_ip, PG_PORT):
        info["postgresql"] = f"reachable at {server_ip}:{PG_PORT}"
    else:
        issues.append(
            f"deployment-server PostgreSQL not reachable at {server_ip}:{PG_PORT} -- "
            "do NOT install PostgreSQL locally; run scripts/preflight_server_check.py and follow its guidance"
        )

    if _tcp_reachable(server_ip, REDIS_PORT):
        info["redis"] = f"reachable at {server_ip}:{REDIS_PORT}"
    else:
        # advisory: recorded as warning, never fixed by a local install
        issues.append(
            f"[advisory] deployment-server Redis not reachable at {server_ip}:{REDIS_PORT} -- "
            "do NOT install Redis locally; check the server container"
        )

    return {"tool": "remote-services", "issues": issues, "info": info}


def _check_local_db_guard(project_root: Path) -> dict:
    """Guard: dev configs must not point at localhost PostgreSQL/Redis, and warn
    if local PostgreSQL/Redis binaries exist on the dev machine."""
    issues: list[str] = []
    info: dict[str, str] = {}

    config_globs = [
        "**/application*.yml", "**/application*.yaml", "**/application*.properties",
        ".env", ".env.*", "frontend/.env", "frontend/.env.*", "backend/.env",
    ]
    offenders: list[str] = []
    for pattern in config_globs:
        for f in project_root.glob(pattern):
            if any(part in ("node_modules", "target", ".git", "dist") for part in f.parts):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if LOCAL_DB_PATTERN.search(text):
                offenders.append(str(f.relative_to(project_root)))
    if offenders:
        issues.append(
            "dev config points at localhost PostgreSQL/Redis (forbidden -- must use deployment server): "
            + ", ".join(sorted(set(offenders))[:5])
        )

    # Local server binaries present: advisory only (never uninstall user software).
    local_bins = [b for b in ("postgres", "redis-server") if _which(b)]
    if local_bins:
        issues.append(
            f"[advisory] local {'/'.join(local_bins)} found on dev machine -- "
            "must not be used by this project; keep configs on the deployment server instances"
        )

    return {"tool": "local-db-guard", "issues": issues, "info": info}


def _check_db_migrations(project_root: Path, stack_snapshot: dict) -> dict:
    """Check declared migration dirs exist (schema managed against server DB)."""
    issues: list[str] = []
    info: dict[str, str] = {}

    infra = stack_snapshot.get("infrastructure", {})
    db_type = infra.get("database")
    if db_type:
        info["detectedDb"] = str(db_type)

    migration_dirs = stack_snapshot.get("migrationDirs", [])
    if migration_dirs:
        existing = [d for d in migration_dirs if (project_root / d).exists()]
        if not existing:
            issues.append(f"Migration dirs declared ({migration_dirs}) but none exist on disk")
        info["migrationDirs"] = existing

    return {"tool": "database", "issues": issues, "info": info}


def preflight_env_check(
    project_root: Path,
    stack_snapshot: dict | None = None,
    server_ip: str = DEFAULT_SERVER_IP,
    skip_remote: bool = False,
) -> dict:
    """Run all environment pre-condition checks.

    The four pinned toolchains are ALWAYS checked (tech.md fixes the stack, so
    a brand-new project with no pom.xml/package.json still requires them).
    """
    if stack_snapshot is None:
        stack_snapshot = {}

    checks: list[dict] = [
        _check_git(),
        _check_java(),
        _check_node(project_root),
        _check_maven(project_root),
        _check_python(project_root),
        _check_local_db_guard(project_root),
        _check_db_migrations(project_root, stack_snapshot),
    ]
    if not skip_remote:
        checks.append(_check_remote_services(server_ip))

    all_issues: list[str] = []
    for check in checks:
        for issue in check.get("issues", []):
            all_issues.append(f"[{check['tool']}] {issue}")

    # Explicit classification: advisory-tagged issues and setup hints are
    # warnings; everything else (missing tool, version mismatch, localhost DB
    # config, unreachable server PostgreSQL) blocks dispatch.
    warnings = [
        i for i in all_issues
        if "[advisory]" in i
        or "node_modules absent" in i
        or "no .venv/venv" in i
        or "Migration dirs declared" in i
    ]
    blocking = [i for i in all_issues if i not in warnings]

    status = "ready" if not blocking else "not-ready"

    return {
        "status": status,
        "baseline": TOOLCHAIN_BASELINE,
        "serverIp": server_ip,
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
        "summary": f"{len(checks)} checks run, {len(blocking)} blocking, {len(warnings)} warnings",
        "nextAction": (
            "dispatch roles" if not blocking else
            "auto-install per references/environment-provisioning.md (run scripts/provision_env.py); "
            "NEVER install PostgreSQL/Redis locally; NEVER change the tech stack"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Path to the project root")
    parser.add_argument("--stack-snapshot", help="Path to stack snapshot JSON (from detect_stack)")
    parser.add_argument("--server-ip", default=DEFAULT_SERVER_IP,
                        help="Deployment server IP hosting PostgreSQL/Redis")
    parser.add_argument("--skip-remote", action="store_true",
                        help="Skip deployment-server reachability checks (offline unit testing only)")
    parser.add_argument("--no-refresh-path", action="store_true",
                        help="Check the current session PATH as-is instead of a fresh-shell view")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    if not args.no_refresh_path:
        refresh_path_from_registry()

    project_root = Path(args.project_root).resolve()
    stack_snapshot = {}
    if args.stack_snapshot:
        try:
            stack_snapshot = json.loads(Path(args.stack_snapshot).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    report = preflight_env_check(
        project_root, stack_snapshot, server_ip=args.server_ip, skip_remote=args.skip_remote
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Environment: {report['status'].upper()}  (baseline: {report['baseline']})")
        print(f"  {report['summary']}")
        if report["blocking"]:
            print("\n  BLOCKING:")
            for b in report["blocking"]:
                print(f"    x {b}")
        if report["warnings"]:
            print("\n  WARNINGS:")
            for w in report["warnings"]:
                print(f"    ! {w}")
        print(f"\n  NEXT: {report['nextAction']}")
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
