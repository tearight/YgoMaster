"""Package only the external AI deliverables; exclude credentials and game assets."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    files = [ROOT / p for p in (
        "YgoMaster/YgoMaster.exe", "YgoMaster/YgoMaster.exe.config", "YgoMaster/YgoMasterClient.exe",
        "YgoMaster/YgoMasterClient.exe.config", "ExternalAi.example.json", "LICENSE",
        "tools/external-ai/Setup-ExternalAi.ps1", "tools/external-ai/Start-ExternalAiBridge.ps1",
        "tools/external-ai/Start-JevApp.ps1", "Docs/external-ai/README.md", "Docs/external-ai/protocol.md",
        "Docs/external-ai/coverage.md", "Docs/external-ai/validation-summary.json")]
    files += sorted((ROOT / "JevApp/jev_app").glob("*.py"))
    missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    if missing:
        parser.error("required build/package files missing: " + ", ".join(missing))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {"commit": commit, "stage": "experimental; real Jev and injected UI integration not yet verified",
                "files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    manifest["files"]["START-HERE.txt"] = hashlib.sha256((ROOT / "Docs/external-ai/START-HERE.txt").read_bytes()).hexdigest()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.write(ROOT / "Docs/external-ai/START-HERE.txt", "START-HERE.txt")
        archive.writestr("delivery-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"output": str(output), "fileCount": len(files) + 2, "bytes": output.stat().st_size}))


if __name__ == "__main__":
    main()
