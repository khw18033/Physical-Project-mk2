// Assets/Scripts/Transport/ITwinTransport.cs
//
// 상위 코드가 보는 **유일한 면**. 여기에는 WebSocket·URL·토픽·재연결이 없다.
//
// ── 왜 인터페이스 하나를 두는가
//
// 뷰어가 게이트웨이에 **직접 붙을지 웹 대시보드를 경유할지 아직 정해지지 않았다.**
// 지금 정하지 않아도 되는 것을 정해 버리면 나중에 상위 코드까지 끌려간다. 그래서
// 연결 방식을 이 인터페이스 뒤로 밀어 두고, 지금은 게이트웨이 직결 구현체
// (<see cref="GatewayWebSocketTransport"/>) 하나만 만든다. 경로가 정해지면
// 구현체를 추가하고 <c>TwinViewer</c> 의 생성 한 줄만 바꾼다.
//
// ── 왜 Pump 인가 (콜백이 아니라)
//
// ClientWebSocket 은 스레드 풀에서 돌고 Unity API 는 메인 스레드 전용이다. 구현체가
// 콜백을 직접 부르면 호출자가 어느 스레드에 있는지 알 수 없어, 언젠가 반드시
// "가끔 죽는" 버그가 된다. 수신은 큐에 쌓고 **메인 스레드가 Update 에서 꺼내 간다** —
// 스레드 경계가 이 메서드 하나로 눈에 보이게 만드는 것이 목적이다.

using System;

namespace HybridDt.Twin.Transport
{
    public enum ConnectionState
    {
        Connecting,
        Open,
        Reconnecting,
        Closed,
    }

    public struct ConnectionStatus
    {
        public ConnectionState State;
        /// <summary>몇 번째 재시도인가. 0이면 정상 연결.</summary>
        public int Attempt;
        /// <summary>다음 재시도까지 남은 시간(ms). 대기 중이 아니면 null.</summary>
        public double? NextRetryInMs;
        /// <summary>마지막 hello 의 서버 시각. **표시용이다** — 클라이언트 시계와 비교하지 않는다.</summary>
        public string ServerTime;
        public double? StaleThresholdMs;
        public string LastError;

        public static ConnectionStatus Closed()
        {
            return new ConnectionStatus { State = ConnectionState.Closed, Attempt = 0 };
        }

        public string Describe()
        {
            switch (State)
            {
                case ConnectionState.Open: return "연결됨";
                case ConnectionState.Connecting: return "연결 중";
                case ConnectionState.Reconnecting:
                    return "재연결 대기 " + Attempt + "회차"
                        + (NextRetryInMs.HasValue ? " (" + Math.Round(NextRetryInMs.Value) + "ms 후)" : "");
                default: return "끊김";
            }
        }
    }

    /// <summary>
    /// <see cref="ITwinTransport.Pump"/> 가 메인 스레드에서 호출하는 수신 면.
    /// 구현부는 <c>TwinViewer</c> 하나다.
    /// </summary>
    public interface ITwinTransportSink
    {
        void OnHello(HelloWire hello);
        /// <summary>구독 확인. snapshotCount 는 VZ-I-02 로 **즉시 밀려온 현재값 건수**다.</summary>
        void OnSubscribed(string subId, Selector selector, int snapshotCount);
        void OnEnvelope(Envelope envelope);
        void OnRole(RoleInfoWire role);
        void OnStatus(ConnectionStatus status);
        void OnTransportError(string message);
    }

    public interface ITwinTransport : IDisposable
    {
        ConnectionStatus Status { get; }

        void Connect();
        void Close();

        /// <summary>
        /// 계약 축으로 구독한다. 반환값은 해제에 쓰는 구독 id.
        ///
        /// 구현체가 반드시 지켜야 하는 것 둘 —
        ///  - **재연결 시 기존 구독을 자동 복원한다.** 호출자는 다시 구독하지 않는다.
        ///  - 서버가 구독 즉시 보내는 현재값(VZ-I-02)을 걸러내지 않고 그대로 흘려보낸다.
        /// </summary>
        /// <param name="scope">VZ-I-11. null 이면 'all'. 현 단계는 'all' 고정이지만 왕복은 살아 있다.</param>
        string Subscribe(Selector selector, object scope = null);

        void Unsubscribe(string subscriptionId);

        /// <summary>VZ-C-04 / BE-Q-04 — 역할과 **그 역할이 적용되는 범위**를 요청한다.</summary>
        void RequestRole();

        /// <summary>
        /// **메인 스레드에서만 호출한다.** 배경 스레드가 쌓아 둔 수신을 이번 프레임에 전부 꺼내
        /// sink 로 넘긴다. 반환값은 꺼낸 건수(계측용).
        /// </summary>
        int Pump(ITwinTransportSink sink);
    }
}
