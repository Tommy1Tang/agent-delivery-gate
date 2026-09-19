"""Print path-resolution facts so CI failures of this class are self-diagnosing.

Motivated by a Windows-only CI failure where a temp directory that was
genuinely inside the project root was reported as REPOSITORY_OUTSIDE_ALLOWED_ROOT.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print(f"platform      : {sys.platform}")
print(f"python        : {sys.version.split()[0]}")
print(f"os.environ[TEMP] : {os.environ.get('TEMP')}")
print(f"os.environ[TMP]  : {os.environ.get('TMP')}")
print(f"tempfile.gettempdir(): {tempfile.gettempdir()}")

with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    print(f"\nTemporaryDirectory() as str : {raw}")
    print(f"  Path(raw).absolute()      : {root.absolute()}")
    print(f"  Path(raw).resolve()       : {root.resolve()}")
    print(f"  absolute == resolve       : {str(root.absolute()) == str(root.resolve())}")

    out = root / "_test_output" / "run-0"
    print(f"\nout dir (as built)          : {out}")
    print(f"  out.absolute()            : {out.absolute()}")
    print(f"  out.resolve(strict=False) : {out.resolve(strict=False)}")
    print(f"  root.resolve()            : {root.resolve()}")
    try:
        rel = out.resolve(strict=False).relative_to(root.resolve())
        print(f"  relative_to(root.resolve) : OK -> {rel}")
    except ValueError as exc:
        print(f"  relative_to(root.resolve) : FAILED -> {exc}")

    # Exercise the real guard.
    from scripts.code_intelligence_models import ensure_contained

    try:
        result = ensure_contained(root, out)
        print(f"\nensure_contained(root, out) : OK -> {result}")
    except ValueError as exc:
        print(f"\nensure_contained(root, out) : FAILED -> {exc}")

    # And the real build path, reporting status/code/diagnostics on failure.
    try:
        from scripts.build_code_index import build_index

        cfg = {
            "sourceExtensions": [".py"],
            "excludeDirectories": [".git", "__pycache__", "_test_output"],
            "excludePaths": [],
            "repositoryId": "diag",
        }
        (root / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        res = build_index(root, out, cfg, "diag")
        print(f"\nbuild_index -> status={res.status} code={res.code} diagnostics={getattr(res, 'diagnostics', None)}")
    except Exception as exc:  # noqa: BLE001 - diagnostics script
        import traceback

        print(f"\nbuild_index raised {type(exc).__name__}: {exc}")
        traceback.print_exc()
