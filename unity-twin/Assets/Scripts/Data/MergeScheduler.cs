// Assets/Scripts/Data/MergeScheduler.cs
//
// 씬 반영 병합 계층 (VZ-I-01).
//
// **명시적 모듈로 둔 이유**는 웹과 같다 — 병합을 저장소 안에 숨기면 "왜 씬이 100ms 늦나"를
// 나중에 아무도 못 찾고, 창 크기를 바꾸려 할 때 어디를 고칠지 모른다.
//
// 규칙 셋.
//  1. **데이터는 전량 받는다.** 병합은 수신을 버리는 것이 아니라 *씬 반영*만 묶는 것이다.
//     저장소는 매 수신마다 갱신되고, 씬을 건드리는 시점만 창으로 모은다.
//  2. 창이 열려 있는 동안 몇 건이 오든 씬 반영은 1회다 → 초당 최대 10회.
//  3. **즉시 반영이 필요한 전이는 창을 건너뛴다.** offline·stale 감지가 100ms 늦는 것은
//     상관없어 보이지만, 규칙을 코드에 남겨 두어야 나중에 창을 늘릴 때 실수하지 않는다.
//
// ── 보간 렌더와는 **다른 축**이다
//
// 이 창은 색·이름표·상태 표시 같은 **씬 상태 반영**에만 걸린다. 위치 보간은 매 프레임
// 돌아야 60fps 가 나오므로 이 스케줄러를 거치지 않는다. 둘을 한 타이머로 묶으면
// 10Hz 로 튀는 화면이 되고, 그러면 VZ-U-02 의 보간이 있으나 마나가 된다.

namespace HybridDt.Twin.Data
{
    public sealed class MergeScheduler
    {
        private readonly double _windowSec;
        private bool _pending;
        private double _flushAt;

        /// <summary>수신 표시 건수(= 봉투 수). 병합 전 원자료의 양.</summary>
        public long Received { get; private set; }
        /// <summary>실제 씬 반영 횟수. **검증 8이 재는 값이 이것이다.**</summary>
        public long Flushed { get; private set; }
        /// <summary>창을 건너뛴 즉시 반영 횟수. 위 Flushed 에 포함된다.</summary>
        public long Immediate { get; private set; }

        public double WindowMs { get { return _windowSec * 1000; } }

        public MergeScheduler(double windowMs)
        {
            _windowSec = windowMs / 1000.0;
        }

        /// <summary>수신 1건 표시. 창이 닫혀 있으면 연다.</summary>
        public void Mark(double now)
        {
            Received++;
            if (_pending) return;
            _pending = true;
            _flushAt = now + _windowSec;
        }

        /// <summary>
        /// 창을 기다리지 않고 다음 프레임에 반영한다.
        /// offline·stale 전이처럼 **늦게 알면 관제 판단이 틀어지는** 변화에만 쓴다.
        /// </summary>
        public void MarkImmediate(double now)
        {
            Received++;
            Immediate++;
            _pending = true;
            _flushAt = now;
        }

        /// <summary>참이면 이번 프레임에 씬을 갱신한다.</summary>
        public bool TryFlush(double now)
        {
            if (!_pending || now < _flushAt) return false;
            _pending = false;
            Flushed++;
            return true;
        }
    }
}
