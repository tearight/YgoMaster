using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using YgoMaster.ExternalAi;

namespace YgoMaster.ExternalAi
{
    public sealed class DecisionStore
    {
        sealed class Record
        {
            public Dictionary<string, object> Request, Response;
            public string Fingerprint, State = "pending", Reason;
            public DateTime Updated;
            public Dictionary<string, object> Snapshot()
            {
                return Protocol.Copy(new Dictionary<string, object> {
                    {"request", Request}, {"decision", Response}, {"state", State},
                    {"reason", Reason}, {"updatedAt", Updated.ToString("o")}
                });
            }
        }
        sealed class DuelState { public long Generation, Sequence; public bool Ended; public DateTime Updated; }
        readonly object gate = new object();
        readonly Dictionary<string, Record> records = new Dictionary<string, Record>();
        readonly Dictionary<string, DuelState> duels = new Dictionary<string, DuelState>();
        readonly int maxLifetimeSeconds;
        public DecisionStore(int maxLifetimeSeconds = 120) { this.maxLifetimeSeconds = maxLifetimeSeconds; }
        static bool Active(Record record) { return record.State == "pending" || record.State == "accepted"; }
        void Prune(DateTime now)
        {
            foreach (Record record in records.Values.Where(Active))
                if (Protocol.Deadline(record.Request) <= now) { record.State = "expired"; record.Reason = "deadline"; record.Updated = now; }
            List<KeyValuePair<string, Record>> completed = records.Where(x => !Active(x.Value)).OrderByDescending(x => x.Value.Updated).ToList();
            foreach (var item in completed.Skip(256)) records.Remove(item.Key);
            HashSet<string> activeDuels = new HashSet<string>(records.Values.Where(Active).Select(x => Protocol.Text(x.Request, "duelId")));
            foreach (var item in duels.Where(x => !activeDuels.Contains(x.Key)).OrderByDescending(x => x.Value.Updated).Skip(256).ToList()) duels.Remove(item.Key);
        }
        Record Find(string decisionId)
        {
            Record record;
            if (!records.TryGetValue(decisionId, out record)) throw new ProtocolException("unknown_decision", 409);
            return record;
        }
        public Dictionary<string, object> Publish(Dictionary<string, object> input, DateTime now)
        {
            Dictionary<string, object> request = Protocol.Copy(input);
            lock (gate)
            {
                Prune(now);
                Protocol.Identity(request);
                string id = Protocol.Text(request, "decisionId"), fingerprint = Protocol.Canonical(request);
                Record existing;
                if (records.TryGetValue(id, out existing))
                {
                    if (existing.Fingerprint != fingerprint) throw new ProtocolException("decision_id_conflict", 409);
                    return existing.Snapshot();
                }
                Protocol.Request(request, now, maxLifetimeSeconds);
                string duelId = Protocol.Text(request, "duelId");
                long generation = Protocol.Number(request, "duelGeneration"), sequence = Protocol.Number(request, "requestSequence");
                DuelState duel;
                if (duels.TryGetValue(duelId, out duel))
                {
                    if (generation < duel.Generation || (generation == duel.Generation && (duel.Ended || sequence <= duel.Sequence)))
                        throw new ProtocolException("stale_request", 409);
                }
                int activeDuels = records.Values.Where(Active).Select(x => Protocol.Text(x.Request, "duelId")).Distinct().Count();
                if (records.Values.Count(Active) >= 64 || (activeDuels >= 8 && !records.Values.Any(x => Active(x) && Protocol.Text(x.Request, "duelId") == duelId)))
                    throw new ProtocolException("bridge_capacity", 429);
                if (duel == null || generation > duel.Generation)
                {
                    foreach (Record old in records.Values.Where(x => Active(x) && Protocol.Text(x.Request, "duelId") == duelId))
                    { old.State = "cancelled"; old.Reason = "new_generation"; old.Updated = now; }
                    duel = new DuelState { Generation = generation }; duels[duelId] = duel;
                }
                duel.Sequence = sequence; duel.Updated = now;
                Record record = new Record { Request = request, Fingerprint = fingerprint, Updated = now };
                records.Add(id, record);
                return record.Snapshot();
            }
        }
        public IList<object> Pending(DateTime now)
        {
            lock (gate) { Prune(now); return records.Values.Where(x => x.State == "pending").OrderBy(x => x.Updated).Select(x => (object)x.Snapshot()).ToList(); }
        }
        public Dictionary<string, object> Get(string decisionId, DateTime now)
        {
            lock (gate) { Prune(now); return Find(decisionId).Snapshot(); }
        }
        public Dictionary<string, object> Context(string decisionId, DateTime now)
        {
            lock (gate)
            {
                Prune(now);
                Dictionary<string, object> current = Find(decisionId).Request;
                string duelId = Protocol.Text(current, "duelId");
                long generation = Protocol.Number(current, "duelGeneration"), actor = Protocol.Number(current, "actor");
                DuelState duel;
                bool ended = !duels.TryGetValue(duelId, out duel) || duel.Ended || duel.Generation != generation;
                List<object> history = new List<object>();
                Dictionary<string, object> result = new Dictionary<string, object> {
                    {"protocolVersion", Protocol.Version}, {"duelId", duelId}, {"duelGeneration", generation},
                    {"actor", actor}, {"ended", ended}, {"historyLimited", true}, {"records", history}
                };
                int bytes = Encoding.UTF8.GetByteCount(Protocol.Serialize(result));
                foreach (Record record in records.Values.Where(value => value.State == "applied" &&
                    Protocol.Text(value.Request, "duelId") == duelId && Protocol.Number(value.Request, "duelGeneration") == generation &&
                    Protocol.Number(value.Request, "actor") == actor && Protocol.Number(value.Request, "requestSequence") < Protocol.Number(current, "requestSequence"))
                    .OrderByDescending(value => Protocol.Number(value.Request, "requestSequence")).Take(64))
                {
                    Dictionary<string, object> request = record.Request;
                    var selected = Protocol.List(record.Response, "actionIds").Cast<string>().ToList();
                    Dictionary<string, object> observation = Protocol.Object(request["observation"]);
                    Dictionary<string, object> compactObservation = observation.Where(pair => pair.Key == "turn" || pair.Key == "phase").ToDictionary(pair => pair.Key, pair => pair.Value);
                    Dictionary<string, object> compactRequest = request.Where(pair => pair.Key == "duelId" || pair.Key == "duelGeneration" ||
                        pair.Key == "decisionId" || pair.Key == "actor" || pair.Key == "requestSequence" || pair.Key == "requestKind").ToDictionary(pair => pair.Key, pair => pair.Value);
                    compactRequest["observation"] = compactObservation;
                    compactRequest["choices"] = Protocol.List(request, "choices").Cast<object>()
                        .Where(value => selected.Contains(Protocol.Text(Protocol.Object(value), "actionId"))).ToList();
                    Dictionary<string, object> compactRecord = new Dictionary<string, object> {
                        {"state", "applied"}, {"request", compactRequest}, {"decision", new Dictionary<string, object> {{"actionIds", selected}}}
                    };
                    int entryBytes = Encoding.UTF8.GetByteCount(Protocol.Serialize(compactRecord)) + 1;
                    if (bytes + entryBytes > BridgeConfig.MaxBodyBytes) break;
                    history.Add(compactRecord); bytes += entryBytes;
                }
                history.Reverse();
                return Protocol.Copy(result);
            }
        }
        public Dictionary<string, object> Submit(Dictionary<string, object> input, DateTime now)
        {
            Dictionary<string, object> response = Protocol.Copy(input);
            lock (gate)
            {
                Prune(now);
                Record record = Find(Protocol.Text(response, "decisionId"));
                Protocol.Decision(record.Request, response);
                if (record.State == "accepted" || record.State == "applied")
                {
                    if (Protocol.Canonical(record.Response) != Protocol.Canonical(response)) throw new ProtocolException("decision_conflict", 409);
                    return record.Snapshot();
                }
                if (record.State != "pending") throw new ProtocolException("decision_" + record.State, 409);
                record.Response = response; record.State = "accepted"; record.Updated = now;
                return record.Snapshot();
            }
        }
        public Dictionary<string, object> Acknowledge(Dictionary<string, object> ack, DateTime now)
        {
            Protocol.Identity(ack);
            lock (gate)
            {
                Prune(now);
                Record record = Find(Protocol.Text(ack, "decisionId"));
                foreach (string key in new[] { "duelId", "duelGeneration", "actor" })
                    if (!Equals(record.Request[key], ack[key])) throw new ProtocolException("identity_mismatch", 409);
                string state = Protocol.Text(ack, "state"), reason = Protocol.Text(ack, "reason");
                if (state != "applied" && state != "rejected" && state != "cancelled") throw new ProtocolException("invalid_ack_state");
                if (record.State == state)
                {
                    if (record.Reason != reason) throw new ProtocolException("ack_conflict", 409);
                    return record.Snapshot();
                }
                if (!Active(record) || (state == "applied" && record.State != "accepted")) throw new ProtocolException("invalid_ack_transition", 409);
                record.State = state; record.Reason = reason; record.Updated = now;
                return record.Snapshot();
            }
        }
        public void EndDuel(string duelId, long generation, DateTime now)
        {
            lock (gate)
            {
                Prune(now);
                DuelState duel;
                if (duels.TryGetValue(duelId, out duel) && generation < duel.Generation) throw new ProtocolException("stale_generation", 409);
                if (duel == null || generation > duel.Generation) { duel = new DuelState { Generation = generation }; duels[duelId] = duel; }
                duel.Ended = true; duel.Updated = now;
                foreach (Record record in records.Values.Where(x => Active(x) && Protocol.Text(x.Request, "duelId") == duelId && Protocol.Number(x.Request, "duelGeneration") <= generation))
                { record.State = "cancelled"; record.Reason = "duel_end"; record.Updated = now; }
            }
        }
    }
}
