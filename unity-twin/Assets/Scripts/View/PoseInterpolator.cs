// Assets/Scripts/View/PoseInterpolator.cs
//
// VZ-U-02 의 핵심 — 수신값(임무 중 50ms) 사이를 메워 60fps 로 그린다.
//
// ── 보간이지 **추정이 아니다**
//
// 수신이 끊겼을 때 마지막 속도로 계속 미끄러지게 하면, 죽은 로봇이 화면에서 계속 움직인다.
// 관제에서 이것이 가장 나쁜 거짓말이다 — 화면은 정상으로 보이는데 실제로는 아무것도
// 모르는 상태이기 때문이다. 그래서 이 클래스에는 **속도로 앞을 미는 코드가 없다.**
// 재생 시각이 최신 표본을 넘어서면 거기서 멈춘다.
//
// ── 멈추는 조건이 둘이다
//
//  1. **서버 판정 우선** — availability 가 stale·offline 이면 즉시 정지한다. 서버가
//     "이 값은 현재값이 아니다"라고 말한 이상 보간할 근거가 없다.
//  2. **마지막 수신 이후 임계 경과** — 임계는 서버가 준 stale_threshold_ms 를 쓴다.
//     **임의 상수를 새로 만들지 않는다.** 뷰어가 자기 숫자를 만들면 웹과 판정이 갈리고,
//     "Unity 에서는 멈췄는데 웹에서는 안 멈췄다"가 계약 문제인지 상수 문제인지 알 수 없게 된다.
//     (1번이 있는데 2번이 필요한 이유: 상태 채널이 5초 주기라 서버 판정이 도착하기까지
//      간격이 있고, 그 사이에 전송이 끊기면 1번은 영영 오지 않는다.)
//
// ── 재생 지연을 왜 두는가
//
// 표본 **사이**를 메우려면 아직 안 온 미래가 아니라 이미 온 과거를 재생해야 한다.
// 그래서 "지금"이 아니라 "지금 - 지연"을 재생한다. 지연은 관측된 수신 간격에서 뽑는다 —
// 로봇은 50ms, 센서는 1분이라 하나의 상수로 덮으면 둘 중 하나가 반드시 깨진다.
// 아래 Min/Max 는 계약값이 아니라 **재생 버퍼의 안전 범위**이며, 그 사실을 이름에 남겼다.

using UnityEngine;
using HybridDt.Twin.Data;

namespace HybridDt.Twin.View
{
    public enum InterpolationMode
    {
        /// <summary>표본이 없어 그릴 위치가 없다.</summary>
        NoData,
        /// <summary>두 표본 사이를 메우는 중. 정상 동작.</summary>
        Interpolating,
        /// <summary>최신 표본에 도달해 그 자리에 붙어 있다. **외삽하지 않는다.**</summary>
        Holding,
        /// <summary>정지. 서버가 stale·offline 이라 했거나 임계를 넘겼다.</summary>
        Frozen,
    }

    public sealed class PoseInterpolator
    {
        /// <summary>재생 버퍼의 하한(초). 계약값이 아니라 표현 계층의 안전 범위다.</summary>
        private const double MinBufferSec = 0.03;
        /// <summary>재생 버퍼의 상한(초). 이보다 뒤로 재생하면 사람이 느낄 만큼 늦는다.</summary>
        private const double MaxBufferSec = 0.5;
        /// <summary>간격을 아직 못 재었을 때의 초기 버퍼(초).</summary>
        private const double InitialBufferSec = 0.1;

        private Vector3 _rendered;
        private bool _hasRendered;

        public InterpolationMode Mode { get; private set; }
        public Vector3 Rendered { get { return _rendered; } }
        public bool HasRendered { get { return _hasRendered; } }
        /// <summary>지금 쓰고 있는 재생 지연(초). 진단 표시용.</summary>
        public double BufferSec { get; private set; }

        /// <summary>
        /// 이번 프레임의 위치를 계산한다. **매 프레임 호출된다** — 씬 상태 병합(100ms)과는 다른 축이다.
        /// </summary>
        /// <param name="serverSaysNotCurrent">availability 가 stale·offline 인가. **서버 판정이 우선이다.**</param>
        /// <param name="staleThresholdSec">서버가 준 임계. 뷰어가 만든 값이 아니다.</param>
        public Vector3 Evaluate(
            PoseBuffer buffer,
            double now,
            bool serverSaysNotCurrent,
            double staleThresholdSec,
            bool flipHandedness)
        {
            if (buffer == null || !buffer.HasAny)
            {
                Mode = InterpolationMode.NoData;
                return _rendered;
            }

            // ① 서버 판정 우선. 있던 자리에 그대로 선다 — 사라지지도, 원점으로 튀지도 않는다.
            if (serverSaysNotCurrent)
            {
                Mode = InterpolationMode.Frozen;
                if (!_hasRendered) SnapToLatest(buffer, flipHandedness);
                return _rendered;
            }

            // ② 마지막 수신 이후 임계 경과. 서버 판정이 아직 도착하지 않은 구간의 보험이다.
            double sinceLast = now - buffer.LastArrivalTime;
            if (sinceLast > staleThresholdSec)
            {
                Mode = InterpolationMode.Frozen;
                if (!_hasRendered) SnapToLatest(buffer, flipHandedness);
                return _rendered;
            }

            double interval = buffer.MeanIntervalSec ?? InitialBufferSec;
            BufferSec = Mathf.Clamp((float)interval, (float)MinBufferSec, (float)MaxBufferSec);

            double playback = now - BufferSec;

            PoseSample a, b;
            double t;
            if (buffer.TryBracket(playback, out a, out b, out t))
            {
                Vector3 pa = FrameConvert.ToUnity(a.X, a.Y, a.Z, flipHandedness);
                Vector3 pb = FrameConvert.ToUnity(b.X, b.Y, b.Z, flipHandedness);
                _rendered = Vector3.Lerp(pa, pb, (float)t);
                _hasRendered = true;
                Mode = InterpolationMode.Interpolating;
                return _rendered;
            }

            // 재생 시각이 최신 표본을 지났다. **여기서 외삽하지 않는다** — 최신 표본에 붙어 선다.
            SnapToLatest(buffer, flipHandedness);
            Mode = InterpolationMode.Holding;
            return _rendered;
        }

        private void SnapToLatest(PoseBuffer buffer, bool flipHandedness)
        {
            PoseSample s = buffer.Latest;
            _rendered = FrameConvert.ToUnity(s.X, s.Y, s.Z, flipHandedness);
            _hasRendered = true;
        }

        /// <summary>표본이 없는 대상을 레지스트리 근거 자리에 놓을 때만 쓴다(미배포 등).</summary>
        public void PlaceWithoutData(Vector3 anchor)
        {
            if (_hasRendered) return;
            _rendered = anchor;
            _hasRendered = true;
        }

        public string DescribeMode()
        {
            switch (Mode)
            {
                case InterpolationMode.Interpolating: return "보간 중";
                case InterpolationMode.Holding: return "최신값 유지";
                case InterpolationMode.Frozen: return "보간 정지";
                default: return "좌표 없음";
            }
        }
    }
}
