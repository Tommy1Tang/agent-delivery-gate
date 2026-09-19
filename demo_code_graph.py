"""Generate a real code-graph query output for the README demo.

Builds the same fixture graph the test-suite uses, writes it to a temp dir,
then runs the public query CLI against it and prints the JSON.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "code_intelligence"))

from helpers import snapshot, trace  # noqa: E402  (test fixture builders)

snap = snapshot()
bridge = trace()
tmp = Path(tempfile.mkdtemp(prefix="graph-demo-"))
snap_path = tmp / "code-index-snapshot.json"
snap_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
bridge_path = tmp / "code-trace-bridge.json"
bridge_path.write_text(json.dumps(bridge, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"fixture graph: {len(snap['symbols'])} symbols, "
      f"{len(snap['relationships'])} relationships")
print("=" * 70)

CASES = [
    ("definition", "app.worker"),
    ("callees", "app.entry"),
    ("callers", "app.worker"),
    ("implements_requirement", "FR-001"),
    ("tests_for", "app.worker"),
]

for intent, target in CASES:
    out = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "query_code_graph.py"),
         "--snapshot", str(snap_path), "--trace-bridge", str(bridge_path),
         "--intent", intent, "--target", target, "--json"],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    print(f"\n$ query_code_graph.py --intent {intent} --target {target}")
    body = out.stdout.strip()
    try:
        parsed = json.loads(body)
        keep = {k: parsed[k] for k in
                ("queryStatus", "intent", "normalizedTarget", "answerFacts",
                 "candidates", "diagnostics") if k in parsed}
        print(json.dumps(keep, ensure_ascii=False, indent=2)[:1100])
    except Exception:
        print(body[:900] or out.stderr[:500])
