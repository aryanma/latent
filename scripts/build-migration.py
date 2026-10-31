"""Package the current study without changing original measurement artifacts."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import zipfile

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE / "experiments/reward-migrations"
PUBLIC = SITE / "data/reward-migrations"


def fingerprint(path):
    return {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}


def included(path):
    return path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store" and path.suffix not in (".pyc", ".pyo")


files = sorted(p for p in ROOT.rglob("*") if included(p) and p.name != "ARTIFACTS.json")
manifest = {"format": "latent-reward-migrations-release/v1", "files": {
    str(p.relative_to(ROOT)): fingerprint(p) for p in files}}
(ROOT / "ARTIFACTS.json").write_text(json.dumps(manifest, indent=2) + "\n")
subprocess.run([sys.executable, str(ROOT / "verify_release.py")], check=True)

for name in ("results.json", "references.json", "inventory.json", "parser-sensitivity.json", "migration-plans.json"):
    if (ROOT / "evaluation" / name).read_bytes() != (PUBLIC / name).read_bytes():
        raise ValueError("Public evidence differs: " + name)
for name in ("browser-fixture.sqlite", "browser-fixture.manifest.json"):
    if (ROOT / "browser-fixture" / name).read_bytes() != (PUBLIC / name).read_bytes():
        raise ValueError("Public fixture differs: " + name)

files.append(ROOT / "ARTIFACTS.json")
archive = PUBLIC / "reproduction.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
    for path in sorted(files):
        info = zipfile.ZipInfo("latent-reward-migrations/" + str(path.relative_to(ROOT)), date_time=(2026, 10, 31, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        output.writestr(info, path.read_bytes(), compresslevel=9)
(PUBLIC / "release.json").write_text(json.dumps({
    "archive": dict(fingerprint(archive), path="reproduction.zip"),
    "manifest": dict(fingerprint(ROOT / "ARTIFACTS.json"), path="../../experiments/reward-migrations/ARTIFACTS.json"),
    "files": len(files), "uncompressed_bytes": sum(p.stat().st_size for p in files),
}, indent=2) + "\n")
print(json.dumps({"archive": str(archive), **fingerprint(archive), "files": len(files)}))
