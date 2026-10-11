using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using YgoMaster.ExternalAi;

namespace YgoMasterClient.ExternalAi
{
    public sealed class InputSession
    {
        public readonly Dictionary<string, object> Request;
        public readonly int EffectId;
        public readonly string Marker;
        readonly Action<IList<string>> apply;
        readonly int threadId;
        public bool Submitted { get; private set; }
        public bool Finished { get; private set; }
        public string FinishState { get; private set; }
        public bool Hold { get { return !Submitted && !Finished; } }
        public InputSession(Dictionary<string, object> request, int effectId, string marker, Action<IList<string>> apply)
        {
            Request = Protocol.Copy(request); EffectId = effectId; Marker = marker;
            this.apply = apply; threadId = Thread.CurrentThread.ManagedThreadId;
        }
        void CheckThread()
        {
            if (Thread.CurrentThread.ManagedThreadId != threadId) throw new InvalidOperationException("wrong_engine_thread");
        }
        public void Apply(Dictionary<string, object> response, DateTime now)
        {
            CheckThread();
            if (Finished || Submitted) throw new ProtocolException("inactive_input", 409);
            if (Protocol.Deadline(Request) <= now) throw new ProtocolException("expired", 409);
            Protocol.Decision(Request, response);
            apply(Protocol.List(response, "actionIds").Cast<object>().Select(x => (string)x).ToList());
            Submitted = true;
        }
        public Dictionary<string, object> Finish(string state, string reason)
        {
            CheckThread();
            if (Finished || (state == "applied" && !Submitted)) throw new InvalidOperationException("invalid_input_finish");
            Finished = true; FinishState = state;
            Dictionary<string, object> ack = new Dictionary<string, object>();
            foreach (string key in new[] { "protocolVersion", "duelId", "duelGeneration", "decisionId", "actor" }) ack[key] = Request[key];
            ack["state"] = state; ack["reason"] = reason;
            return ack;
        }
    }
}
