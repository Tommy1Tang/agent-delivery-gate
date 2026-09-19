#!/usr/bin/env python3
"""Deterministic technology-stack detector for software-development-team.

Scans the project root for well-known dependency manifests and returns the
canonical adapter ids the downstream roles must follow. Run as a script or
import :func:`detect_stack` from orchestrate.py.

Goals:
- Pure file-system inspection, no LLM judgement.
- Output is stable for the same inputs (sorted, lower-cased adapter ids).
- Tells callers what to read and what to ignore so token budget shrinks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Map adapter id (matches assets/config/agent-team-config.json -> harness.adapters)
# to (manifest filenames, content signatures). Order matters for prioritisation.
ADAPTER_SIGNATURES: list[tuple[str, list[str], list[str]]] = [
    (
        "javaSpringMysql",
        ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle"],
        ["spring-boot", "org.springframework", "mybatis", "mysql"],
    ),
    (
        "pythonFastapiSqlite",
        ["pyproject.toml", "requirements.txt", "Pipfile", "poetry.lock"],
        ["fastapi", "uvicorn", "sqlite", "sqlalchemy"],
    ),
    (
        "nodeReact",
        ["package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"],
        ["react", "next", "express", "nestjs"],
    ),
    (
        "vueElementPlus",
        ["package.json", "pnpm-lock.yaml", "yarn.lock", "vite.config.ts", "vite.config.js"],
        ["vue", "element-plus", "@vue/", "vite"],
    ),
]

# Hint files that are not mapped to a single adapter but still inform the team.
INFRA_HINTS = {
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    "kubernetes": ["k8s/", "manifests/", "helm/"],
    "githubActions": [".github/workflows/"],
    "gitlabCi": [".gitlab-ci.yml"],
}

DB_MIGRATION_HINTS = [
    "src/main/resources/db/migration",  # Flyway
    "src/main/resources/db/changelog",  # Liquibase
    "db/migrate",                         # Rails
    "migrations",                         # generic / Django / Alembic
    "prisma/migrations",
    "supabase/migrations",
]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _exists_any(root: Path, candidates: list[str]) -> list[str]:
    hits: list[str] = []
    for c in candidates:
        target = root / c
        if target.exists():
            hits.append(c)
    return hits


def detect_stack(project_root: Path) -> dict:
    """Return a deterministic snapshot of the project stack."""
    project_root = project_root.resolve()
    selected: list[str] = []
    evidence: dict[str, list[str]] = {}

    # Search both project root and common sub-directories.
    search_roots = [project_root]
    for sub in ("backend", "server", "api", "frontend", "client", "web", "ui", "app"):
        sub_path = project_root / sub
        if sub_path.is_dir():
            search_roots.append(sub_path)

    # Pre-load common manifest contents once to test signatures.
    cached: dict[str, str] = {}
    for adapter_id, manifests, signatures in ADAPTER_SIGNATURES:
        manifest_hits: list[str] = []
        signature_hits: list[str] = []
        for search_root in search_roots:
            for manifest in manifests:
                manifest_path = search_root / manifest
                if not manifest_path.exists():
                    continue
                rel_manifest = str(manifest_path.relative_to(project_root))
                manifest_hits.append(rel_manifest)
                cache_key = str(manifest_path)
                text = cached.setdefault(cache_key, _read_text(manifest_path).lower())
                for sig in signatures:
                    if sig.lower() in text and sig not in signature_hits:
                        signature_hits.append(sig)
        if manifest_hits and signature_hits:
            selected.append(adapter_id)
            evidence[adapter_id] = sorted(set(manifest_hits + signature_hits))

    selected = sorted(set(selected))

    infra: dict[str, list[str]] = {}
    for label, candidates in INFRA_HINTS.items():
        hits = _exists_any(project_root, candidates)
        if hits:
            infra[label] = hits

    migration_dirs = [d for d in DB_MIGRATION_HINTS if (project_root / d).exists()]

    layout = {
        "hasBackend": any((project_root / d).exists() for d in ("backend", "server", "src/main/java", "api")),
        "hasFrontend": any((project_root / d).exists() for d in ("frontend", "client", "web", "ui")),
        "hasDocs": (project_root / "docs").exists(),
        "hasTests": any(
            (project_root / d).exists()
            for d in ("tests", "test", "src/test", "__tests__", "e2e")
        ),
    }

    return {
        "projectRoot": str(project_root),
        "selectedAdapters": selected,
        "adapterEvidence": evidence,
        "infrastructure": infra,
        "migrationDirs": migration_dirs,
        "projectLayout": layout,
        "deterministic": True,
        "scaffoldTemplate": _resolve_scaffold_template(selected),
    }


# Scaffold template resolution: adapter -> scaffold directory name
SCAFFOLD_MAP = {
    "javaSpringMysql": "java-spring-postgresql",
    "nodeReact": "node-react",
    "vueElementPlus": "vue-element-plus",
    "pythonFastapiSqlite": "python-fastapi-sqlite",
}


def _resolve_scaffold_template(adapters: list[str]) -> str:
    """Determine the appropriate scaffold template based on detected adapters.

    Priority: Java > Node > Python > default (Java)
    """
    if not adapters:
        return "java-spring-postgresql"  # Default to the Java/Spring adapter

    # Priority-based resolution
    for adapter in ["javaSpringMysql", "nodeReact", "pythonFastapiSqlite", "vueElementPlus"]:
        if adapter in adapters:
            return SCAFFOLD_MAP.get(adapter, "java-spring-postgresql")

    return "java-spring-postgresql"


def get_scaffold_path(skill_root: Path, adapters: list[str]) -> Path:
    """Get the resolved scaffold template path for external callers."""
    template_name = _resolve_scaffold_template(adapters)
    return skill_root / "assets" / "templates" / template_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()

    result = detect_stack(Path(args.project_root))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Project root      : {result['projectRoot']}")
        print(f"Selected adapters : {result['selectedAdapters'] or ['<none>']}")
        print(f"Migration dirs    : {result['migrationDirs'] or ['<none>']}")
        print(f"Infrastructure    : {sorted(result['infrastructure'].keys()) or ['<none>']}")
        print(f"Layout            : {result['projectLayout']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
