"""Run the production external AI decoder against an isolated, normally initialized DLL."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "JevApp"))
from jev_app.bridge import BridgeClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll", required=True)
    parser.add_argument("--data", required=True, help="CardData folder; read only")
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", choices=("mock", "jev"), default="mock")
    parser.add_argument("--decisions", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--scenario", choices=("basic", "spell-target"), default="basic")
    args = parser.parse_args()
    if not 1 <= args.decisions <= 100 or not 5 <= args.timeout <= 600:
        parser.error("decisions must be 1..100 and timeout must be 5..600 seconds")
    if args.provider == "jev" and not os.environ.get("JEV_API_KEY"):
        parser.error("JEV_API_KEY is missing from the process environment")
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    host = output / "NativeHost.exe"
    sources = ["ExternalAi/Protocol.cs", "ExternalAi/BridgeConfig.cs", "YgoMasterServer/Lib/MiniJSON.cs",
               "YgoMasterServer/Enums/Duel.cs", "YgoMasterServer/Enums/Misc.cs", "YgoMasterClient/ExternalAi/EngineProfile.cs",
               "YgoMasterClient/ExternalAi/InputSession.cs", "YgoMasterClient/ExternalAi/BridgeWorker.cs",
               "YgoMasterClient/DuelDll.ExternalAi.cs", "tests/ExternalAi/NativeHost.cs"]
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    source_hashes = {source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest() for source in sources}
    subprocess.run([str(compiler), "/nologo", "/unsafe", "/platform:x64", "/r:System.Web.Extensions.dll", f"/out:{host}",
                    *(str(ROOT / source) for source in sources)], cwd=ROOT, check=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    (output / "external-ai.token").write_text(base64.b64encode(os.urandom(32)).decode())
    config = output / "ExternalAi.local.json"
    config.write_text(json.dumps({"enabled": True, "prefix": f"http://127.0.0.1:{port}/", "tokenFile": "external-ai.token", "deadlineSeconds": 120}))
    bridge = BridgeClient(config)
    processes = []
    with (output / "server.log").open("w") as server_log, (output / "app.log").open("w", encoding="utf-8") as app_log:
        try:
            server = subprocess.Popen([str(ROOT / "YgoMaster/YgoMaster.exe"), "--external-ai-bridge-only", "--external-ai-config", str(config)], stdout=server_log, stderr=server_log)
            processes.append(server)
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("bridge exited; see server.log")
                try:
                    bridge.pending(); break
                except OSError:
                    time.sleep(.05)
            else:
                raise RuntimeError("bridge readiness timed out")
            child_env = dict(os.environ, PYTHONIOENCODING="utf-8")
            app = subprocess.Popen([sys.executable, "-u", "-m", "jev_app", "--bridge-config", str(config), "--provider", args.provider,
                                    "--card-data", args.data], cwd=ROOT / "JevApp", stdout=app_log, stderr=app_log, env=child_env)
            processes.append(app)
            completed = subprocess.run([str(host), args.dll, args.data, str(config), str(args.decisions), str(args.timeout), args.scenario],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.timeout + 15)
            text = completed.stdout.decode("utf-8", errors="replace")
            (output / "native.log").write_text(text, encoding="utf-8")
            summary = next((json.loads(line[8:]) for line in text.splitlines() if line.startswith("SUMMARY ")), None)
            records = [] if summary is None else [bridge.get(r["decisionId"]) for r in summary["requests"]]
            evidence = {"scope": "isolated normal duel, production decoder/controller/worker, no UI or injected hook",
                        "provider": args.provider, "scenario": args.scenario, "exitCode": completed.returncode, "sourceHashes": source_hashes,
                        "native": summary, "bridgeRecords": records}
            (output / "result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"exitCode": completed.returncode, "nativeConsumed": len(summary["consumedIds"]) if summary else 0,
                              "serverApplied": sum(r["state"] == "applied" for r in records), "output": str(output)}))
            return completed.returncode
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
