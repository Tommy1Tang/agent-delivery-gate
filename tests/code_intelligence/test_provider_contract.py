from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.code_graph_provider import ProviderConfig, ProviderProbe, _protobuf_to_mapping, _validate_manifest, probe_provider, run_provider_index
from scripts.code_intelligence_models import file_hash


class _Message:
    def __init__(self, fields: list[tuple[object, object]]) -> None:
        self._fields = fields

    def ListFields(self) -> list[tuple[object, object]]:
        return self._fields


class _UpbDescriptor:
    """protobuf 7/upb shape: is_repeated exists and label does not."""

    def __init__(self, name: str, *, is_repeated: bool = False, enum_type: object = None) -> None:
        self.name = name
        self.is_repeated = is_repeated
        self.enum_type = enum_type


class _LegacyDescriptor:
    LABEL_REPEATED = 3

    def __init__(self, name: str, *, label: int, enum_type: object = None) -> None:
        self.name = name
        self.label = label
        self.enum_type = enum_type


class _EnumValue:
    def __init__(self, name: str) -> None:
        self.name = name


class _EnumType:
    def __init__(self) -> None:
        self.values_by_number = {1: _EnumValue("KNOWN")}


class _RecordHash:
    mode = "sha256"

    def __init__(self, payload: bytes) -> None:
        self.value = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode("ascii").rstrip("=")


class _DistributionFile:
    def __init__(self, relative: str, payload: bytes) -> None:
        self.relative = relative
        self.hash = _RecordHash(payload)

    def __str__(self) -> str:
        return self.relative


class _Distribution:
    version = "0.0.779"

    def __init__(self, root: Path, files: list[_DistributionFile]) -> None:
        self.root = root
        self.files = files
        self.entry_points = [SimpleNamespace(group="console_scripts", name="cgr", value="codebase_rag.cli:app")]

    def locate_file(self, value: object) -> Path:
        return self.root / str(value)


class ProviderContractTests(unittest.TestCase):
    def test_clean_full_run_uses_disposable_mirror_and_preserves_source_cache(self) -> None:
        probe = ProviderProbe("SUCCESS", "OK", "0.0.779", "cgr")
        staged_roots: list[Path] = []

        def fake_run(argv: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            self.assertGreater(timeout_seconds, 0)
            if argv[1] == "index":
                staged_root = Path(argv[argv.index("--repo-path") + 1])
                staged_output = Path(argv[argv.index("--output-proto-dir") + 1])
                staged_roots.append(staged_root)
                self.assertTrue((staged_root / "app.py").is_file())
                self.assertFalse((staged_root / "excluded" / "ignored.py").exists())
                self.assertFalse((staged_root / "docs" / "10-report.md").exists())
                self.assertFalse((staged_root / ".cgr-hash-cache.json").exists())
                (staged_root / ".cgr-hash-cache.json").write_text("provider-state", encoding="utf-8")
                staged_output.mkdir(parents=True)
                (staged_output / "nodes.bin").write_bytes(b"all-nodes")
                (staged_output / "relationships.bin").write_bytes(b"all-relationships")
                manifest = {
                    "manifest_version": 1,
                    "analyzer_version": "0.0.779",
                    "codec_schema_sha256": ProviderConfig().codec_schema_sha256,
                    "artifacts": {
                        "nodes.bin": {"sha256": file_hash(staged_output / "nodes.bin").removeprefix("sha256:")},
                        "relationships.bin": {"sha256": file_hash(staged_output / "relationships.bin").removeprefix("sha256:")},
                    },
                }
                (staged_output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "app.py").write_text("def all_code(): pass\n", encoding="utf-8")
            (root / "excluded").mkdir()
            (root / "excluded" / "ignored.py").write_text("ignored = True\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "10-report.md").write_text("quality report\n", encoding="utf-8")
            source_cache = root / ".cgr-hash-cache.json"
            source_cache.write_text("pre-existing-source-state", encoding="utf-8")
            stale_output = root / "derived" / "one"
            stale_output.mkdir(parents=True)
            (stale_output / "stale-delta.bin").write_bytes(b"stale")
            config = ProviderConfig.from_mapping({
                "provider": {},
                "excludeDirectories": ["excluded", "derived"],
                "excludePaths": ["docs\\10-report.md"],
            })
            with patch("scripts.code_graph_provider.probe_provider", return_value=probe), patch("scripts.code_graph_provider._run", side_effect=fake_run):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first_future = executor.submit(run_provider_index, root, root / "derived" / "one", config)
                    second_future = executor.submit(run_provider_index, root, root / "derived" / "two", config)
                    first = first_future.result()
                    second = second_future.result()

            self.assertEqual((first.status, second.status), ("SUCCESS", "SUCCESS"))
            self.assertEqual(source_cache.read_text(encoding="utf-8"), "pre-existing-source-state")
            self.assertFalse((root / ".cgr-dir-mtimes.json").exists())
            self.assertTrue((root / "derived" / "one" / "nodes.bin").is_file())
            self.assertFalse((root / "derived" / "one" / "stale-delta.bin").exists())
            self.assertTrue((root / "derived" / "two" / "nodes.bin").is_file())
            self.assertEqual(len(set(staged_roots)), 2)
            self.assertTrue(all(not staged_root.exists() for staged_root in staged_roots))

    def test_protobuf_7_upb_descriptor_without_label_is_supported(self) -> None:
        repeated = _UpbDescriptor("children", is_repeated=True)
        enum = _UpbDescriptor("kind", enum_type=_EnumType())
        nested = _UpbDescriptor("nested")
        scalar = _UpbDescriptor("count")
        self.assertFalse(hasattr(repeated, "label"))

        result = _protobuf_to_mapping(_Message([
            (repeated, [_Message([(_UpbDescriptor("name"), "first")]), "raw"]),
            (enum, 1),
            (nested, _Message([(_UpbDescriptor("enabled"), True)])),
            (scalar, 2),
        ]))

        self.assertEqual(result, {
            "children": [{"name": "first"}, "raw"],
            "kind": "KNOWN",
            "nested": {"enabled": True},
            "count": 2,
        })

    def test_legacy_descriptor_falls_back_to_label(self) -> None:
        repeated = _LegacyDescriptor("values", label=_LegacyDescriptor.LABEL_REPEATED)
        scalar = _LegacyDescriptor("count", label=1)
        result = _protobuf_to_mapping(_Message([(repeated, [1, 2]), (scalar, 3)]))
        self.assertEqual(result, {"values": [1, 2], "count": 3})

    def test_is_repeated_takes_precedence_over_legacy_label(self) -> None:
        descriptor = _UpbDescriptor("count", is_repeated=False)
        descriptor.label = 3
        descriptor.LABEL_REPEATED = 3
        self.assertEqual(_protobuf_to_mapping(_Message([(descriptor, 7)])), {"count": 7})

    def test_missing_command_is_stable_unknown(self) -> None:
        # @trace FR-008 AC-008 AC-011 AC-012 AC-013
        # @test-id TEST-CODE-PROVIDER-CONTRACT
        with patch("scripts.code_graph_provider.shutil.which", return_value=None):
            result = probe_provider({})
        self.assertEqual((result.status, result.code), ("UNKNOWN", "PROVIDER_COMMAND_NOT_FOUND"))

    def test_version_mismatch_is_rejected(self) -> None:
        completed = subprocess.CompletedProcess(["cgr", "--version"], 0, "code-graph-rag version 9.9.9\n", "")
        with patch("scripts.code_graph_provider.shutil.which", return_value="cgr"), \
             patch("scripts.code_graph_provider._verify_distribution_identity", return_value={"verificationMode": "installed-record"}), \
             patch("scripts.code_graph_provider._run", return_value=completed):
            result = probe_provider({})
        self.assertEqual(result.code, "PROVIDER_VERSION_MISMATCH")

    def test_probe_byte_binds_path_launcher_distribution_record_and_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            launcher = root / "bin" / "cgr"
            decoder = root / "codec" / "schema_pb2.py"
            record = root / "code_graph_rag-0.0.779.dist-info" / "RECORD"
            for path, payload in ((launcher, b"trusted-launcher"), (decoder, b"trusted-decoder"), (record, b"record")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            distribution = _Distribution(root, [
                _DistributionFile("bin/cgr", launcher.read_bytes()),
                _DistributionFile("codec/schema_pb2.py", decoder.read_bytes()),
                _DistributionFile("code_graph_rag-0.0.779.dist-info/RECORD", record.read_bytes()),
            ])
            completed = subprocess.CompletedProcess([str(launcher), "--version"], 0, "code-graph-rag version 0.0.779\n", "")
            module = SimpleNamespace(__file__=str(decoder))
            with patch("scripts.code_graph_provider.shutil.which", return_value=str(launcher)), \
                 patch("scripts.code_graph_provider._run", return_value=completed), \
                 patch("scripts.code_graph_provider.importlib.metadata.distribution", return_value=distribution), \
                 patch("scripts.code_graph_provider.importlib.import_module", return_value=module):
                result = probe_provider({})

        self.assertTrue(result.ok)
        self.assertEqual(result.identity["entryPoint"], "codebase_rag.cli:app")
        self.assertEqual(result.identity["launcherSha256"], "sha256:" + hashlib.sha256(b"trusted-launcher").hexdigest())
        self.assertEqual(result.identity["decoderSha256"], "sha256:" + hashlib.sha256(b"trusted-decoder").hexdigest())

    def test_probe_rejects_path_shadow_and_recorded_byte_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            launcher = root / "bin" / "cgr"
            shadow = root / "shadow" / "cgr"
            decoder = root / "codec" / "schema_pb2.py"
            record = root / "code_graph_rag-0.0.779.dist-info" / "RECORD"
            for path, payload in ((launcher, b"trusted"), (shadow, b"trusted"), (decoder, b"decoder"), (record, b"record")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            distribution = _Distribution(root, [
                _DistributionFile("bin/cgr", b"trusted"),
                _DistributionFile("codec/schema_pb2.py", b"decoder"),
                _DistributionFile("code_graph_rag-0.0.779.dist-info/RECORD", b"record"),
            ])
            completed = subprocess.CompletedProcess([str(shadow), "--version"], 0, "code-graph-rag version 0.0.779\n", "")
            module = SimpleNamespace(__file__=str(decoder))
            with patch("scripts.code_graph_provider.shutil.which", return_value=str(shadow)), \
                 patch("scripts.code_graph_provider._run", return_value=completed), \
                 patch("scripts.code_graph_provider.importlib.metadata.distribution", return_value=distribution), \
                 patch("scripts.code_graph_provider.importlib.import_module", return_value=module):
                shadowed = probe_provider({})
            launcher.write_bytes(b"tampered")
            with patch("scripts.code_graph_provider.shutil.which", return_value=str(launcher)), \
                 patch("scripts.code_graph_provider._run", return_value=completed), \
                 patch("scripts.code_graph_provider.importlib.metadata.distribution", return_value=distribution), \
                 patch("scripts.code_graph_provider.importlib.import_module", return_value=module):
                tampered = probe_provider({})

        self.assertEqual((shadowed.status, shadowed.code), ("UNKNOWN", "PROVIDER_CONTRACT_MISMATCH"))
        self.assertEqual((tampered.status, tampered.code), ("UNKNOWN", "PROVIDER_CONTRACT_MISMATCH"))

    def test_schema_drift_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); (root / "nodes.bin").write_bytes(b"n"); (root / "relationships.bin").write_bytes(b"r")
            manifest = {"manifest_version": 1, "analyzer_version": "0.0.779", "codec_schema_sha256": "0" * 64, "artifacts": {"nodes.bin": {"sha256": "0" * 64}, "relationships.bin": {"sha256": "0" * 64}}}
            errors = _validate_manifest(root, manifest, ProviderConfig())
        self.assertTrue(any("codec" in item for item in errors))

    def test_nonzero_index_exit_and_verify_failure_are_unknown(self) -> None:
        probe = ProviderProbe("SUCCESS", "OK", "0.0.779", "cgr")
        failure = subprocess.CompletedProcess([], 7, "", "bad")
        with tempfile.TemporaryDirectory() as raw, patch("scripts.code_graph_provider.probe_provider", return_value=probe), patch("scripts.code_graph_provider._run", return_value=failure):
            result = run_provider_index(Path(raw), Path(raw) / "out", ProviderConfig())
        self.assertEqual((result.status, result.code), ("UNKNOWN", "PROVIDER_PROCESS_FAILED"))

        success = subprocess.CompletedProcess([], 0, "", "")
        verify_fail = subprocess.CompletedProcess([], 1, "", "bad")
        with tempfile.TemporaryDirectory() as raw, patch("scripts.code_graph_provider.probe_provider", return_value=probe), patch("scripts.code_graph_provider._run", side_effect=[success, verify_fail]):
            result = run_provider_index(Path(raw), Path(raw) / "out", ProviderConfig())
        self.assertEqual(result.code, "INDEX_INTEGRITY_FAILURE")


if __name__ == "__main__": unittest.main()
