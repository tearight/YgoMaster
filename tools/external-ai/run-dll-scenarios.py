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
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "JevApp"))
from jev_app.bridge import BridgeClient


def scenario_checks(summary, records, scenario, native_text="", app_text=""):
    if summary is None or scenario not in ("discard-two", "twin-target", "chain-cost", "deck-order"):
        return {}
    applied = [record for record in records if record["state"] == "applied"]
    if scenario == "deck-order":
        ordered = [record for record in applied if record["request"]["observation"].get("selectionContext", {}).get("role") == "deck_order"]
        if not ordered:
            return {"ordered_list_applied": False}
        record = ordered[0]; req = record["request"]
        by_id = {choice["actionId"]: choice["cardReferences"][0] for choice in req["choices"]}
        selected = record["decision"]["actionIds"]
        selected_uids = [by_id[key]["uniqueId"] for key in selected]
        snapshots = summary["deckOrderSnapshots"]
        before = next((row["uniqueIds"] for row in snapshots if row["sequence"] == req["requestSequence"]), [])
        after = next((row["uniqueIds"] for row in snapshots if row["sequence"] > req["requestSequence"]), [])
        later = [row["request"] for row in applied if row["request"]["requestSequence"] > req["requestSequence"]]
        questions = [json.loads(line[9:]) for line in app_text.splitlines() if line.startswith("QUESTION ")]
        rendered = next((row for row in questions if row["selection"]["role"] == "deck_order"), None)
        parent = req["observation"]["selectionContext"].get("parentDecisionId")
        source = req["observation"]["selectionContext"].get("sourceCards", [])
        return {"ordered_list_applied": True,
                "three_distinct_cards_in_full_order": len(selected_uids) == len(set(selected_uids)) == 3 and set(selected) == set(by_id),
                "non_default_order_chosen": selected != list(by_id),
                "selected_order_became_deck_top": bool(after) and after[:3] == selected_uids,
                "other_deck_cards_kept_order": bool(before) and len(before) == len(after) and before[3:] == after[3:],
                "first_ranked_card_drawn_next_turn": bool(selected_uids) and any(row["observation"]["turn"] > req["observation"]["turn"]
                    and any(card.get("uniqueId") == selected_uids[0] and card["player"] == req["actor"] and card.get("position") == 13
                            for card in row["observation"]["cards"]) for row in later),
                "six_top_first_choices_rendered": rendered is not None and len(rendered["criteria"]) == 6
                    and all(text.startswith("덱 맨 위부터 이 순서로 놓는다: ") for text in rendered["criteria"].values()),
                "source_activation_linked": len(source) == 1 and any(row["request"]["decisionId"] == parent
                    and any(choice["actionId"] in row["decision"]["actionIds"] and choice["semanticKind"] == "activate"
                        and choice["cardReferences"][0].get("uniqueId") == source[0].get("uniqueId") for choice in row["request"]["choices"])
                    for row in applied),
                "private_deck_order_excluded_from_requests": all("deckOrderSnapshots" not in row["request"]["observation"]
                    and all("uniqueId" not in card and "cardId" not in card for card in row["request"]["observation"]["cards"]
                            if card.get("position") == 15) for row in records)}
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
    if scenario == "chain-cost":
        # This fixed DLL fixture proves resolution, rather than treating accepted input as success.
        activations = [(record["request"], choice) for record in applied for choice in record["request"]["choices"]
                       if choice["actionId"] in record["decision"]["actionIds"] and choice["semanticKind"] == "activate"
                       and any(card.get("cardId") == 4862 for card in choice["cardReferences"])]
        req, action = activations[0] if activations else ({}, {})
        source = req.get("observation", {}).get("selectionContext", {}).get("sourceCards", [])
        spell_uid = source[0].get("uniqueId") if len(source) == 1 and source[0].get("cardId") == 4812 else None
        trap_uid = action.get("cardReferences", [{}])[0].get("uniqueId")
        events = [tuple(map(int, line.split()[1:])) for line in native_text.splitlines() if line.startswith("EVENT ")]
        start = next((i for i, event in enumerate(events) if event[0] == 52 and event[3] >> 16 == spell_uid), None)
        end = next((i for i in range((start or 0) + 1, len(events))
                    if start is not None and events[i][0] == 86 and events[i][3] == events[start][3]), None)
        window = events[start:end + 1] if start is not None and end is not None else []
        resolution = [event[3] >> 16 for event in window if event[0] == 53]
        two_links = [record["request"] for record in applied
                     if [link.get("cardReferences", [{}])[0].get("uniqueId")
                         for link in record["request"]["observation"].get("chain", []) if link.get("cardReferences")]
                     == [spell_uid, trap_uid]]
        later = [record["request"] for record in applied if two_links
                 and record["request"]["requestSequence"] > two_links[0]["requestSequence"]]
        grave_cards = {(card["player"], card["uniqueId"]) for card in summary["finalCards"] if card["position"] == 16}
        return {"response_source_is_opposing_spell": spell_uid is not None and source[0]["player"] != req["actor"],
                "two_public_chain_sources_in_order": bool(two_links) and len(two_links[0]["observation"]["chain"]) == 2
                    and two_links[0]["observation"]["chainComplete"] and all(link["sourceLocated"] and link["order"] == i + 1
                    for i, link in enumerate(two_links[0]["observation"]["chain"])),
                "counter_trap_resolved_before_spell": bool(window) and resolution == [trap_uid, spell_uid],
                "spell_disabled_and_destroyed": all(any(event[0] == kind and event[3] == spell_uid for event in window) for kind in (36, 32)),
                "negated_spell_did_not_draw": bool(window) and not any(event[0] == 68 for event in window),
                "later_spell_proves_draw_detector_active": end is not None and any(event[0] == 68 for event in events[end + 1:]),
                "cost_card_reached_grave": bool(discards) and (discards[0][1]["player"], discards[0][1]["uniqueId"]) in grave_cards,
                "counter_trap_and_spell_reached_grave": spell_uid is not None and bool(activations)
                    and (req["actor"], trap_uid) in grave_cards and (source[0]["player"], spell_uid) in grave_cards,
                "resolved_chain_cleared": bool(later) and later[0]["observation"].get("chain") == [],
                "next_chain_starts_at_one": any(len(row["observation"].get("chain", [])) == 1
                    and row["observation"]["chain"][0]["order"] == 1 for row in later)}
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
    parser.add_argument("--restart-app-after", type=int, default=0, help="test-only mock app restart after this many applied inputs")
    parser.add_argument("--scenario", choices=("basic", "spell-target", "discard-two", "twin-target", "chain-cost", "deck-order"), default="basic")
    args = parser.parse_args()
    if not 1 <= args.decisions <= 100 or not 5 <= args.timeout <= 600:
        parser.error("decisions must be 1..100 and timeout must be 5..600 seconds")
    if args.restart_app_after and (args.provider != "mock" or args.scenario != "basic" or not 1 <= args.restart_app_after < args.decisions):
        parser.error("app restart requires mock/basic and a threshold below the decision count")
    if not Path(args.dll).is_file() or not Path(args.data).is_dir() or (args.loader and not Path(args.loader).is_file()):
        parser.error("DLL, CardData directory, and optional loader must exist")
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
    for source in ("YgoMasterServer/ExternalAi/DecisionStore.cs", "YgoMasterServer/ExternalAi/DecisionBridge.cs", "YgoMasterServer/Program.cs"):
        source_hashes[source] = hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
    server_hash = hashlib.sha256((ROOT / "YgoMaster/YgoMaster.exe").read_bytes()).hexdigest()
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
            if args.provider == "mock" and (args.restart_app_after or args.scenario in ("discard-two", "twin-target", "chain-cost", "deck-order")):
                app_command = [sys.executable, "-u", str(ROOT / "tests/ExternalAi/ScenarioApp.py"), "--scenario", args.scenario]
            app = subprocess.Popen([*app_command, "--bridge-config", str(config), "--card-data", args.data],
                                   cwd=ROOT / "JevApp", stdout=app_log, stderr=app_log, env=child_env)
            processes.append(app)
            restart_ids = []
            native_path = output / "native.log"
            with native_path.open("wb") as native_log:
                native_process = subprocess.Popen([str(host), args.dll, args.data, str(config), str(args.decisions), str(args.timeout), args.scenario,
                                                  "ui-waits-for-input" if args.ui_waits_for_input else "no-ui", str(Path(args.loader).resolve()) if args.loader else ""],
                                                 stdout=native_log, stderr=subprocess.STDOUT)
                processes.append(native_process)
                limit = time.monotonic() + args.timeout + 15
                while native_process.poll() is None:
                    if time.monotonic() >= limit:
                        raise TimeoutError("native host timed out")
                    if args.restart_app_after and not restart_ids:
                        observed_requests = []
                        for line in native_path.read_text(encoding="utf-8", errors="replace").splitlines():
                            if line.startswith("REQUEST "):
                                try:
                                    observed_requests.append(json.loads(line[8:]))
                                except json.JSONDecodeError:
                                    pass  # The native writer may still be completing its last line.
                        applied_ids = []
                        for req in observed_requests:
                            try:
                                if bridge.get(req["decisionId"])["state"] == "applied":
                                    applied_ids.append(req["decisionId"])
                            except HTTPError as error:
                                # The engine can log a new request before its worker publishes it.
                                try:
                                    if error.code != 409 or json.loads(error.read())["error"] != "unknown_decision":
                                        raise
                                finally:
                                    error.close()
                        if len(applied_ids) >= args.restart_app_after:
                            restart_ids = applied_ids[:args.restart_app_after]
                            app.terminate(); app.wait(timeout=5)
                            app_log.write("APP_RESTART\n"); app_log.flush()
                            app = subprocess.Popen([*app_command, "--bridge-config", str(config), "--card-data", args.data],
                                                   cwd=ROOT / "JevApp", stdout=app_log, stderr=app_log, env=child_env)
                            processes.append(app)
                    time.sleep(.1)
                native_code = native_process.wait()
            text = native_path.read_text(encoding="utf-8", errors="replace")
            summary = next((json.loads(line[8:]) for line in text.splitlines() if line.startswith("SUMMARY ")), None)
            records = [] if summary is None else [bridge.get(r["decisionId"]) for r in summary["requests"]]
            checks = scenario_checks(summary, records, args.scenario, text, (output / "app.log").read_text(encoding="utf-8"))
            restart_evidence = None
            if args.restart_app_after:
                after_restart = (output / "app.log").read_text(encoding="utf-8").partition("APP_RESTART\n")[2]
                questions = [json.loads(line[9:]) for line in after_restart.splitlines() if line.startswith("QUESTION ")]
                restored_ids = questions[0]["historyDecisionIds"] if questions else []
                checks.update(separate_app_process_restarted=bool(restart_ids),
                              applied_history_restored_after_restart=bool(restart_ids) and set(restart_ids).issubset(restored_ids))
                restart_evidence = {"appliedBeforeRestart": restart_ids, "firstProviderHistoryAfterRestart": restored_ids}
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
            exit_code = native_code if native_code else (0 if all(checks.values()) else 4)
            scope = "isolated normal duel; production decoder/controller/worker and Hook<T> with host view/SysAct adapters" if args.loader else "isolated normal duel, production decoder/controller/worker, no UI or injected hook"
            evidence = {"scope": scope, "loaderSha256": hashlib.sha256(Path(args.loader).read_bytes()).hexdigest() if args.loader else None,
                        "provider": args.provider, "scenario": args.scenario, "exitCode": exit_code, "sourceHashes": source_hashes,
                        "serverExecutableSha256": server_hash, "appRestart": restart_evidence,
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
