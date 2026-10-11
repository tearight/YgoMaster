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


def scenario_checks(summary, records, scenario):
    if summary is None or scenario not in ("discard-two", "twin-target"):
        return {}
    applied = [record for record in records if record["state"] == "applied"]
    def selections(role):
        values = []
        for record in applied:
            req = record["request"]
            if req["observation"].get("selectionContext", {}).get("role") != role:
                continue
            selected = set(record["decision"]["actionIds"])
            for choice in req["choices"]:
                if choice["actionId"] in selected:
                    values.append((req, choice["cardReferences"][0]))
        return values
    discards = selections("discard")
    grave = {card["uniqueId"] for card in summary["finalCards"] if card["position"] == 16}
    if scenario == "discard-two":
        chosen = discards[:2]
        return {"two_distinct_cards_chosen": len({card["uniqueId"] for req, card in chosen}) == 2,
                "remaining_count_decreased": [req["observation"]["selectionContext"]["remainingCount"] for req, card in chosen] == [2, 1],
                "non_default_indices_chosen": len(chosen) == 2 and all(card["index"] > 0 for req, card in chosen),
                "chosen_cards_reached_grave": len(chosen) == 2 and all(card["uniqueId"] in grave for req, card in chosen)}
    targets = selections("target")[:2]
    more = [record["request"]["requestSequence"] for record in applied if record["decision"]["actionIds"] == ["yesno_1"]]
    return {"cost_card_reached_grave": bool(discards) and discards[0][1]["uniqueId"] in grave,
            "two_distinct_targets_chosen": len({card["uniqueId"] for req, card in targets}) == 2,
            "both_targets_reached_grave": len(targets) == 2 and all(card["uniqueId"] in grave for req, card in targets),
            "another_target_confirmed_between_choices": len(targets) == 2 and any(targets[0][0]["requestSequence"] < seq < targets[1][0]["requestSequence"] for seq in more)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll", required=True)
    parser.add_argument("--data", required=True, help="CardData folder; read only")
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", choices=("mock", "jev"), default="mock")
    parser.add_argument("--decisions", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--ui-waits-for-input", action="store_true", help="simulate a view still waiting for its input button")
    parser.add_argument("--loader", help="existing YgoMasterLoader.dll; enables production Hook<T> in the owned host")
    parser.add_argument("--scenario", choices=("basic", "spell-target", "discard-two", "twin-target"), default="basic")
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
               "YgoMasterClient/DuelDll.ExternalAi.cs", "YgoMasterClient/Hook.cs", "tests/ExternalAi/HookHost.cs", "tests/ExternalAi/NativeHost.cs"]
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    source_hashes = {source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest() for source in sources}
    for path in [*sorted((ROOT / "JevApp/jev_app").glob("*.py")), ROOT / "tests/ExternalAi/ScenarioApp.py", Path(__file__)]:
        source_hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    source_hashes["YgoMasterClient/DuelDll.cs"] = hashlib.sha256((ROOT / "YgoMasterClient/DuelDll.cs").read_bytes()).hexdigest()
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
            app_command = [sys.executable, "-u", "-m", "jev_app", "--provider", args.provider]
            if args.provider == "mock" and args.scenario in ("discard-two", "twin-target"):
                app_command = [sys.executable, "-u", str(ROOT / "tests/ExternalAi/ScenarioApp.py"), "--scenario", args.scenario]
            app = subprocess.Popen([*app_command, "--bridge-config", str(config), "--card-data", args.data],
                                   cwd=ROOT / "JevApp", stdout=app_log, stderr=app_log, env=child_env)
            processes.append(app)
            completed = subprocess.run([str(host), args.dll, args.data, str(config), str(args.decisions), str(args.timeout), args.scenario,
                                        "ui-waits-for-input" if args.ui_waits_for_input else "no-ui", str(Path(args.loader).resolve()) if args.loader else ""],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.timeout + 15)
            text = completed.stdout.decode("utf-8", errors="replace")
            (output / "native.log").write_text(text, encoding="utf-8")
            summary = next((json.loads(line[8:]) for line in text.splitlines() if line.startswith("SUMMARY ")), None)
            records = [] if summary is None else [bridge.get(r["decisionId"]) for r in summary["requests"]]
            checks = scenario_checks(summary, records, args.scenario)
            if args.ui_waits_for_input and summary is not None:
                checks.update(submitted_input_busy_released=summary["submittedUiBusyOverrides"] > 0,
                              no_submitted_input_ui_wait=summary["submittedUiBusyCalls"] == 0)
            if args.loader and summary is not None:
                checks.update(real_native_hooks_installed=summary["nativeHookCount"] == 11,
                              native_sysact_intercepted=summary["nativeSysActCalls"] > 0,
                              competing_ui_input_suppressed=summary["suppressedUiInputs"] > 0,
                              view_callbacks_preserved=summary["originalViewCalls"] > 0,
                              target_cpu_evaluators_not_entered=all(counts[1] == 0 for counts in summary["cpuEvaluatorCalls"].values()),
                              cpu_counter_actors_known=all(counts[2] == 0 for counts in summary["cpuEvaluatorCalls"].values()))
                if args.scenario == "basic" and args.decisions >= 16:
                    checks["other_cpu_proves_counters_active"] = sum(counts[0] for counts in summary["cpuEvaluatorCalls"].values()) > 0
            exit_code = completed.returncode if completed.returncode else (0 if all(checks.values()) else 4)
            scope = "isolated normal duel; production decoder/controller/worker and Hook<T> with host view/SysAct adapters" if args.loader else "isolated normal duel, production decoder/controller/worker, no UI or injected hook"
            evidence = {"scope": scope, "loaderSha256": hashlib.sha256(Path(args.loader).read_bytes()).hexdigest() if args.loader else None,
                        "provider": args.provider, "scenario": args.scenario, "exitCode": exit_code, "sourceHashes": source_hashes,
                        "hostCompileSources": sources,
                        "native": summary, "bridgeRecords": records, "scenarioChecks": checks}
            (output / "result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"exitCode": exit_code, "nativeConsumed": len(summary["consumedIds"]) if summary else 0,
                              "serverApplied": sum(r["state"] == "applied" for r in records), "output": str(output)}))
            return exit_code
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
