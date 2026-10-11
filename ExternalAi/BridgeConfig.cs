using System;
using System.IO;
using System.Net;
using System.Collections.Generic;

namespace YgoMaster.ExternalAi
{
    public sealed class BridgeConfig
    {
        public bool Enabled;
        public string Prefix = "http://127.0.0.1:49172/";
        public string Token;
        public int DeadlineSeconds = 120;
        public const int MaxBodyBytes = 1048576;
        public static BridgeConfig Load(string path)
        {
            Dictionary<string, object> data = Protocol.Parse(File.ReadAllText(path));
            BridgeConfig config = new BridgeConfig();
            config.Enabled = Protocol.Flag(data, "enabled");
            if (!config.Enabled) return config;
            config.Prefix = Protocol.Text(data, "prefix");
            Uri uri;
            IPAddress address;
            if (!Uri.TryCreate(config.Prefix, UriKind.Absolute, out uri) || uri.Scheme != "http" ||
                !IPAddress.TryParse(uri.Host.Trim('[', ']'), out address) || !IPAddress.IsLoopback(address) ||
                uri.AbsolutePath != "/" || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment) ||
                !string.IsNullOrEmpty(uri.UserInfo) || !config.Prefix.EndsWith("/")) throw new ProtocolException("invalid_loopback_prefix");
            string tokenPath = Protocol.Text(data, "tokenFile");
            tokenPath = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(path)), tokenPath));
            config.Token = File.ReadAllText(tokenPath).Trim();
            try { if (Convert.FromBase64String(config.Token).Length != 32) throw new FormatException(); }
            catch { throw new ProtocolException("invalid_bridge_token"); }
            if (data.ContainsKey("deadlineSeconds")) config.DeadlineSeconds = checked((int)Protocol.Number(data, "deadlineSeconds"));
            if (config.DeadlineSeconds < 5 || config.DeadlineSeconds > 600) throw new ProtocolException("invalid_deadline_seconds");
            return config;
        }
    }
}
