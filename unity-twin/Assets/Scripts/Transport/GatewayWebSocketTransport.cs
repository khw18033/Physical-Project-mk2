// Assets/Scripts/Transport/GatewayWebSocketTransport.cs
//
// ITwinTransport 의 **게이트웨이 직결** 구현체. 전송 방식을 아는 유일한 파일이다.
//
// 하는 일 넷 —
//  1. 계약 축 {entity, node, channel} 구독을 그대로 서버에 넘긴다. **토픽 문자열로 번역하지 않는다** (VZ-I-01).
//  2. 끊기면 지수 백오프로 재접속하고 **기존 구독을 자동 복원**한다.
//  3. 복원되면 서버가 현재값을 다시 밀어 주므로(VZ-I-02) 씬에 빈자리가 남지 않는다.
//  4. scope(VZ-I-11)를 구독 요청에 실어 보내고, 봉투에 실려 돌아온 값을 그대로 상위로 넘긴다.
//
// ── WebGL 에서는 이 구현체가 돌지 않는다
//
// System.Net.WebSockets.ClientWebSocket 은 소켓과 스레드를 쓰므로 WebGL 빌드에서 동작하지
// 않는다. 지금 범위(에디터·데스크톱 뷰어)에서는 문제가 없고, **웹 대시보드 경유 안으로
// 가거나 WebGL 빌드가 필요해지면 이 파일을 통째로 갈아끼우는 자리**다. 인터페이스를 둔
// 이유가 그것이고, 그때 상위 코드는 한 줄도 바뀌지 않는다.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace HybridDt.Twin.Transport
{
    public sealed class GatewayWebSocketTransport : ITwinTransport
    {
        private enum InKind { Hello, Subscribed, Data, Role, Status, Error }

        private struct Inbound
        {
            public InKind Kind;
            public HelloWire Hello;
            public string SubId;
            public Selector Selector;
            public int SnapshotCount;
            public Envelope Envelope;
            public RoleInfoWire Role;
            public ConnectionStatus Status;
            public string Message;
        }

        private sealed class SubRecord
        {
            public string Id;
            public Selector Selector;
            public object Scope;
        }

        private readonly Uri _uri;
        private readonly ConcurrentDictionary<string, SubRecord> _subs = new ConcurrentDictionary<string, SubRecord>();
        private readonly ConcurrentQueue<Inbound> _inbox = new ConcurrentQueue<Inbound>();
        private readonly ConcurrentQueue<string> _outbox = new ConcurrentQueue<string>();
        private readonly SemaphoreSlim _outboxSignal = new SemaphoreSlim(0);

        private CancellationTokenSource _cts;
        private Task _worker;
        private int _subSeq;
        private volatile bool _open;
        /// <summary>
        /// 역할 조회를 요청받았는가. **구독과 같은 이유로 기억해 둔다** — 연결이 열리기 전에
        /// 요청하면 보낼 곳이 없고, 조용히 버리면 화면이 영영 "권한 미수신"으로 남는다.
        /// (첫 구현에서 실제로 그렇게 됐다. 붙는 순간을 기다렸다가 보내는 것이 맞다.)
        /// </summary>
        private volatile bool _roleRequested;
        private ConnectionStatus _status = ConnectionStatus.Closed();
        private readonly object _statusLock = new object();

        public GatewayWebSocketTransport(string url)
        {
            if (string.IsNullOrWhiteSpace(url)) throw new ArgumentException("게이트웨이 주소가 비어 있다", "url");
            _uri = new Uri(url);
        }

        public ConnectionStatus Status
        {
            get { lock (_statusLock) return _status; }
        }

        // ── 연결 ──────────────────────────────────────────────────────────────

        public void Connect()
        {
            if (_worker != null && !_worker.IsCompleted) return;
            _cts = new CancellationTokenSource();
            CancellationToken token = _cts.Token;
            _worker = Task.Run(() => RunAsync(token), token);
        }

        public void Close()
        {
            _open = false;
            if (_cts != null)
            {
                try { _cts.Cancel(); } catch (ObjectDisposedException) { }
            }
            PushStatus(s => { s.State = ConnectionState.Closed; s.Attempt = 0; s.NextRetryInMs = null; return s; });
        }

        public void Dispose()
        {
            Close();
            try { if (_cts != null) _cts.Dispose(); } catch (Exception) { }
            _cts = null;
        }

        /// <summary>
        /// 접속 → 수신 → 끊김 → 백오프 → 재접속의 바깥 루프.
        /// **재접속마다 구독을 다시 보낸다.** 호출자는 그 사실을 알 필요가 없다.
        /// </summary>
        private async Task RunAsync(CancellationToken token)
        {
            int attempt = 0;

            while (!token.IsCancellationRequested)
            {
                int shown = attempt;
                PushStatus(s =>
                {
                    s.State = shown > 0 ? ConnectionState.Reconnecting : ConnectionState.Connecting;
                    s.Attempt = shown;
                    s.NextRetryInMs = null;
                    return s;
                });

                ClientWebSocket ws = new ClientWebSocket();
                CancellationTokenSource sessionCts = CancellationTokenSource.CreateLinkedTokenSource(token);

                try
                {
                    await ws.ConnectAsync(_uri, sessionCts.Token).ConfigureAwait(false);
                }
                catch (Exception e)
                {
                    ws.Dispose();
                    sessionCts.Dispose();
                    if (token.IsCancellationRequested) break;

                    attempt++;
                    double delay = Backoff.DelayMs(attempt);
                    int shownAttempt = attempt;
                    string reason = "접속 실패 — " + e.Message;
                    PushStatus(s =>
                    {
                        s.State = ConnectionState.Reconnecting;
                        s.Attempt = shownAttempt;
                        s.NextRetryInMs = delay;
                        s.LastError = reason;
                        return s;
                    });
                    await SafeDelay(delay, token).ConfigureAwait(false);
                    continue;
                }

                attempt = 0;

                // **구독 자동 복원.** 재연결 직후 서버가 현재값을 1회 푸시하므로(VZ-I-02)
                // 씬에 공백이 생기지 않는다. 복원 메시지를 먼저 채운 뒤 _open 을 세운다 —
                // 순서가 반대면 Subscribe() 와 겹쳐 같은 구독이 두 번 나갈 수 있다.
                DrainOutbox();
                foreach (SubRecord sub in _subs.Values) EnqueueSubscribe(sub);
                if (_roleRequested) EnqueueRole();
                _open = true;

                PushStatus(s =>
                {
                    s.State = ConnectionState.Open;
                    s.Attempt = 0;
                    s.NextRetryInMs = null;
                    s.LastError = null;
                    return s;
                });

                Task sendLoop = Task.Run(() => SendLoopAsync(ws, sessionCts.Token), sessionCts.Token);
                string closeReason = await ReceiveLoopAsync(ws, sessionCts.Token).ConfigureAwait(false);

                _open = false;
                try { sessionCts.Cancel(); } catch (Exception) { }
                try { await sendLoop.ConfigureAwait(false); } catch (Exception) { }
                try { ws.Dispose(); } catch (Exception) { }
                sessionCts.Dispose();

                if (token.IsCancellationRequested) break;

                attempt = 1;
                double retry = Backoff.DelayMs(attempt);
                PushStatus(s =>
                {
                    s.State = ConnectionState.Reconnecting;
                    s.Attempt = 1;
                    s.NextRetryInMs = retry;
                    s.LastError = closeReason;
                    return s;
                });
                await SafeDelay(retry, token).ConfigureAwait(false);
            }

            _open = false;
            PushStatus(s => { s.State = ConnectionState.Closed; s.NextRetryInMs = null; return s; });
        }

        private static async Task SafeDelay(double ms, CancellationToken token)
        {
            try { await Task.Delay((int)ms, token).ConfigureAwait(false); }
            catch (OperationCanceledException) { }
        }

        // ── 송신 ──────────────────────────────────────────────────────────────

        private async Task SendLoopAsync(ClientWebSocket ws, CancellationToken token)
        {
            while (!token.IsCancellationRequested && ws.State == WebSocketState.Open)
            {
                try { await _outboxSignal.WaitAsync(token).ConfigureAwait(false); }
                catch (OperationCanceledException) { return; }

                string payload;
                if (!_outbox.TryDequeue(out payload)) continue;

                try
                {
                    byte[] bytes = Encoding.UTF8.GetBytes(payload);
                    await ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, token)
                        .ConfigureAwait(false);
                }
                catch (Exception e)
                {
                    PushError("송신 실패 — " + e.Message);
                    return;
                }
            }
        }

        private void Enqueue(object message)
        {
            _outbox.Enqueue(JsonConvert.SerializeObject(message));
            _outboxSignal.Release();
        }

        /// <summary>끊긴 동안 쌓인 송신 대기를 버린다. 복원 구독이 같은 일을 하므로 중복을 막는다.</summary>
        private void DrainOutbox()
        {
            string dropped;
            while (_outbox.TryDequeue(out dropped)) { }
            while (_outboxSignal.CurrentCount > 0)
            {
                if (!_outboxSignal.Wait(0)) break;
            }
        }

        // ── 수신 ──────────────────────────────────────────────────────────────

        private async Task<string> ReceiveLoopAsync(ClientWebSocket ws, CancellationToken token)
        {
            byte[] buffer = new byte[8192];

            while (!token.IsCancellationRequested && ws.State == WebSocketState.Open)
            {
                MemoryStream ms = new MemoryStream();
                WebSocketReceiveResult result;

                try
                {
                    do
                    {
                        result = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), token).ConfigureAwait(false);
                        if (result.MessageType == WebSocketMessageType.Close)
                            return "게이트웨이가 연결을 닫았다";
                        ms.Write(buffer, 0, result.Count);
                    } while (!result.EndOfMessage);
                }
                catch (OperationCanceledException) { return "연결 종료"; }
                catch (Exception e) { return "수신 실패 — " + e.Message; }

                string text = Encoding.UTF8.GetString(ms.ToArray());
                try { Dispatch(text); }
                catch (Exception e) { PushError("메시지 해석 실패 — " + e.Message); }
            }

            return "연결이 끊겼다";
        }

        /// <summary>
        /// 서버 메시지를 큐에 넣는다. **여기서 Unity API 를 부르지 않는다** — 배경 스레드다.
        /// </summary>
        private void Dispatch(string text)
        {
            JObject root = JObject.Parse(text);
            string type = (string)root["type"];

            switch (type)
            {
                case "hello":
                    _inbox.Enqueue(new Inbound { Kind = InKind.Hello, Hello = root.ToObject<HelloWire>() });
                    return;

                case "subscribed":
                    _inbox.Enqueue(new Inbound
                    {
                        Kind = InKind.Subscribed,
                        SubId = (string)root["id"],
                        Selector = root["selector"] == null ? null : root["selector"].ToObject<Selector>(),
                        SnapshotCount = root["snapshot_count"] == null ? 0 : (int)root["snapshot_count"],
                    });
                    return;

                case "data":
                {
                    JToken envToken = root["envelope"];
                    if (envToken == null) return;
                    _inbox.Enqueue(new Inbound { Kind = InKind.Data, Envelope = envToken.ToObject<Envelope>() });
                    return;
                }

                case "role":
                    _inbox.Enqueue(new Inbound { Kind = InKind.Role, Role = root.ToObject<RoleInfoWire>() });
                    return;

                case "error":
                    PushError("게이트웨이 오류 — " + (string)root["message"]);
                    return;

                // unsubscribed / pong / command_ack / plan_decision / scenario 는 뷰어가 쓰지 않는다.
                // **조용히 버린다** — 이번 범위의 뷰어에는 제어 경로가 없으므로 이 메시지들이
                // 도착할 일이 없고, 도착한다면 그것 자체가 구성 실수다.
                default:
                    return;
            }
        }

        private void PushError(string message)
        {
            _inbox.Enqueue(new Inbound { Kind = InKind.Error, Message = message });
        }

        private void PushStatus(Func<ConnectionStatus, ConnectionStatus> mutate)
        {
            ConnectionStatus next;
            lock (_statusLock)
            {
                _status = mutate(_status);
                next = _status;
            }
            _inbox.Enqueue(new Inbound { Kind = InKind.Status, Status = next });
        }

        // ── 구독 ──────────────────────────────────────────────────────────────

        public string Subscribe(Selector selector, object scope = null)
        {
            if (selector == null) throw new ArgumentNullException("selector");

            string id = "twin-sub-" + Interlocked.Increment(ref _subSeq);
            SubRecord record = new SubRecord { Id = id, Selector = selector, Scope = scope ?? "all" };
            _subs[id] = record;

            // 끊겨 있으면 보내지 않는다 — 재연결 시 복원 경로가 같은 일을 한다.
            if (_open) EnqueueSubscribe(record);
            return id;
        }

        private void EnqueueSubscribe(SubRecord record)
        {
            Enqueue(new Dictionary<string, object>
            {
                { "type", "subscribe" },
                { "id", record.Id },
                { "selector", record.Selector },
                { "scope", record.Scope },
            });
        }

        public void Unsubscribe(string subscriptionId)
        {
            SubRecord removed;
            if (!_subs.TryRemove(subscriptionId, out removed)) return;
            if (_open) Enqueue(new Dictionary<string, object> { { "type", "unsubscribe" }, { "id", subscriptionId } });
        }

        public void RequestRole()
        {
            _roleRequested = true;
            if (_open) EnqueueRole();
        }

        private void EnqueueRole()
        {
            Enqueue(new Dictionary<string, object> { { "type", "role" } });
        }

        // ── 메인 스레드 배출 ──────────────────────────────────────────────────

        public int Pump(ITwinTransportSink sink)
        {
            if (sink == null) return 0;

            int drained = 0;
            Inbound item;
            while (_inbox.TryDequeue(out item))
            {
                drained++;
                switch (item.Kind)
                {
                    case InKind.Hello: sink.OnHello(item.Hello); break;
                    case InKind.Subscribed: sink.OnSubscribed(item.SubId, item.Selector, item.SnapshotCount); break;
                    case InKind.Data: sink.OnEnvelope(item.Envelope); break;
                    case InKind.Role: sink.OnRole(item.Role); break;
                    case InKind.Status: sink.OnStatus(item.Status); break;
                    case InKind.Error: sink.OnTransportError(item.Message); break;
                }
            }
            return drained;
        }
    }
}
