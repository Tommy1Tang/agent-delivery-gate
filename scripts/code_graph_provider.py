"""Narrow adapter for the pinned code-graph-rag offline index provider."""

from __future__ import annotations

import importlib
import importlib.metadata
import base64
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # package import in unittest discovery
    from .code_intelligence_models import file_hash, normalize_relative_path
except ImportError:  # direct CLI execution
    from code_intelligence_models import file_hash, normalize_relative_path


PINNED_VERSION = "0.0.779"
PINNED_MANIFEST_VERSION = 1
PINNED_CODEC_SHA256 = "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84"
PINNED_DISTRIBUTION = "code-graph-rag"
PINNED_ENTRY_POINT = "codebase_rag.cli:app"
VERSION_PATTERN = re.compile(r"^code-graph-rag version ([0-9]+(?:\.[0-9]+){2})$")


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    executable: str = "cgr"
    provider_version: str = PINNED_VERSION
    manifest_version: int = PINNED_MANIFEST_VERSION
    codec_schema_sha256: str = PINNED_CODEC_SHA256
    distribution_name: str = PINNED_DISTRIBUTION
    entry_point: str = PINNED_ENTRY_POINT
    required_captures: tuple[str, ...] = ("structure", "calls", "types", "imports")
    excluded_directories: tuple[str, ...] = ()
    excluded_paths: tuple[str, ...] = ()
    timeout_seconds: int = 600

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProviderConfig":
        provider = value.get("provider", value)
        if not isinstance(provider, Mapping):
            raise ValueError("provider configuration must be an object")
        captures = provider.get("requiredCaptures", ("structure", "calls", "types", "imports"))
        if not isinstance(captures, Sequence) or isinstance(captures, (str, bytes)):
            raise ValueError("requiredCaptures must be an array")
        exclusions = value.get("excludeDirectories", provider.get("excludeDirectories", ()))
        if not isinstance(exclusions, Sequence) or isinstance(exclusions, (str, bytes)):
            raise ValueError("excludeDirectories must be an array")
        excluded_paths = value.get("excludePaths", provider.get("excludePaths", ()))
        if not isinstance(excluded_paths, Sequence) or isinstance(excluded_paths, (str, bytes)):
            raise ValueError("excludePaths must be an array")
        return cls(
            executable=str(provider.get("executable", "cgr")),
            provider_version=str(provider.get("providerVersion", PINNED_VERSION)),
            manifest_version=int(provider.get("manifestVersion", PINNED_MANIFEST_VERSION)),
            codec_schema_sha256=str(provider.get("codecSchemaSha256", PINNED_CODEC_SHA256)),
            distribution_name=str(provider.get("distributionName", PINNED_DISTRIBUTION)),
            entry_point=str(provider.get("entryPoint", PINNED_ENTRY_POINT)),
            required_captures=tuple(str(item) for item in captures),
            excluded_directories=tuple(str(item) for item in exclusions),
            excluded_paths=tuple(normalize_relative_path(str(item)) for item in excluded_paths),
            timeout_seconds=int(provider.get("timeoutSeconds", 600)),
        )


@dataclass(frozen=True, slots=True)
class ProviderProbe:
    status: str
    code: str
    provider_version: str | None = None
    executable: str | None = None
    remediation: str = ""
    diagnostics: tuple[str, ...] = ()
    identity: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "SUCCESS"


@dataclass(frozen=True, slots=True)
class ProviderRun:
    status: str
    code: str
    output_dir: Path
    exit_code: int
    duration_ms: int
    manifest: Mapping[str, object] | None = None
    diagnostics: tuple[str, ...] = ()
    identity: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawGraph:
    nodes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    relationships: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    manifest: Mapping[str, object] = field(default_factory=dict)


def _run(argv: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout_seconds,
        shell=False,
    )


def _recorded_sha256(distribution_file: object) -> str:
    recorded = getattr(distribution_file, "hash", None)
    if recorded is None or getattr(recorded, "mode", None) != "sha256":
        raise ValueError("distribution RECORD is missing a sha256 claim")
    encoded = str(getattr(recorded, "value", ""))
    try:
        digest = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).hex()
    except (ValueError, TypeError) as exc:
        raise ValueError("distribution RECORD sha256 claim is invalid") from exc
    if len(digest) != 64:
        raise ValueError("distribution RECORD sha256 claim is invalid")
    return "sha256:" + digest


def _record_entry_for_path(distribution: object, path: Path) -> object:
    matches: list[object] = []
    resolved = path.resolve(strict=True)
    for item in getattr(distribution, "files", ()) or ():
        try:
            located = Path(distribution.locate_file(item)).resolve(strict=True)
        except (OSError, TypeError, ValueError):
            continue
        if located == resolved:
            matches.append(item)
    if len(matches) != 1:
        raise ValueError("runtime file is not uniquely owned by the pinned distribution RECORD")
    return matches[0]


def _verify_distribution_identity(config: ProviderConfig, executable: Path) -> dict[str, str]:
    distribution = importlib.metadata.distribution(config.distribution_name)
    if distribution.version != config.provider_version:
        raise ValueError("provider distribution version mismatch")
    entry_points = [
        item for item in distribution.entry_points
        if item.group == "console_scripts" and item.name == "cgr" and item.value == config.entry_point
    ]
    if len(entry_points) != 1:
        raise ValueError("provider console entry point mismatch")
    decoder = importlib.import_module("codec.schema_pb2")
    decoder_file = Path(str(getattr(decoder, "__file__", "")))
    if executable.is_symlink() or decoder_file.is_symlink():
        raise ValueError("symlinked provider runtime files are forbidden")
    launcher_entry = _record_entry_for_path(distribution, executable)
    decoder_entry = _record_entry_for_path(distribution, decoder_file)
    if file_hash(executable) != _recorded_sha256(launcher_entry):
        raise ValueError("provider launcher bytes do not match distribution RECORD")
    if file_hash(decoder_file) != _recorded_sha256(decoder_entry):
        raise ValueError("provider decoder bytes do not match distribution RECORD")
    record_entries = [item for item in distribution.files or () if str(item).replace("\\", "/").endswith(".dist-info/RECORD")]
    if len(record_entries) != 1:
        raise ValueError("provider distribution RECORD is unavailable")
    record_path = Path(distribution.locate_file(record_entries[0]))
    if record_path.is_symlink() or not record_path.is_file():
        raise ValueError("provider distribution RECORD is unavailable")
    return {
        "verificationMode": "installed-record",
        "distribution": config.distribution_name,
        "entryPoint": config.entry_point,
        "launcherSha256": file_hash(executable),
        "decoderSha256": file_hash(decoder_file),
        "recordSha256": file_hash(record_path),
    }


def probe_provider(config: Mapping[str, object]) -> ProviderProbe:
    # @trace FR-008 AC-008 AC-011 AC-012 AC-013
    parsed = ProviderConfig.from_mapping(config)
    executable = shutil.which(parsed.executable)
    if executable is None:
        return ProviderProbe(
            "UNKNOWN",
            "PROVIDER_COMMAND_NOT_FOUND",
            remediation=f"Install code-graph-rag=={parsed.provider_version} in the active Python environment.",
        )
    try:
        identity = _verify_distribution_identity(parsed, Path(executable))
    except (importlib.metadata.PackageNotFoundError, ImportError, OSError, TypeError, ValueError) as exc:
        return ProviderProbe(
            "UNKNOWN", "PROVIDER_CONTRACT_MISMATCH", executable=executable,
            diagnostics=(type(exc).__name__,),
            remediation="Use the pinned distribution-owned launcher and decoder without PATH shadowing or byte drift.",
        )
    try:
        result = _run([executable, "--version"], parsed.timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProviderProbe("UNKNOWN", "PROVIDER_PROCESS_FAILED", executable=executable, diagnostics=(type(exc).__name__,), remediation="Repair the provider installation and retry the probe.")
    text = result.stdout.strip()
    match = VERSION_PATTERN.fullmatch(text)
    if result.returncode != 0 or match is None:
        return ProviderProbe("UNKNOWN", "PROVIDER_CONTRACT_MISMATCH", executable=executable, diagnostics=(f"exit={result.returncode}",), remediation="Install the pinned provider and verify `cgr --version`.")
    cli_version = match.group(1)
    if cli_version != parsed.provider_version:
        return ProviderProbe("UNKNOWN", "PROVIDER_VERSION_MISMATCH", provider_version=cli_version, executable=executable, remediation=f"Install code-graph-rag=={parsed.provider_version}.")
    return ProviderProbe("SUCCESS", "OK", provider_version=cli_version, executable=executable, identity=identity)


def _validate_manifest(index_dir: Path, manifest: Mapping[str, object], config: ProviderConfig) -> tuple[str, ...]:
    errors: list[str] = []
    if manifest.get("manifest_version") != config.manifest_version:
        errors.append("manifest_version mismatch")
    if manifest.get("analyzer_version") != config.provider_version:
        errors.append("analyzer_version mismatch")
    if manifest.get("codec_schema_sha256") != config.codec_schema_sha256:
        errors.append("codec_schema_sha256 mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        errors.append("artifacts missing")
    else:
        expected_names = {"nodes.bin", "relationships.bin"}
        if not expected_names.issubset(artifacts):
            errors.append("split artifacts missing")
        for name, claim in artifacts.items():
            if name not in {"index.bin", "nodes.bin", "relationships.bin"} or not isinstance(claim, Mapping):
                errors.append("foreign artifact name or claim")
                continue
            path = index_dir / str(name)
            if path.is_symlink() or not path.is_file():
                errors.append(f"artifact unavailable: {name}")
                continue
            claimed_hash = str(claim.get("sha256", ""))
            if file_hash(path).removeprefix("sha256:") != claimed_hash:
                errors.append(f"artifact hash mismatch: {name}")
    return tuple(errors)


_PUBLISH_LOCKS_GUARD = threading.Lock()
_PUBLISH_LOCKS: dict[str, threading.Lock] = {}


def _publish_lock(output_dir: Path) -> threading.Lock:
    key = str(output_dir.resolve(strict=False)).casefold()
    with _PUBLISH_LOCKS_GUARD:
        return _PUBLISH_LOCKS.setdefault(key, threading.Lock())


def _mirror_ignore(
    repo_root: Path,
    output_dir: Path,
    excluded_directories: frozenset[str],
    excluded_paths: frozenset[str],
):
    output = output_dir.resolve(strict=False)

    def ignore(current: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        current_path = Path(current)
        for name in names:
            candidate = current_path / name
            relative = normalize_relative_path(candidate.relative_to(repo_root).as_posix())
            if relative in excluded_paths:
                ignored.add(name)
                continue
            if candidate.is_symlink() or name.startswith(".cgr-"):
                ignored.add(name)
                continue
            if candidate.resolve(strict=False) == output:
                ignored.add(name)
                continue
            if candidate.is_dir() and name in excluded_directories:
                ignored.add(name)
        return ignored

    return ignore


def _publish_verified_index(staged_output: Path, output_dir: Path, artifact_names: Sequence[str]) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with _publish_lock(output_dir):
        with tempfile.TemporaryDirectory(prefix=".provider-publish-", dir=output_dir.parent) as publish_raw:
            publish_root = Path(publish_raw)
            candidate = publish_root / "candidate"
            backup = publish_root / "previous"
            candidate.mkdir()
            for name in ("manifest.json", *artifact_names):
                shutil.copy2(staged_output / name, candidate / name, follow_symlinks=False)
            had_previous = output_dir.exists()
            if had_previous:
                output_dir.replace(backup)
            try:
                candidate.replace(output_dir)
            except OSError:
                if had_previous and backup.exists() and not output_dir.exists():
                    backup.replace(output_dir)
                raise


def run_provider_index(repo_root: Path, output_dir: Path, config: ProviderConfig) -> ProviderRun:
    probe = probe_provider({"provider": {
        "executable": config.executable,
        "providerVersion": config.provider_version,
        "manifestVersion": config.manifest_version,
        "codecSchemaSha256": config.codec_schema_sha256,
        "distributionName": config.distribution_name,
        "entryPoint": config.entry_point,
        "requiredCaptures": list(config.required_captures),
        "timeoutSeconds": config.timeout_seconds,
    }})
    if not probe.ok or probe.executable is None:
        return ProviderRun(probe.status, probe.code, output_dir, 2, 0, diagnostics=probe.diagnostics)
    started = time.monotonic()
    try:
        source = repo_root.resolve(strict=True)
        destination = output_dir.resolve(strict=False)
        with tempfile.TemporaryDirectory(prefix="cgr-full-snapshot-") as staging_raw:
            staging = Path(staging_raw).resolve(strict=True)
            try:
                staging.relative_to(source)
            except ValueError:
                pass
            else:
                return ProviderRun("UNKNOWN", "PROVIDER_STAGING_FAILED", output_dir, 2, int((time.monotonic() - started) * 1000), diagnostics=("staging directory is inside source repository",))
            mirror = staging / "repository"
            staged_output = staging / "provider-output"
            shutil.copytree(
                source,
                mirror,
                symlinks=True,
                ignore=_mirror_ignore(
                    source,
                    destination,
                    frozenset(config.excluded_directories),
                    frozenset(config.excluded_paths),
                ),
            )
            argv = [probe.executable, "index", "--repo-path", str(mirror), "--output-proto-dir", str(staged_output), "--split-index"]
            for capture in config.required_captures:
                argv.extend(("--capture", capture))
            result = _run(argv, config.timeout_seconds)
            duration = int((time.monotonic() - started) * 1000)
            if result.returncode != 0:
                return ProviderRun("UNKNOWN", "PROVIDER_PROCESS_FAILED", output_dir, 2, duration, diagnostics=(f"providerExitCode={result.returncode}",))
            verify = _run([probe.executable, "verify-index", "--index-dir", str(staged_output)], config.timeout_seconds)
            if verify.returncode != 0:
                return ProviderRun("UNKNOWN", "INDEX_INTEGRITY_FAILURE", output_dir, 2, duration, diagnostics=(f"verifyExitCode={verify.returncode}",))
            manifest_path = staged_output / "manifest.json"
            if manifest_path.is_symlink():
                return ProviderRun("UNKNOWN", "PROVIDER_CONTRACT_MISMATCH", output_dir, 2, duration, diagnostics=("symlinked manifest is forbidden",))
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return ProviderRun("UNKNOWN", "PROVIDER_DECODE_FAILED", output_dir, 2, duration)
            errors = _validate_manifest(staged_output, manifest, config)
            if errors:
                return ProviderRun("UNKNOWN", "PROVIDER_CONTRACT_MISMATCH", output_dir, 2, duration, manifest, errors)
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, Mapping):
                return ProviderRun("UNKNOWN", "PROVIDER_CONTRACT_MISMATCH", output_dir, 2, duration, manifest, ("artifacts missing",))
            _publish_verified_index(staged_output, destination, tuple(str(name) for name in artifacts))
    except subprocess.TimeoutExpired:
        return ProviderRun("UNKNOWN", "PROVIDER_PROCESS_FAILED", output_dir, 2, int((time.monotonic() - started) * 1000), diagnostics=("TimeoutExpired",))
    except OSError as exc:
        return ProviderRun("UNKNOWN", "PROVIDER_STAGING_FAILED", output_dir, 2, int((time.monotonic() - started) * 1000), diagnostics=(type(exc).__name__,))
    return ProviderRun("SUCCESS", "OK", output_dir, 0, int((time.monotonic() - started) * 1000), manifest, identity=probe.identity)


_DESCRIPTOR_ATTRIBUTE_MISSING = object()


def _descriptor_is_repeated(descriptor: Any) -> bool:
    """Use the protobuf 6/7 API, falling back to the legacy descriptor API."""
    is_repeated = getattr(descriptor, "is_repeated", _DESCRIPTOR_ATTRIBUTE_MISSING)
    if is_repeated is not _DESCRIPTOR_ATTRIBUTE_MISSING:
        return bool(is_repeated)
    return descriptor.label == descriptor.LABEL_REPEATED


def _protobuf_to_mapping(message: Any) -> dict[str, Any]:
    """Extract only stable structural fields and intentionally discard snippets."""
    result: dict[str, Any] = {}
    for descriptor, value in message.ListFields():
        name = descriptor.name
        if name.lower() in {"snippet", "source", "text", "content", "docstring"}:
            continue
        if _descriptor_is_repeated(descriptor):
            result[name] = [_protobuf_to_mapping(item) if hasattr(item, "ListFields") else item for item in value]
        elif descriptor.enum_type is not None:
            enum_value = descriptor.enum_type.values_by_number.get(int(value))
            result[name] = enum_value.name if enum_value is not None else f"UNKNOWN_ENUM_{value}"
        elif hasattr(value, "ListFields"):
            result[name] = _protobuf_to_mapping(value)
        else:
            result[name] = value
    return result


def load_provider_index(index_dir: Path) -> RawGraph:
    """Load a verified raw graph.

    ``raw-graph.json`` is an explicit deterministic fixture contract used by
    tests; production directories use the provider protobuf artifacts.
    """
    fixture = index_dir / "raw-graph.json"
    manifest_path = index_dir / "manifest.json"
    manifest: Mapping[str, object] = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if fixture.is_file():
        value = json.loads(fixture.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping) or not isinstance(value.get("nodes", []), list) or not isinstance(value.get("relationships", []), list):
            raise ValueError("raw-graph fixture violates the provider adapter contract")
        return RawGraph(tuple(dict(item) for item in value.get("nodes", [])), tuple(dict(item) for item in value.get("relationships", [])), manifest)
    try:
        pb = importlib.import_module("codec.schema_pb2")
    except ImportError as exc:
        raise RuntimeError("PROVIDER_CONTRACT_MISMATCH: codec.schema_pb2 is unavailable") from exc
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    for name, destination in (("nodes.bin", nodes), ("relationships.bin", relationships), ("index.bin", None)):
        path = index_dir / name
        if not path.is_file():
            continue
        index = pb.GraphCodeIndex()
        index.ParseFromString(path.read_bytes())
        if destination is not None:
            sequence = index.nodes if name == "nodes.bin" else index.relationships
            destination.extend(_protobuf_to_mapping(item) for item in sequence)
        else:
            nodes.extend(_protobuf_to_mapping(item) for item in index.nodes)
            relationships.extend(_protobuf_to_mapping(item) for item in index.relationships)
    if not nodes and not relationships:
        raise RuntimeError("PROVIDER_DECODE_FAILED: no provider artifacts were decoded")
    return RawGraph(tuple(nodes), tuple(relationships), manifest)
