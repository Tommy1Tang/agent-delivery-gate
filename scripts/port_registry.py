"""
Port Registry — 多项目端口自动分配与冲突检测

功能：
- 为每个新项目自动分配不冲突的后端/前端端口
- 维护端口注册表文件（/opt/infrastructure/.port-registry.json）
- 支持查询、释放端口

端口分配策略：
- 后端端口范围：8080-8180（最多支持 100 个项目）
- 前端端口范围：3100-3200（最多支持 100 个项目）
- 首个项目使用 8080/3100，后续递增

使用方式（可独立调用，或由部署流程调用）：
    from port_registry import allocate_ports, release_ports, get_project_ports
"""

import json
import os
from pathlib import Path
from typing import Tuple, Optional

# 默认注册表路径（服务器上）
DEFAULT_REGISTRY_PATH = "/opt/infrastructure/.port-registry.json"

# 端口范围配置
BACKEND_PORT_START = 8080
BACKEND_PORT_END = 8180
FRONTEND_PORT_START = 3100
FRONTEND_PORT_END = 3200


def _get_registry_path() -> Path:
    """Get the port registry file path."""
    env_path = os.environ.get("PORT_REGISTRY_PATH", DEFAULT_REGISTRY_PATH)
    return Path(env_path)


def _load_registry() -> dict:
    """Load the port registry from file."""
    path = _get_registry_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return {"projects": {}, "allocated_backend_ports": [], "allocated_frontend_ports": []}
    return {"projects": {}, "allocated_backend_ports": [], "allocated_frontend_ports": []}


def _save_registry(registry: dict) -> None:
    """Save the port registry to file."""
    path = _get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def allocate_ports(project_slug: str) -> Tuple[int, int]:
    """Allocate backend and frontend ports for a project.
    
    If the project already has allocated ports, return them.
    Otherwise, find the next available ports.
    
    Returns:
        Tuple of (backend_port, frontend_port)
    
    Raises:
        RuntimeError: If no ports are available (all 100 slots used)
    """
    registry = _load_registry()
    
    # 如果项目已有分配的端口，直接返回
    if project_slug in registry["projects"]:
        entry = registry["projects"][project_slug]
        print(f"  [Port] Project '{project_slug}' already allocated: backend={entry['backend_port']}, frontend={entry['frontend_port']}")
        return entry["backend_port"], entry["frontend_port"]
    
    # 查找下一个可用的后端端口
    allocated_backend = set(registry.get("allocated_backend_ports", []))
    backend_port = None
    for port in range(BACKEND_PORT_START, BACKEND_PORT_END + 1):
        if port not in allocated_backend:
            backend_port = port
            break
    
    if backend_port is None:
        raise RuntimeError(f"No available backend ports in range {BACKEND_PORT_START}-{BACKEND_PORT_END}. Maximum project capacity reached.")
    
    # 查找下一个可用的前端端口
    allocated_frontend = set(registry.get("allocated_frontend_ports", []))
    frontend_port = None
    for port in range(FRONTEND_PORT_START, FRONTEND_PORT_END + 1):
        if port not in allocated_frontend:
            frontend_port = port
            break
    
    if frontend_port is None:
        raise RuntimeError(f"No available frontend ports in range {FRONTEND_PORT_START}-{FRONTEND_PORT_END}. Maximum project capacity reached.")
    
    # 注册端口
    registry["projects"][project_slug] = {
        "backend_port": backend_port,
        "frontend_port": frontend_port,
    }
    registry.setdefault("allocated_backend_ports", []).append(backend_port)
    registry.setdefault("allocated_frontend_ports", []).append(frontend_port)
    
    _save_registry(registry)
    
    print(f"  [Port] Allocated for '{project_slug}': backend={backend_port}, frontend={frontend_port}")
    return backend_port, frontend_port


def release_ports(project_slug: str) -> bool:
    """Release ports allocated to a project.
    
    Returns True if ports were released, False if project not found.
    """
    registry = _load_registry()
    
    if project_slug not in registry["projects"]:
        return False
    
    entry = registry["projects"].pop(project_slug)
    
    backend_ports = registry.get("allocated_backend_ports", [])
    frontend_ports = registry.get("allocated_frontend_ports", [])
    
    if entry["backend_port"] in backend_ports:
        backend_ports.remove(entry["backend_port"])
    if entry["frontend_port"] in frontend_ports:
        frontend_ports.remove(entry["frontend_port"])
    
    _save_registry(registry)
    print(f"  [Port] Released for '{project_slug}': backend={entry['backend_port']}, frontend={entry['frontend_port']}")
    return True


def get_project_ports(project_slug: str) -> Optional[Tuple[int, int]]:
    """Get allocated ports for a project.
    
    Returns (backend_port, frontend_port) or None if not found.
    """
    registry = _load_registry()
    if project_slug in registry["projects"]:
        entry = registry["projects"][project_slug]
        return entry["backend_port"], entry["frontend_port"]
    return None


def list_all_projects() -> dict:
    """List all registered projects and their ports."""
    registry = _load_registry()
    return registry.get("projects", {})


def get_stats() -> dict:
    """Get port allocation statistics."""
    registry = _load_registry()
    total_backend = BACKEND_PORT_END - BACKEND_PORT_START + 1
    total_frontend = FRONTEND_PORT_END - FRONTEND_PORT_START + 1
    used = len(registry.get("projects", {}))
    return {
        "total_capacity": min(total_backend, total_frontend),
        "used": used,
        "available": min(total_backend, total_frontend) - used,
        "backend_range": f"{BACKEND_PORT_START}-{BACKEND_PORT_END}",
        "frontend_range": f"{FRONTEND_PORT_START}-{FRONTEND_PORT_END}",
    }


if __name__ == "__main__":
    """CLI for port registry management."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python port_registry.py allocate <project-slug>")
        print("  python port_registry.py release <project-slug>")
        print("  python port_registry.py query <project-slug>")
        print("  python port_registry.py list")
        print("  python port_registry.py stats")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "allocate" and len(sys.argv) >= 3:
        bp, fp = allocate_ports(sys.argv[2])
        print(f"Backend: {bp}, Frontend: {fp}")
    elif cmd == "release" and len(sys.argv) >= 3:
        release_ports(sys.argv[2])
    elif cmd == "query" and len(sys.argv) >= 3:
        result = get_project_ports(sys.argv[2])
        if result:
            print(f"Backend: {result[0]}, Frontend: {result[1]}")
        else:
            print("Not found")
            sys.exit(1)
    elif cmd == "list":
        projects = list_all_projects()
        for slug, info in projects.items():
            print(f"  {slug}: backend={info['backend_port']}, frontend={info['frontend_port']}")
    elif cmd == "stats":
        stats = get_stats()
        print(f"  Capacity: {stats['used']}/{stats['total_capacity']} used, {stats['available']} available")
        print(f"  Backend range: {stats['backend_range']}")
        print(f"  Frontend range: {stats['frontend_range']}")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
