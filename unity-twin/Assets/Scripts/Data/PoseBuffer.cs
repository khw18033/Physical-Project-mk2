// Assets/Scripts/Data/PoseBuffer.cs
//
// 수신한 좌표 표본의 보관함. **보간의 재료이지 보간 자체는 아니다** — 계산은 View/PoseInterpolator 가 한다.
//
// ── 왜 계약 좌표를 그대로 담는가 (Vector3 로 바꿔 담지 않는다)
//
// 손잡이 변환은 표현 계층의 일이고 **경계 한 곳(FrameConvert)에서만** 일어나야 한다.
// 여기서 Vector3 로 바꿔 담으면 변환 지점이 둘이 되고, 인스펙터에서 플래그를 뒤집어도
// 이미 담긴 표본은 옛 규칙으로 남는다. 검증 7(플래그를 뒤집으면 눈에 띄게 달라진다)이
// 그 자리에서 무너진다.
//
// ── 왜 로컬 도착 시각을 같이 담는가
//
// 보간 재생은 표본 사이의 **간격**이 필요한데, 서버 시각으로 재생하면 서버·클라이언트
// 시계 차이가 그대로 재생 오차가 된다. 대신 도착 시각(로컬 단조 시계)으로 재생하면
// 시계 차이가 개입하지 않는다. **상태 판정에는 이 시각을 쓰지 않는다** — stale 은
// 서버가 판정하고(VZ-U-01), 여기 시각은 오직 "몇 초 전에 도착했나"의 재생용이다.

using System;

namespace HybridDt.Twin.Data
{
    public struct PoseSample
    {
        /// <summary>**이미 전역 좌표로 변환된 값**(BE-C-04 · DT-03). 계약 축 그대로 담는다.</summary>
        public double X;
        public double Y;
        public double Z;
        public string Frame;
        public long Seq;
        /// <summary>로컬 단조 시계 기준 도착 시각(초). 재생에만 쓴다.</summary>
        public double LocalTime;
    }

    public sealed class PoseBuffer
    {
        private const int Capacity = 16;
        private const int IntervalWindow = 8;

        private readonly PoseSample[] _samples = new PoseSample[Capacity];
        private int _count;
        private int _head; // 다음에 쓸 자리

        private readonly double[] _intervals = new double[IntervalWindow];
        private int _intervalCount;
        private int _intervalHead;

        private long _lastSeq = long.MinValue;

        public int Count { get { return _count; } }
        public bool HasAny { get { return _count > 0; } }
        public double LastArrivalTime { get; private set; }
        /// <summary>역전·중복으로 버린 표본 수. 계측용 — 늘어나면 순서 보장이 깨지고 있다는 뜻.</summary>
        public int DroppedOutOfOrder { get; private set; }

        /// <summary>
        /// 표본 1건 적재. **역전된 표본은 버린다** — 오래된 좌표를 최신으로 오인해 그리면
        /// 로봇이 뒤로 튄다. seq 는 대상×채널별 단조 증가라 이 판단이 성립한다.
        /// </summary>
        public bool Push(double x, double y, double z, string frame, long seq, double localTime)
        {
            if (_count > 0 && seq <= _lastSeq)
            {
                DroppedOutOfOrder++;
                return false;
            }

            if (_count > 0)
            {
                double dt = localTime - LastArrivalTime;
                if (dt > 0)
                {
                    _intervals[_intervalHead] = dt;
                    _intervalHead = (_intervalHead + 1) % IntervalWindow;
                    if (_intervalCount < IntervalWindow) _intervalCount++;
                }
            }

            _samples[_head] = new PoseSample { X = x, Y = y, Z = z, Frame = frame, Seq = seq, LocalTime = localTime };
            _head = (_head + 1) % Capacity;
            if (_count < Capacity) _count++;

            _lastSeq = seq;
            LastArrivalTime = localTime;
            return true;
        }

        /// <summary>0 = 가장 오래된 표본. 버퍼가 가득 차면 밀려난 것부터 사라진다.</summary>
        public PoseSample At(int index)
        {
            int start = (_head - _count + Capacity) % Capacity;
            return _samples[(start + index) % Capacity];
        }

        public PoseSample Latest { get { return At(_count - 1); } }

        /// <summary>
        /// 최근 수신 간격의 평균(초). 표본이 부족하면 null.
        /// **보간 지연을 여기서 뽑는 이유**는 원천마다 주기가 다르기 때문이다 —
        /// 로봇은 임무 중 50ms, 센서는 평시 1분이다. 하나의 상수로 덮으면 둘 중 하나가 깨진다.
        /// </summary>
        public double? MeanIntervalSec
        {
            get
            {
                if (_intervalCount == 0) return null;
                double sum = 0;
                for (int i = 0; i < _intervalCount; i++) sum += _intervals[i];
                return sum / _intervalCount;
            }
        }

        /// <summary>
        /// 재생 시각을 감싸는 두 표본을 찾는다.
        /// 재생 시각이 최신 표본보다 뒤면 **찾지 못한 것으로 처리한다** —
        /// 그 구간을 외삽으로 메우는 순간 "죽은 로봇이 계속 미끄러지는" 거짓말이 된다.
        /// </summary>
        public bool TryBracket(double playbackTime, out PoseSample a, out PoseSample b, out double t)
        {
            a = default(PoseSample);
            b = default(PoseSample);
            t = 0;
            if (_count < 2) return false;

            for (int i = _count - 1; i > 0; i--)
            {
                PoseSample later = At(i);
                PoseSample earlier = At(i - 1);
                if (playbackTime >= earlier.LocalTime && playbackTime <= later.LocalTime)
                {
                    double span = later.LocalTime - earlier.LocalTime;
                    a = earlier;
                    b = later;
                    t = span <= 0 ? 1 : (playbackTime - earlier.LocalTime) / span;
                    if (t < 0) t = 0;
                    if (t > 1) t = 1;
                    return true;
                }
            }
            return false;
        }

        public void Clear()
        {
            _count = 0;
            _head = 0;
            _intervalCount = 0;
            _intervalHead = 0;
            _lastSeq = long.MinValue;
            DroppedOutOfOrder = 0;
            LastArrivalTime = 0;
        }
    }
}
