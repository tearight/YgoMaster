using System;
using System.Collections.Generic;
using System.Threading;
using YgoMaster.ExternalAi;
using YgoMasterClient.ExternalAi;

class InputSessionChecks
{
    static void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
    static int Main()
    {
        Dictionary<string, object> request = Protocol.Parse(@"{
            ""protocolVersion"":1,""duelId"":""duel"",""duelGeneration"":1,""decisionId"":""first"",""requestSequence"":1,""actor"":1,
            ""requestKind"":""list"",""rawRequest"":{""decodeStatus"":""complete""},""observation"":{},
            ""choices"":[{""actionId"":""b"",""semanticKind"":""select_card"",""text"":""b"",""cardReferences"":[],""arguments"":{}},
                        {""actionId"":""a"",""semanticKind"":""select_card"",""text"":""a"",""cardReferences"":[],""arguments"":{}}],
            ""constraints"":{""min"":2,""max"":2,""ordered"":true,""allowEmpty"":false,""legality"":""allowed_selections"",""allowedSelections"":[[""b"",""a""]]},
            ""deadline"":""2099-01-01T00:00:00Z""}");
        Dictionary<string, object> response = Protocol.Parse(@"{""protocolVersion"":1,""duelId"":""duel"",""duelGeneration"":1,
            ""decisionId"":""first"",""actor"":1,""actionIds"":[""b"",""a""],""provider"":""mock"",""model"":""test""}");
        int calls = 0;
        InputSession session = new InputSession(request, 56, "request-marker", ids => { Check(ids[0] == "b" && ids[1] == "a", "ordered values"); calls++; });
        Check(session.Hold, "hold before decision");
        Exception wrongThread = null;
        Thread other = new Thread(() => { try { session.Apply(response, DateTime.UtcNow); } catch (Exception error) { wrongThread = error; } });
        other.Start(); other.Join();
        Check(wrongThread is InvalidOperationException && calls == 0, "worker cannot apply native input");
        session.Apply(response, DateTime.UtcNow);
        Check(calls == 1 && session.Submitted && !session.Hold && !session.Finished, "submitted is not consumed");
        bool duplicateRejected = false;
        try { session.Apply(response, DateTime.UtcNow); } catch (ProtocolException) { duplicateRejected = true; }
        Check(duplicateRejected && calls == 1, "apply exactly once");
        Check(Protocol.Text(session.Finish("applied", "engine_consumed"), "state") == "applied", "explicit consumption acknowledgement");
        InputSession cancelled = new InputSession(request, 56, "old-marker", ids => calls++);
        cancelled.Finish("cancelled", "new_generation");
        bool staleRejected = false;
        try { cancelled.Apply(response, DateTime.UtcNow); } catch (ProtocolException) { staleRejected = true; }
        Check(staleRejected && calls == 1, "cancelled session cannot apply queued result");
        Console.WriteLine("PASS engine thread ownership, ordered mapping, one apply, explicit consumption, stale queued result");
        return 0;
    }
}
