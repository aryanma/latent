"""Verify complete, independent experiment outputs and write a checksum receipt."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
files = {}
for run in ("run1", "run2"):
    summary = json.loads((root / run / "summary.json").read_text())
    assert summary["total_scored_probes"] == 247
    assert summary["semantic_judge_calls"] == 0
    assert summary["network_attempts"] == 0
    assert summary["failures"] == []
    rows = json.loads((root / run / "results.json").read_text())
    assert all(not p["tool_errors"] for r in rows for p in r["probes"].values())
    assert all(p["fresh_environment_reset_verified"] for r in rows for p in r["probes"].values())
for first in sorted((root / "run1").glob("*.json")):
    a, b = first.read_bytes(), (root / "run2" / first.name).read_bytes()
    assert a == b, f"Nonidentical output: {first.name}"
    files[first.name] = {"byte_identical": True, "sha256": hashlib.sha256(a).hexdigest(), "bytes": len(a)}
status = subprocess.run(["git", "-C", str(root / "upstream"), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
assert status == ""
report = {
    "all_outputs_byte_identical": True,
    "independent_process_runs": 2,
    "scored_probes_per_run": 247,
    "total_scored_probes": 494,
    "model_calls_in_scoring": 0,
    "network_attempts_during_imports_and_scoring": 0,
    "tool_execution_errors": 0,
    "scoring_exceptions": 0,
    "upstream_worktree_clean": True,
    "files": files,
    "audit_script_sha256": hashlib.sha256((root / "run_audit.py").read_bytes()).hexdigest(),
}
(root / "reproducibility.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report, indent=2))
