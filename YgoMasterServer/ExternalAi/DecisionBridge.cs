using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;

namespace YgoMaster.ExternalAi
{
    public sealed class DecisionBridge : IDisposable
    {
        readonly BridgeConfig config;
        readonly DecisionStore store;
        HttpListener listener;
        Thread worker;
        public DecisionBridge(BridgeConfig config) { this.config = config; store = new DecisionStore(config.DeadlineSeconds); }
        public void Start()
        {
            if (!config.Enabled) return;
            listener = new HttpListener(); listener.Prefixes.Add(config.Prefix); listener.Start();
            listener.TimeoutManager.EntityBody = TimeSpan.FromSeconds(5);
            worker = new Thread(delegate()
            {
                while (listener.IsListening)
                {
                    try { Process(listener.GetContext()); }
                    catch (HttpListenerException) { break; }
                    catch (ObjectDisposedException) { break; }
                    catch { Console.Error.WriteLine("External AI request failed"); }
                }
            });
            worker.IsBackground = true; worker.Start();
        }
        bool Authorized(HttpListenerRequest request)
        {
            if (request.RemoteEndPoint == null || !IPAddress.IsLoopback(request.RemoteEndPoint.Address)) return false;
            string received = request.Headers["Authorization"] ?? "";
            string expected = "Bearer " + config.Token;
            int difference = received.Length ^ expected.Length;
            for (int i = 0; i < expected.Length; i++) difference |= expected[i] ^ (i < received.Length ? received[i] : 0);
            return difference == 0;
        }
        Dictionary<string, object> Body(HttpListenerRequest request)
        {
            if (request.ContentLength64 > BridgeConfig.MaxBodyBytes) throw new ProtocolException("body_too_large", 413);
            using (MemoryStream stream = new MemoryStream())
            {
                byte[] buffer = new byte[8192]; int count;
                while ((count = request.InputStream.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (stream.Length + count > BridgeConfig.MaxBodyBytes) throw new ProtocolException("body_too_large", 413);
                    stream.Write(buffer, 0, count);
                }
                return Protocol.Parse(new UTF8Encoding(false, true).GetString(stream.ToArray()));
            }
        }
        void Process(HttpListenerContext context)
        {
            try
            {
                if (!Authorized(context.Request)) throw new ProtocolException("unauthorized", 401);
                DateTime now = DateTime.UtcNow;
                string path = context.Request.Url.AbsolutePath;
                string method = context.Request.HttpMethod;
                object result;
                if (method == "GET" && path == "/v1/pending") result = new Dictionary<string, object> { {"records", store.Pending(now)} };
                else if (method == "GET" && path.StartsWith("/v1/context/", StringComparison.Ordinal)) result = store.Context(path.Substring("/v1/context/".Length), now);
                else if (method == "GET" && path.StartsWith("/v1/requests/", StringComparison.Ordinal)) result = store.Get(path.Substring(13), now);
                else if (method == "POST" && path == "/v1/requests") result = store.Publish(Body(context.Request), now);
                else if (method == "POST" && path == "/v1/decisions") result = store.Submit(Body(context.Request), now);
                else if (method == "POST" && path == "/v1/acks") result = store.Acknowledge(Body(context.Request), now);
                else if (method == "POST" && path == "/v1/duels/end")
                {
                    Dictionary<string, object> body = Body(context.Request);
                    Protocol.Identity(body);
                    store.EndDuel(Protocol.Text(body, "duelId"), Protocol.Number(body, "duelGeneration"), now);
                    result = new Dictionary<string, object> { {"state", "cancelled"} };
                }
                else throw new ProtocolException("unknown_route", 404);
                Reply(context, 200, result);
            }
            catch (ProtocolException error) { Reply(context, error.StatusCode, new Dictionary<string, object> { {"error", error.Message} }); }
            catch (DecoderFallbackException) { Reply(context, 400, new Dictionary<string, object> { {"error", "invalid_utf8"} }); }
            catch { Reply(context, 500, new Dictionary<string, object> { {"error", "bridge_failure"} }); }
            finally { context.Response.Close(); }
        }
        static void Reply(HttpListenerContext context, int status, object value)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(Protocol.Serialize(value));
            context.Response.StatusCode = status; context.Response.ContentType = "application/json; charset=utf-8";
            context.Response.ContentLength64 = bytes.Length;
            try { context.Response.OutputStream.Write(bytes, 0, bytes.Length); }
            catch (HttpListenerException) { }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }
        public void Dispose() { if (listener != null) listener.Close(); if (worker != null) worker.Join(1000); }
    }
}
