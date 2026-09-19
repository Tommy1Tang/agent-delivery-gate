"""Shared deterministic types and serialization for the code-intelligence sidecar.

The module intentionally uses only the Python standard library.  Gate facts are
derived from canonical JSON, never from LLM output or generated Cypher.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum, StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "1.0.0"
HASH_PREFIX = "sha256:"
VOLATILE_HASH_KEYS = frozenset({"generatedAt", "created_at", "contentHash"})


class ImpactVerdict(StrEnum):
    FOUND = "FOUND"
    NO_IMPACT = "NO_IMPACT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SymbolRef:
    repositoryId: str
    relativePath: str
    qualifiedName: str
    symbolKind: str
    startLine: int
    endLine: int
    manifestHash: str
    symbolId: str = ""

    def __post_init__(self) -> None:
        normalized = normalize_relative_path(self.relativePath)
        if not self.repositoryId or not self.qualifiedName or not self.symbolKind:
            raise ValueError("SymbolRef identity fields must be non-empty")
        if self.startLine < 1 or self.endLine < self.startLine:
            raise ValueError("SymbolRef line span must be a 1-based closed interval")
        object.__setattr__(self, "relativePath", normalized)
        expected = symbol_id(
            self.repositoryId,
            normalized,
            self.qualifiedName,
            self.symbolKind,
            self.startLine,
            self.endLine,
        )
        if self.symbolId and self.symbolId != expected:
            raise ValueError("SymbolRef symbolId does not match its stable identity")
        object.__setattr__(self, "symbolId", expected)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_value(cls, value: Mapping[str, object] | "SymbolRef") -> "SymbolRef":
        if isinstance(value, cls):
            return value
        return cls(
            repositoryId=str(value.get("repositoryId", "")),
            relativePath=str(value.get("relativePath", "")),
            qualifiedName=str(value.get("qualifiedName", "")),
            symbolKind=str(value.get("symbolKind", "")).upper(),
            startLine=int(value.get("startLine", 0)),
            endLine=int(value.get("endLine", 0)),
            manifestHash=str(value.get("manifestHash", "")),
            symbolId=str(value.get("symbolId", "")),
        )


def normalize_relative_path(value: str | os.PathLike[str]) -> str:
    """Return a safe repository-relative POSIX path.

    Absolute paths, drive-qualified paths, traversal, empty paths and NUL are
    rejected so derived artifacts never leak or escape the repository root.
    """

    raw = os.fspath(value).replace("\\", "/").strip()
    if not raw or "\x00" in raw:
        raise ValueError("relative path must be non-empty and contain no NUL")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ValueError("absolute paths are forbidden in code-intelligence artifacts")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path traversal and non-normal path segments are forbidden")
    return path.as_posix()


def ensure_contained(root: Path, candidate: Path, *, allow_root: bool = False) -> Path:
    resolved_root = root.resolve(strict=True)
    lexical_candidate = candidate.absolute()
    try:
        lexical_relative = lexical_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("path is outside the allowed root") from exc
    lexical_current = resolved_root
    for part in lexical_relative.parts:
        lexical_current = lexical_current / part
        if lexical_current.exists() and lexical_current.is_symlink():
            raise ValueError("symlinked artifact path is forbidden")
    resolved_candidate = candidate.resolve(strict=False)
    try:
        relative = resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("path is outside the allowed root") from exc
    if not allow_root and not relative.parts:
        raise ValueError("the allowed root itself cannot be used as an artifact target")
    return resolved_candidate


def _json_value(value: Any, excluded_keys: frozenset[str]) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item, excluded_keys)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
            if str(key) not in excluded_keys
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item, excluded_keys) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [_json_value(item, excluded_keys) for item in value]
        return sorted(converted, key=lambda item: canonical_json(item))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN and Infinity are forbidden in canonical JSON")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_json(value: Any, excluded_keys: Iterable[str] = ()) -> bytes:
    excluded = frozenset(excluded_keys)
    normalized = _json_value(value, excluded)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: Any, excluded_keys: Iterable[str] = VOLATILE_HASH_KEYS) -> str:
    return HASH_PREFIX + hashlib.sha256(canonical_json(value, excluded_keys)).hexdigest()


def boundary_summary(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    boundaries = list(rows)

    def counts(field: str) -> list[dict[str, object]]:
        values: dict[str, int] = {}
        for row in boundaries:
            key = str(row.get(field, ""))
            values[key] = values.get(key, 0) + 1
        return [{"key": key, "count": values[key]} for key in sorted(values)]

    return {
        "total": len(boundaries),
        "byType": counts("type"),
        "byClass": counts("boundaryClass"),
        "byKind": counts("boundaryKind"),
        "traversalStopped": bool(boundaries),
    }


def bytes_hash(value: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return HASH_PREFIX + digest.hexdigest()


def symbol_id(
    repository_id: str,
    relative_path: str,
    qualified_name: str,
    symbol_kind: str,
    start_line: int,
    end_line: int,
) -> str:
    payload = "|".join(
        (repository_id, normalize_relative_path(relative_path), qualified_name, symbol_kind.upper(), str(start_line), str(end_line))
    )
    return HASH_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, value: Any, *, allowed_root: Path | None = None) -> None:
    target = path.resolve(strict=False)
    if allowed_root is not None:
        target = ensure_contained(allowed_root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(staging_name).replace(target)
    except BaseException:
        staging = Path(staging_name)
        if staging.exists():
            staging.unlink()
        raise


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return value
