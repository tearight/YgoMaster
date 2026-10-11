using System;
using System.Collections.Generic;
using System.Linq;
using System.IO;
using System.Threading;
using YgoMaster;
using YgoMaster.ExternalAi;
using YgoMasterClient.ExternalAi;

namespace YgoMasterClient
{
    unsafe static partial class DuelDll
    {
        static EngineProfile externalAiProfile;
        static BridgeConfig externalAiConfig;
        static BridgeWorker externalAiWorker;
        static InputSession externalAiInput;
        static Dictionary<string, object> externalAiLastApplied;
        static IList<string> externalAiSelected;
        static Dictionary<string, object> externalAiActiveChoice;
        static string externalAiActiveDecision;
        static string externalAiDuel;
        static long externalAiGeneration, externalAiSequence;
        static bool externalAiEnabled, externalAiCpuChanged;
        static Queue<object> externalAiEvents = new Queue<object>();

        static void ExternalAiInit(IntPtr module, string dllPath = null)
        {
            if (string.IsNullOrEmpty(ClientSettings.ExternalAiConfigPath)) return;
            try
            {
                externalAiConfig = BridgeConfig.Load(ClientSettings.ExternalAiConfigPath);
                if (externalAiConfig.Enabled)
                {
                    externalAiProfile = new EngineProfile(module, dllPath ?? Path.Combine("masterduel_Data", "Plugins", "x86_64", "duel.dll"));
                    externalAiWorker = new BridgeWorker(externalAiConfig);
                }
            }
            catch { Console.WriteLine("External AI disabled: config or DLL profile could not be verified"); }
        }
        static void ExternalAiBegin(GameMode mode)
        {
            externalAiGeneration++; externalAiSequence = 0; externalAiDuel = Guid.NewGuid().ToString("N");
            externalAiInput = null; externalAiLastApplied = null; externalAiSelected = null;
            externalAiActiveChoice = null; externalAiActiveDecision = null;
            externalAiEvents.Clear(); externalAiCpuChanged = false;
            externalAiEnabled = externalAiWorker != null && mode == GameMode.SoloSingle && !IsPvpDuel && !IsPvpSpectator;
        }
        static int ExternalAiPlayerType(int player, int type)
        {
            if (externalAiEnabled && player == RivalID && type == (int)DuelPlayerType.CPU)
            { externalAiCpuChanged = true; return (int)DuelPlayerType.Human; }
            return type;
        }
        static bool ExternalAiOwnsInput
        {
            get { return externalAiEnabled && externalAiInput != null && !externalAiInput.Finished; }
        }
        static void ExternalAiEnd()
        {
            // End is signalled from the game lifecycle; native work is not accessed here.
            if (externalAiWorker != null && externalAiDuel != null)
            {
                externalAiWorker.Send("v1/duels/end", new Dictionary<string, object> {
                    {"protocolVersion", 1}, {"duelId", externalAiDuel}, {"duelGeneration", externalAiGeneration},
                    {"decisionId", "duel-end"}, {"actor", RivalID}
                });
            }
            externalAiEnabled = false; externalAiInput = null;
        }
        static void ExternalAiAck(string state, string reason)
        {
            if (externalAiInput == null || externalAiInput.Finished) return;
            if (state == "applied") externalAiLastApplied = externalAiInput.Request;
            externalAiWorker.Send("v1/acks", externalAiInput.Finish(state, reason));
            externalAiInput = null;
        }
        static void ExternalAiOnRunEffect(int id, int p1, int p2, int p3)
        {
            if (!externalAiEnabled || !externalAiCpuChanged || externalAiProfile == null || !externalAiProfile.Ready) return;
            // Discard/Update/Close are view notifications from the hand-selection
            // state machine (5d7990), not DlgSetResult requests. Selection arrives as WaitInput.
            bool discardView = id == 55 && (p1 == 16 || p1 == 18 || p1 == 19);
            bool input = id == 4 || (id == 55 && !discardView) || id == 56;
            if (!input)
            {
                if (externalAiInput != null && externalAiInput.Submitted && !externalAiProfile.Pending(externalAiInput.EffectId))
                    ExternalAiAck("applied", "engine_request_consumed");
                // Parameters can contain private card information; only the public event kind is retained.
                externalAiEvents.Enqueue(new Dictionary<string, object> { {"event", ((DuelViewType)id).ToString()} });
                while (externalAiEvents.Count > 64) externalAiEvents.Dequeue();
                return;
            }
            int actor = externalAiProfile.Actor(id);
            if (actor != RivalID) return;
            string marker = externalAiProfile.Marker(id);
            if (externalAiInput != null)
            {
                if (externalAiInput.Submitted) ExternalAiAck("applied", "next_engine_input_request");
                else if (externalAiInput.Marker == marker && externalAiInput.EffectId == id) return;
                else ExternalAiAck("cancelled", "request_replaced");
            }
            try { ExternalAiBuildRequest(id, p1, p2, p3, actor, marker); }
            catch
            {
                Console.WriteLine("External AI request decoder failed; CPU control disabled for this duel");
                ExternalAiDisableOnEngineThread();
            }
        }
        static bool ExternalAiControlsBusy(int effectId)
        {
            // The list producer emits RunList (56), but polls IsBusyEffect with RunDialog (55).
            return ExternalAiOwnsInput &&
                (externalAiInput.EffectId == effectId || (externalAiInput.EffectId == 56 && effectId == 55));
        }
        static int ExternalAiBusy(int effectId) { return ExternalAiControlsBusy(effectId) && externalAiInput.Hold ? 1 : 0; }
        static void ExternalAiBeforeSysAct()
        {
            if (!externalAiEnabled || externalAiInput == null) return;
            if (Protocol.Deadline(externalAiInput.Request) <= DateTime.UtcNow)
            {
                ExternalAiAck("rejected", "deadline_without_verified_consumption");
                ExternalAiDisableOnEngineThread();
                return;
            }
            Dictionary<string, object> record;
            while (externalAiWorker.TryRead(out record))
            {
                if (externalAiInput == null) break;
                Dictionary<string, object> request = Protocol.Object(record["request"]);
                if (Protocol.Text(request, "decisionId") != Protocol.Text(externalAiInput.Request, "decisionId")) continue;
                string state = Protocol.Text(record, "state");
                if (state == "accepted" && !externalAiInput.Submitted)
                {
                    InputSession session = externalAiInput;
                    Dictionary<string, object> decision = Protocol.Object(record["decision"]);
                    lock (ActionsToRunInNextSysAct) ActionsToRunInNextSysAct.Add(delegate()
                    {
                        if (session != externalAiInput || !externalAiEnabled) return;
                        try
                        {
                            if (externalAiProfile.Actor(session.EffectId) != RivalID || externalAiProfile.Marker(session.EffectId) != session.Marker)
                                throw new ProtocolException("engine_request_changed", 409);
                            session.Apply(decision, DateTime.UtcNow);
                        }
                        catch { ExternalAiAck("rejected", "engine_input_validation_failed"); ExternalAiDisableOnEngineThread(); }
                    });
                }
                else if (state == "cancelled" || state == "expired" || state == "rejected")
                { externalAiInput = null; ExternalAiDisableOnEngineThread(); }
            }
        }
        static void ExternalAiAfterSysAct(int result)
        {
            if (externalAiInput != null && externalAiInput.Submitted &&
                (result == 1 || !externalAiProfile.Pending(externalAiInput.EffectId) || externalAiProfile.Marker(externalAiInput.EffectId) != externalAiInput.Marker))
                ExternalAiAck("applied", "engine_request_consumed");
        }
        static void ExternalAiDisableOnEngineThread()
        {
            if (externalAiCpuChanged) hookDLL_DuelSetPlayerType.Original(RivalID, (int)DuelPlayerType.CPU);
            externalAiCpuChanged = false; externalAiEnabled = false;
        }
        static Dictionary<string, object> ExternalAiCard(int player, int pos, int index, int observer)
        {
            string zone = pos <= 12 ? "필드" : new[] { "패", "엑스트라 덱", "덱", "묘지", "제외 구역" }[pos - 13];
            bool visible = (player == observer && pos != 15) || pos == 16 ||
                (pos == 13 && hookDLL_DuelGetHandCardOpen.Original(player, index)) ||
                (pos <= 12 && hookDLL_DuelGetCardFace.Original(player, pos, index) == 1);
            Dictionary<string, object> card = new Dictionary<string, object> {
                {"player", player}, {"position", pos}, {"zone", zone}, {"index", index}, {"identityVisible", visible}
            };
            if (visible)
            {
                PvpBasicVal value = default(PvpBasicVal); hookDLL_DuelGetCardBasicVal.Original(player, pos, index, ref value);
                card["cardId"] = (int)(ushort)value.CardID; card["uniqueId"] = hookDLL_DuelGetCardUniqueID.Original(player, pos, index);
                card["attack"] = value.Atk; card["defense"] = value.Def; card["level"] = (int)value.Level;
            }
            if (pos <= 12) card["faceUp"] = hookDLL_DuelGetCardFace.Original(player, pos, index) == 1;
            return card;
        }
        static void ExternalAiBuildRequest(int id, int p1, int p2, int p3, int actor, string marker)
        {
            List<object> choices = new List<object>();
            Dictionary<string, Action> actions = new Dictionary<string, Action>();
            Dictionary<string, int> listIndices = new Dictionary<string, int>();
            bool multi = false;
            Dictionary<string, object> limits = new Dictionary<string, object> {
                {"min", 1}, {"max", 1}, {"ordered", false}, {"allowEmpty", false}, {"legality", "single"}
            };
            Action<string, string, Dictionary<string, object>, List<object>, Action> add = (key, kind, args, cards, apply) =>
            {
                choices.Add(new Dictionary<string, object> { {"actionId", key}, {"semanticKind", kind}, {"text", ""},
                    {"arguments", args}, {"cardReferences", cards} }); actions[key] = apply;
            };
            string reason = null;
            Dictionary<string, object> selectionContext = new Dictionary<string, object> { {"role", "unknown"}, {"parentDecisionId", null} };
            if (id == 4)
            {
                if (p1 == (int)DuelMenuActType.MainPhase || p1 == (int)DuelMenuActType.BattlePhase)
                { externalAiActiveChoice = null; externalAiActiveDecision = null; }
                if (p1 == (int)DuelMenuActType.DrawPhase)
                {
                    uint mask = hookDLL_DuelComGetCommandMask.Original(actor, 15, 0);
                    if ((mask & (1u << (int)DuelCommandType.Draw)) != 0)
                        add("draw", "draw_card", new Dictionary<string, object>(), new List<object>(),
                            () => hookDLL_DuelComDoCommand.Original(actor, 15, 0, (int)DuelCommandType.Draw));
                }
                else if (p1 == (int)DuelMenuActType.Location)
                {
                    List<object> references = new List<object>();
                    if (externalAiLastApplied != null && externalAiSelected != null)
                        foreach (object value in Protocol.List(externalAiLastApplied, "choices"))
                        {
                            Dictionary<string, object> choice = Protocol.Object(value);
                            if (!externalAiSelected.Contains(Protocol.Text(choice, "actionId"))) continue;
                            foreach (object cardValue in Protocol.List(choice, "cardReferences"))
                            {
                                Dictionary<string, object> card = Protocol.Object(cardValue);
                                object uid;
                                if (card.TryGetValue("uniqueId", out uid) && Convert.ToInt32(uid) == p2)
                                    references.Add(card);
                            }
                        }
                    if (references.Count > 0)
                    {
                        selectionContext["role"] = "placement";
                        selectionContext["parentDecisionId"] = Protocol.Text(externalAiLastApplied, "decisionId");
                    }
                    for (int pos = 0; pos <= 12; pos++) if (externalAiProfile.AllowsLocation(actor, pos))
                    {
                        int location = pos;
                        add("location_" + pos, "place_card", new Dictionary<string, object> { {"position", pos} }, references,
                            () => hookDLL_DuelComDoCommand.Original(actor, location, 0, (int)DuelCommandType.Decide));
                    }
                }
                else if (p1 == (int)DuelMenuActType.LockOn)
                {
                    selectionContext["role"] = "target";
                    if (externalAiActiveChoice != null)
                        foreach (object cardValue in Protocol.List(externalAiActiveChoice, "cardReferences"))
                        {
                            Dictionary<string, object> card = Protocol.Object(cardValue);
                            object cardId;
                            if (card.TryGetValue("cardId", out cardId) && Convert.ToInt32(cardId) == p2)
                            {
                                selectionContext["parentDecisionId"] = externalAiActiveDecision;
                                selectionContext["sourceCards"] = Protocol.List(externalAiActiveChoice, "cardReferences");
                            }
                        }
                    for (int player = 0; player < 2; player++) for (int pos = 0; pos <= 12; pos++)
                    {
                        if (hookDLL_DuelGetCardNum.Original(player, pos) == 0 ||
                            (hookDLL_DuelComGetCommandMask.Original(player, pos, 0) & (1u << (int)DuelCommandType.Decide)) == 0) continue;
                        int owner = player, location = pos;
                        add("target_" + player + "_" + pos, "select_card", new Dictionary<string, object>(),
                            new List<object> { ExternalAiCard(player, pos, 0, actor) },
                            () => {
                                if ((hookDLL_DuelComGetCommandMask.Original(owner, location, 0) & (1u << (int)DuelCommandType.Decide)) == 0)
                                    throw new InvalidOperationException("target_no_longer_legal");
                                hookDLL_DuelComDoCommand.Original(owner, location, 0, (int)DuelCommandType.Decide);
                            });
                    }
                }
                else if (p1 == (int)DuelMenuActType.Selection && p2 >= 32 && p2 <= 34)
                {
                    // 5d7990 selects one eligible hand card per WaitInput, then decreases
                    // this count. It does not consume a dialog bitmask or a ranked list.
                    int remaining = externalAiProfile.Read16(0x3dbc);
                    if (remaining < 1 || remaining > 128) throw new InvalidOperationException("invalid_discard_count");
                    selectionContext["role"] = "discard";
                    selectionContext["remainingCount"] = remaining;
                    int count = hookDLL_DuelGetCardNum.Original(actor, 13);
                    if (count < 1 || count > 128) throw new InvalidOperationException("invalid_hand_count");
                    for (int index = 0; index < count; index++)
                    {
                        if ((hookDLL_DuelComGetCommandMask.Original(actor, 13, index) & (1u << (int)DuelCommandType.Decide)) == 0) continue;
                        int itemIndex = index, uniqueId = hookDLL_DuelGetCardUniqueID.Original(actor, 13, index);
                        add("discard_" + index, "discard_card", new Dictionary<string, object>(),
                            new List<object> { ExternalAiCard(actor, 13, index, actor) }, () => {
                                if (hookDLL_DuelGetCardUniqueID.Original(actor, 13, itemIndex) != uniqueId ||
                                    (hookDLL_DuelComGetCommandMask.Original(actor, 13, itemIndex) & (1u << (int)DuelCommandType.Decide)) == 0)
                                    throw new InvalidOperationException("discard_no_longer_legal");
                                hookDLL_DuelComDoCommand.Original(actor, 13, itemIndex, (int)DuelCommandType.Decide);
                            });
                    }
                }
                else if (p1 != 2 && p1 != 3 && p1 != 4 && p1 != 5) reason = "unsupported_menu_type";
                else
                {
                    string[] kinds = { "attack", null, "special_summon", "activate", "summon", "flip_summon", "set_monster", "set_spell", "pendulum_summon", "change_position", "change_position" };
                    for (int pos = 0; pos < 18; pos++)
                    {
                        int count = hookDLL_DuelGetCardNum.Original(actor, pos);
                        if (count < 0 || count > 128) throw new InvalidOperationException("invalid_card_count");
                        for (int index = 0; index < count; index++)
                        {
                            uint mask = hookDLL_DuelComGetCommandMask.Original(actor, pos, index);
                            for (int command = 0; command < kinds.Length; command++)
                            {
                                if (kinds[command] == null || (mask & (1u << command)) == 0) continue;
                                int location = pos, itemIndex = index, commandId = command;
                                Dictionary<string, object> card = ExternalAiCard(actor, pos, index, actor);
                                Dictionary<string, object> arguments = new Dictionary<string, object>();
                                if (command == 9 || command == 10) arguments["positionName"] = command == 9 ? "앞면 공격 표시" : "앞면 수비 표시";
                                add("command_" + pos + "_" + index + "_" + command, kinds[command], arguments,
                                    new List<object> { card }, () => hookDLL_DuelComDoCommand.Original(actor, location, itemIndex, commandId));
                            }
                        }
                    }
                    uint phaseMask = hookDLL_DuelComGetMovablePhase.Original();
                    string[] phases = { "드로우 페이즈", "스탠바이 페이즈", "메인 페이즈 1", "배틀 페이즈", "메인 페이즈 2", "엔드 페이즈" };
                    for (int phase = 0; phase < phases.Length; phase++) if ((phaseMask & (1u << phase)) != 0)
                    {
                        int selectedPhase = phase;
                        add("phase_" + phase, "phase", new Dictionary<string, object> { {"phaseName", phases[phase]} }, new List<object>(),
                            () => hookDLL_DuelComMovePhase.Original(selectedPhase));
                    }
                    if ((p1 == 4 || p1 == 5) && (p2 == 0 || p2 == 2 || p2 == 3 || p2 == 4))
                        add("decline", "decline", new Dictionary<string, object>(), new List<object>(), () => hookDLL_DuelComCancelCommand.Original());
                }
            }
            else if (id == 55)
            {
                if (p1 == (int)DuelDialogType.Ok)
                {
                    int initial = externalAiProfile.Read32(0x3c9c);
                    if (initial < 0) reason = "unsupported_ok_result";
                    else add("acknowledge", "acknowledge", new Dictionary<string, object>(), new List<object>(),
                        () => hookDLL_DuelDlgSetResult.Original((uint)initial));
                }
                else if (p1 == 7)
                {
                    string[] phases = { "드로우 페이즈", "스탠바이 페이즈", "메인 페이즈 1", "배틀 페이즈", "메인 페이즈 2", "엔드 페이즈" };
                    for (int phase = 0; phase < 6; phase++) if (((uint)p3 & (1u << phase)) != 0)
                    {
                        uint selected = (uint)phase;
                        add("dialog_phase_" + phase, "phase", new Dictionary<string, object> { {"phaseName", phases[phase]} }, new List<object>(),
                            () => hookDLL_DuelDlgSetResult.Original(selected));
                    }
                }
                else if (p1 == (int)DuelDialogType.Effect &&
                    (p2 == (int)DuelDialogEffectType.All || p2 == (int)DuelDialogEffectType.More))
                {
                    // Effect's p2 is DialogEffectType, not a DLG string ID.
                    add("effect_no", "decline", new Dictionary<string, object> { {"effectPromptType", p2} },
                        new List<object>(), () => hookDLL_DuelDlgSetResult.Original(0));
                    add("effect_yes", "check_effects", new Dictionary<string, object> { {"effectPromptType", p2} },
                        new List<object>(), () => hookDLL_DuelDlgSetResult.Original(1));
                }
                else if (p1 == (int)DuelDialogType.YesNo)
                {
                    int count = externalAiProfile.Read32(0x3ca0);
                    List<object> parts = new List<object>();
                    if (count < 0 || count > 4) reason = "unsupported_mixed_dialog_text";
                    else for (int index = 0; index < count; index++)
                    {
                        uint mixed = (uint)externalAiProfile.Read32(0x3ca4 + index * 4);
                        parts.Add(new Dictionary<string, object> { {"type", (int)(mixed >> 28)}, {"value", (int)(mixed & 0x0fffffffu)} });
                    }
                    // p2 is the actual Yes/No question. The mix buffer is its preceding
                    // explanation; e.g. "Twin Twisters is activated" precedes DLG 33.
                    if (reason == null) for (uint value = 0; value < 2; value++)
                    {
                        uint selected = value;
                        add("yesno_" + value, value == 0 ? "no" : "yes", new Dictionary<string, object> { {"textId", p2}, {"textGroup", "DLG"}, {"mixedText", parts} },
                            new List<object>(), () => hookDLL_DuelDlgSetResult.Original(selected));
                    }
                }
                else if (p1 == 6)
                {
                    // The producer has six slots and its reported count need not mean contiguous slots.
                    for (int slot = 0; slot < 6; slot++)
                    {
                        uint packed = (uint)externalAiProfile.Read32(0x3cb8 + slot * 4);
                        if ((packed & 0x80000000u) == 0) continue;
                        uint selected = (uint)slot;
                        add("dialog_slot_" + slot, "dialog_option", new Dictionary<string, object> { {"textId", (int)(packed & 0x0fffffffu)}, {"textGroup", "DLG"} },
                            new List<object>(), () => hookDLL_DuelDlgSetResult.Original(selected));
                    }
                }
                else reason = "unsupported_dialog_type";
            }
            else
            {
                int count = hookDLL_DuelListGetItemMax.Original();
                if (count < 0 || count > 300) throw new InvalidOperationException("invalid_list_count");
                int min = hookDLL_DuelListGetSelectMin.Original(), max = hookDLL_DuelListGetSelectMax.Original();
                multi = hookDLL_DuelListIsMultiMode.Original() != 0;
                limits["min"] = min; limits["max"] = max; limits["allowEmpty"] = min == 0;
                // Material/sum constraints are not inferred from min/max. Unknown remains explicit.
                limits["legality"] = min == 1 && max == 1 ? "single" : "unknown";
                for (int index = 0; index < count; index++)
                {
                    int itemIndex = index, cardId = hookDLL_DuelListGetItemID.Original(index);
                    int attributes = hookDLL_DuelListGetItemAttribute.Original(index);
                    int owner = (attributes & (int)DuelListAttribute.Opponent) != 0 ? 1 - actor : actor;
                    bool visible = cardId > 0 && externalAiProfile.ListType != (int)DuelListType.BlindSelect &&
                        (owner == actor || (attributes & (int)DuelListAttribute.FromGrave) != 0);
                    Dictionary<string, object> card = new Dictionary<string, object> {
                        {"player", owner},
                        {"zone", "선택 목록"}, {"index", index}, {"identityVisible", visible}
                    };
                    if (visible) { card["cardId"] = cardId; card["uniqueId"] = hookDLL_DuelListGetItemUniqueID.Original(index); }
                    string key = "list_" + index;
                    add(key, "select_card", new Dictionary<string, object>(), new List<object> { card }, () => hookDLL_DuelListSetIndex.Original(itemIndex));
                    listIndices[key] = index;
                }
            }
            if (choices.Count == 0 && reason == null) reason = "no_decoded_choices";
            List<object> observedCards = new List<object>();
            for (int player = 0; player < 2; player++) for (int pos = 0; pos < 18; pos++)
            {
                int count = hookDLL_DuelGetCardNum.Original(player, pos);
                if (count < 0 || count > 128) throw new InvalidOperationException("invalid_card_count");
                // Deck order and opposing extra deck identities are excluded. Counts remain available.
                if (pos == 15 || (pos == 14 && player != actor))
                    observedCards.Add(new Dictionary<string, object> { {"player", player}, {"position", pos}, {"count", count}, {"identityVisible", false} });
                else for (int index = 0; index < count; index++) observedCards.Add(ExternalAiCard(player, pos, index, actor));
            }
            Dictionary<string, object> request = new Dictionary<string, object> {
                {"protocolVersion", 1}, {"duelId", externalAiDuel}, {"duelGeneration", externalAiGeneration},
                {"decisionId", Guid.NewGuid().ToString("N")}, {"requestSequence", ++externalAiSequence}, {"actor", actor},
                {"requestKind", id == 4 ? "menu" : id == 55 ? "dialog" : "list"},
                {"rawRequest", new Dictionary<string, object> { {"effectId", id}, {"params", new int[] {p1,p2,p3}},
                    {"decodeStatus", reason == null ? "complete" : "unsupported"}, {"reason", reason} }},
                {"observation", new Dictionary<string, object> { {"turn", hookDLL_DuelGetTurnNum.Original()}, {"phase", hookDLL_DuelGetCurrentPhase.Original()},
                    {"turnPlayer", hookDLL_DuelWhichTurnNow.Original()},
                    {"lifePoints", new int[] {hookDLL_DuelGetLP.Original(0),hookDLL_DuelGetLP.Original(1)}}, {"cards", observedCards},
                    {"events", externalAiEvents.ToArray()}, {"selectionContext", selectionContext} }},
                {"choices", choices}, {"constraints", limits}, {"deadline", DateTime.UtcNow.AddSeconds(externalAiConfig.DeadlineSeconds).ToString("o")}
            };
            externalAiInput = new InputSession(request, id, marker, selected =>
            {
                externalAiSelected = selected.ToArray();
                foreach (object choiceValue in choices)
                {
                    Dictionary<string, object> choice = Protocol.Object(choiceValue);
                    if (selected.Contains(Protocol.Text(choice, "actionId")) && Protocol.Text(choice, "semanticKind") == "activate")
                    {
                        externalAiActiveChoice = choice;
                        externalAiActiveDecision = Protocol.Text(request, "decisionId");
                    }
                }
                if (id == 56 && Protocol.Number(limits, "max") == 1)
                {
                    hookDLL_DuelListSetIndex.Original(listIndices[selected[0]]);
                    hookDLL_DuelDlgSetResult.Original(1);
                }
                else if (id == 56 && multi)
                {
                    foreach (int index in listIndices.Values) hookDLL_DuelListSetCardExData.Original(index, 0);
                    for (int rank = 0; rank < selected.Count; rank++) hookDLL_DuelListSetCardExData.Original(listIndices[selected[rank]], rank + 1);
                    hookDLL_DuelDlgSetResult.Original((uint)selected.Count);
                }
                else actions[selected[0]]();
            });
            externalAiWorker.Send("v1/requests", externalAiInput.Request);
        }
    }
}
