// Assets/Scripts/Diagnostics/SceneUpdateMeter.cs
//
// 검증 8을 **실측하기 위한** 계측기.
//
// "씬 반영이 초당 10회를 넘지 않는다"는 눈으로 확인할 수 없다. 병합 창이 제대로
// 걸려 있는지, 그리고 그것과 별개로 보간 렌더가 실제 60fps 로 도는지를 같은 화면에서
// 나란히 보여야 **둘이 분리되어 있다는 것**이 증명된다. 한 숫자만 보면 "화면이
// 부드러우니 됐다"로 끝나고, 그러면 병합이 실제로는 안 걸려 있어도 모른다.
//
// 계약이 아니라 계측이므로 이 파일이 없어도 뷰어는 동작한다.

using System.Collections.Generic;

namespace HybridDt.Twin.Diagnostics
{
    public sealed class SceneUpdateMeter
    {
        private const double WindowSec = 1.0;

        private readonly Queue<double> _sceneUpdates = new Queue<double>();
        private readonly Queue<double> _frames = new Queue<double>();
        private readonly Queue<double> _envelopes = new Queue<double>();

        /// <summary>씬 반영 누적 횟수.</summary>
        public long TotalSceneUpdates { get; private set; }
        /// <summary>수신 봉투 누적 건수. **씬 반영보다 훨씬 커야 정상이다** — 데이터는 전량 받는다.</summary>
        public long TotalEnvelopes { get; private set; }
        /// <summary>관측된 최대 씬 반영률(회/초). 검증 8이 보는 값.</summary>
        public double PeakSceneUpdatesPerSec { get; private set; }

        public void RecordSceneUpdate(double now)
        {
            TotalSceneUpdates++;
            _sceneUpdates.Enqueue(now);
            Trim(_sceneUpdates, now);
            double rate = _sceneUpdates.Count / WindowSec;
            if (rate > PeakSceneUpdatesPerSec) PeakSceneUpdatesPerSec = rate;
        }

        public void RecordFrame(double now)
        {
            _frames.Enqueue(now);
            Trim(_frames, now);
        }

        public void RecordEnvelope(double now)
        {
            TotalEnvelopes++;
            _envelopes.Enqueue(now);
            Trim(_envelopes, now);
        }

        public double SceneUpdatesPerSec { get { return _sceneUpdates.Count / WindowSec; } }
        public double FramesPerSec { get { return _frames.Count / WindowSec; } }
        public double EnvelopesPerSec { get { return _envelopes.Count / WindowSec; } }

        private static void Trim(Queue<double> q, double now)
        {
            while (q.Count > 0 && now - q.Peek() > WindowSec) q.Dequeue();
        }
    }
}
