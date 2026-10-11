using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using YgoMaster.ExternalAi;

namespace YgoMasterClient.ExternalAi
{
    // This worker has no native delegates or pointers. Results return to the SysAct thread.
    public sealed class BridgeWorker : IDisposable
    {
        sealed class Message { public string Route; public Dictionary<string, object> Body; }
        readonly BridgeConfig config;
        readonly ConcurrentQueue<Message> outbound = new ConcurrentQueue<Message>();
        readonly ConcurrentQueue<Dictionary<string, object>> inbound = new ConcurrentQueue<Dictionary<string, object>>();
        readonly Thread thread;
        volatile bool stopping;
        public BridgeWorker(BridgeConfig config)
        {
            this.config = config;
            thread = new Thread(Run); thread.IsBackground = true; thread.Start();
        }
        public void Send(string route, Dictionary<string, object> body) { outbound.Enqueue(new Message { Route = route, Body = Protocol.Copy(body) }); }
        public bool TryRead(out Dictionary<string, object> record) { return inbound.TryDequeue(out record); }
        Dictionary<string, object> Call(string route, Dictionary<string, object> body)
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(config.Prefix + route);
            request.Proxy = null; request.AllowAutoRedirect = false; request.Timeout = 5000; request.ReadWriteTimeout = 5000;
            request.Headers["Authorization"] = "Bearer " + config.Token;
            if (body != null)
            {
                byte[] bytes = Encoding.UTF8.GetBytes(Protocol.Serialize(body));
                if (bytes.Length > BridgeConfig.MaxBodyBytes) throw new ProtocolException("body_too_large");
                request.Method = "POST"; request.ContentType = "application/json"; request.ContentLength = bytes.Length;
                using (Stream stream = request.GetRequestStream()) stream.Write(bytes, 0, bytes.Length);
            }
            using (WebResponse response = request.GetResponse())
            using (Stream stream = response.GetResponseStream())
            using (MemoryStream buffer = new MemoryStream())
            {
                byte[] bytes = new byte[8192]; int count;
                while ((count = stream.Read(bytes, 0, bytes.Length)) > 0)
                {
                    if (buffer.Length + count > BridgeConfig.MaxBodyBytes) throw new ProtocolException("response_too_large");
                    buffer.Write(bytes, 0, count);
                }
                return Protocol.Parse(new UTF8Encoding(false, true).GetString(buffer.ToArray()));
            }
        }
        void Run()
        {
            Message current = null;
            string activeId = null, lastRecord = null;
            while (!stopping)
            {
                try
                {
                    if (current == null) outbound.TryDequeue(out current);
                    if (current != null)
                    {
                        if (current.Route == "v1/requests" && Protocol.Deadline(current.Body) <= DateTime.UtcNow) current = null;
                        else
                        {
                            Dictionary<string, object> reply = Call(current.Route, current.Body);
                            if (current.Route == "v1/requests") { activeId = Protocol.Text(current.Body, "decisionId"); lastRecord = null; }
                            else if (current.Route == "v1/duels/end" || (current.Route == "v1/acks" && activeId == Protocol.Text(current.Body, "decisionId"))) activeId = null;
                            current = null;
                        }
                    }
                    if (activeId != null)
                    {
                        Dictionary<string, object> record = Call("v1/requests/" + Uri.EscapeDataString(activeId), null);
                        string state = Protocol.Text(record, "state"), fingerprint = Protocol.Canonical(record);
                        if (state != "pending" && fingerprint != lastRecord) { inbound.Enqueue(record); lastRecord = fingerprint; }
                        if (state != "pending" && state != "accepted") activeId = null;
                    }
                }
                catch (WebException error)
                {
                    HttpWebResponse response = error.Response as HttpWebResponse;
                    if (response != null)
                    {
                        int code = (int)response.StatusCode; response.Close();
                        if (code != 429 && code < 500) current = null;
                    }
                }
                catch (ProtocolException) { current = null; }
                catch (IOException) { }
                catch (ObjectDisposedException) { }
                Thread.Sleep(250);
            }
        }
        public void Dispose() { stopping = true; thread.Join(1000); }
    }
}
