using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Web.Script.Serialization;

namespace YgoMaster.ExternalAi
{
    public sealed class ProtocolException : Exception
    {
        public readonly int StatusCode;
        public ProtocolException(string reason, int statusCode = 400) : base(reason) { StatusCode = statusCode; }
    }

    // Plain JSON records are shared with the Python app. Native setter data stays in the client.
    public static class Protocol
    {
        public const int Version = 1;
        public static Dictionary<string, object> Parse(string json)
        {
            try
            {
                JavaScriptSerializer parser = new JavaScriptSerializer();
                parser.MaxJsonLength = 1048576;
                parser.RecursionLimit = 32;
                return Object(Normalize(parser.DeserializeObject(json)));
            }
            catch (ProtocolException) { throw; }
            catch { throw new ProtocolException("invalid_json"); }
        }

        static object Normalize(object value)
        {
            Dictionary<string, object> map = value as Dictionary<string, object>;
            if (map != null) return map.ToDictionary(x => x.Key, x => Normalize(x.Value));
            object[] array = value as object[];
            if (array != null) return array.Select(Normalize).ToList();
            if (value is decimal) return Convert.ToDouble(value, CultureInfo.InvariantCulture);
            return value;
        }

        public static string Serialize(object value) { return MiniJSON.Json.Serialize(value); }
        public static Dictionary<string, object> Copy(Dictionary<string, object> value) { return Parse(Serialize(value)); }
        public static Dictionary<string, object> Object(object value)
        {
            Dictionary<string, object> map = value as Dictionary<string, object>;
            if (map == null) throw new ProtocolException("expected_object");
            return map;
        }
        public static object Required(Dictionary<string, object> map, string key)
        {
            object value;
            if (!map.TryGetValue(key, out value) || value == null) throw new ProtocolException("missing_" + key);
            return value;
        }
        public static string Text(Dictionary<string, object> map, string key)
        {
            string value = Required(map, key) as string;
            if (string.IsNullOrEmpty(value) || value.Length > 4096) throw new ProtocolException("invalid_" + key);
            return value;
        }
        public static long Number(Dictionary<string, object> map, string key)
        {
            object value = Required(map, key);
            if (!(value is int) && !(value is long)) throw new ProtocolException("invalid_" + key);
            return Convert.ToInt64(value, CultureInfo.InvariantCulture);
        }
        public static bool Flag(Dictionary<string, object> map, string key)
        {
            object value = Required(map, key);
            if (!(value is bool)) throw new ProtocolException("invalid_" + key);
            return (bool)value;
        }
        public static IList List(Dictionary<string, object> map, string key)
        {
            IList value = Required(map, key) as IList;
            if (value == null) throw new ProtocolException("invalid_" + key);
            return value;
        }
        public static DateTime Deadline(Dictionary<string, object> request)
        {
            DateTimeOffset deadline;
            string text = Text(request, "deadline");
            if ((!text.EndsWith("Z", StringComparison.Ordinal) && !text.EndsWith("+00:00", StringComparison.Ordinal)) ||
                !DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture,
                DateTimeStyles.None, out deadline) || deadline.Offset != TimeSpan.Zero)
                throw new ProtocolException("invalid_deadline");
            return deadline.UtcDateTime;
        }
        public static void Identity(Dictionary<string, object> data)
        {
            if (Number(data, "protocolVersion") != Version) throw new ProtocolException("unsupported_protocol");
            foreach (string key in new[] { "duelId", "decisionId" })
            {
                string value = Text(data, key);
                if (value.Length > 128 || value.Any(c => !char.IsLetterOrDigit(c) && c != '-' && c != '_'))
                    throw new ProtocolException("invalid_" + key);
            }
            if (Number(data, "duelGeneration") < 1) throw new ProtocolException("invalid_generation");
            if (Number(data, "actor") < 0 || Number(data, "actor") > 1) throw new ProtocolException("invalid_actor");
        }
        public static void Request(Dictionary<string, object> request, DateTime now, int maxLifetimeSeconds)
        {
            Identity(request);
            if (Number(request, "requestSequence") < 1) throw new ProtocolException("invalid_sequence");
            Text(request, "requestKind");
            Dictionary<string, object> raw = Object(Required(request, "rawRequest"));
            string status = Text(raw, "decodeStatus");
            if (status != "complete" && status != "unsupported") throw new ProtocolException("invalid_decode_status");
            Object(Required(request, "observation"));
            Dictionary<string, object> limits = Object(Required(request, "constraints"));
            long min = Number(limits, "min"), max = Number(limits, "max");
            if (min < 0 || max < min || max > 4096) throw new ProtocolException("invalid_selection_count");
            Flag(limits, "ordered"); Flag(limits, "allowEmpty");
            string legality = Text(limits, "legality");
            if (legality != "single" && legality != "independent" && legality != "allowed_selections" && legality != "unknown")
                throw new ProtocolException("invalid_legality");
            IList choices = List(request, "choices");
            if (choices.Count > 4096 || (status == "complete" && choices.Count == 0)) throw new ProtocolException("invalid_choices");
            HashSet<string> ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (object choice in choices)
            {
                Dictionary<string, object> item = Object(choice);
                string id = Text(item, "actionId");
                if (id.Length > 128 || !ids.Add(id)) throw new ProtocolException("invalid_action_id");
                Text(item, "semanticKind");
                if (!(Required(item, "text") is string)) throw new ProtocolException("invalid_choice_text");
                List(item, "cardReferences"); Object(Required(item, "arguments"));
            }
            if (legality == "single" && (min != 1 || max != 1)) throw new ProtocolException("invalid_single_constraint");
            if (legality == "allowed_selections")
            {
                IList selections = List(limits, "allowedSelections");
                if (selections.Count == 0 || selections.Count > 4096) throw new ProtocolException("invalid_allowed_selections");
                foreach (object selection in selections) ValidateSelection(request, selection as IList, ids, false);
            }
            if (Deadline(request) <= now) throw new ProtocolException("expired", 409);
            if (Deadline(request) > now.AddSeconds(maxLifetimeSeconds)) throw new ProtocolException("deadline_too_far");
        }
        static void ValidateSelection(Dictionary<string, object> request, IList selected, HashSet<string> candidates, bool checkLegality)
        {
            if (selected == null) throw new ProtocolException("invalid_action_ids");
            Dictionary<string, object> limits = Object(Required(request, "constraints"));
            if (selected.Count < Number(limits, "min") || selected.Count > Number(limits, "max") ||
                (selected.Count == 0 && !Flag(limits, "allowEmpty"))) throw new ProtocolException("invalid_selection_count");
            HashSet<string> seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (object item in selected)
            {
                string id = item as string;
                if (id == null || !candidates.Contains(id) || !seen.Add(id)) throw new ProtocolException("invalid_action_ids");
            }
            if (!checkLegality) return;
            string legality = Text(limits, "legality");
            if (legality == "unknown") throw new ProtocolException("unknown_legality", 409);
            if (legality == "allowed_selections")
            {
                bool ordered = Flag(limits, "ordered");
                bool found = List(limits, "allowedSelections").Cast<object>().Any(x =>
                {
                    IList allowed = x as IList;
                    if (allowed == null || allowed.Count != selected.Count) return false;
                    return ordered ? allowed.Cast<object>().SequenceEqual(selected.Cast<object>()) :
                        new HashSet<object>(allowed.Cast<object>()).SetEquals(selected.Cast<object>());
                });
                if (!found) throw new ProtocolException("illegal_selection");
            }
        }
        public static void Decision(Dictionary<string, object> request, Dictionary<string, object> response)
        {
            Identity(response);
            foreach (string key in new[] { "duelId", "decisionId" })
                if (Text(request, key) != Text(response, key)) throw new ProtocolException("identity_mismatch", 409);
            foreach (string key in new[] { "duelGeneration", "actor" })
                if (Number(request, key) != Number(response, key)) throw new ProtocolException("identity_mismatch", 409);
            if (Text(Object(request["rawRequest"]), "decodeStatus") != "complete") throw new ProtocolException("unsupported_request", 409);
            Text(response, "provider"); Text(response, "model");
            object confidence;
            if (response.TryGetValue("confidence", out confidence) && confidence != null)
            {
                if (!(confidence is double) && !(confidence is int) && !(confidence is long) && !(confidence is float))
                    throw new ProtocolException("invalid_confidence");
                double number = Convert.ToDouble(confidence, CultureInfo.InvariantCulture);
                if (double.IsNaN(number) || double.IsInfinity(number) || number < 0 || number > 1) throw new ProtocolException("invalid_confidence");
            }
            HashSet<string> candidates = new HashSet<string>(List(request, "choices").Cast<object>()
                .Select(x => Text(Object(x), "actionId")), StringComparer.Ordinal);
            ValidateSelection(request, List(response, "actionIds"), candidates, true);
        }
        public static string Canonical(object value)
        {
            Dictionary<string, object> map = value as Dictionary<string, object>;
            if (map != null) return "{" + string.Join(",", map.OrderBy(x => x.Key, StringComparer.Ordinal)
                .Select(x => Serialize(x.Key) + ":" + Canonical(x.Value))) + "}";
            IList list = value as IList;
            if (list != null) return "[" + string.Join(",", list.Cast<object>().Select(Canonical)) + "]";
            return Serialize(value);
        }
    }
}
