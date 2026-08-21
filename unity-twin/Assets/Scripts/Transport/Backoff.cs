// Assets/Scripts/Transport/Backoff.cs
//
// 지수 백오프 + 지터.
//
// 숫자는 웹 대시보드(src/transport/backoff.ts)와 **일부러 같게** 두었다. 두 클라이언트가
// 같은 게이트웨이를 물고 있으므로 재접속 리듬이 다르면 "웹은 붙었는데 Unity는 아직"
// 같은 상태가 생겨, 검증 9(두 화면 일치)에서 계약 문제와 재접속 타이밍 문제를 구분하기 어렵다.

using System;

namespace HybridDt.Twin.Transport
{
    public static class Backoff
    {
        /// <summary>첫 재시도까지. 목 서버 재기동 정도는 거의 즉시 붙어야 한다.</summary>
        public const double InitialMs = 500;
        public const double Factor = 2;
        /// <summary>상한. 이보다 길어지면 사람이 다시 재생 버튼을 누르는 편이 빠르다.</summary>
        public const double MaxMs = 15000;
        public const double JitterRatio = 0.25;

        private static readonly Random Rng = new Random();

        public static double DelayMs(int attempt)
        {
            double raw = InitialMs * Math.Pow(Factor, Math.Max(0, attempt - 1));
            double capped = Math.Min(raw, MaxMs);
            double jitter;
            lock (Rng) jitter = capped * JitterRatio * (Rng.NextDouble() * 2 - 1);
            return Math.Max(100, Math.Round(capped + jitter));
        }
    }
}
