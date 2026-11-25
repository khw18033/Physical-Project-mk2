using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 가상 평가의 "온보드 반응형 로컬 플래너" 비교 조건용 Dynamic Window Approach (Fox et al., 1997).
///
/// 전역 경로는 처음 받은 것을 끝까지 쓰고 다시 계산하지 않는다. 매 제어 주기마다 가속 한계 안의
/// (v, w) 후보를 앞으로 굴려 보고, 통행 가능한 것 중 점수가 가장 높은 것을 고른다.
/// 통행 가능 여부는 로봇 몸통 크기의 캡슐이 지도의 충돌체(가구/벽 + 로봇이 탐지해 트윈에 반영된 장애물)와
/// 겹치는지로 본다. 탐지 전의 장애물은 지도에 없으므로 보이지 않는다.
///
/// 가상 GO1의 pose를 직접 움직이므로 agent.ProactiveReplayExternallyDriven 를 켠 동안만 쓴다.
/// </summary>
[DisallowMultipleComponent]
public class GO1DwaLocalController : MonoBehaviour
{
    public float maxSpeed = 0.4f;
    public float maxYawRateDeg = 110f;
    public float accel = 1.0f;            // m/s^2
    public float yawAccelDeg = 360f;      // deg/s^2
    public float controlPeriod = 0.1f;
    public float horizon = 1.5f;
    public float rolloutStep = 0.1f;
    public int speedSamples = 4;
    public int yawSamples = 11;
    public float lookahead = 1.2f;
    [Tooltip("통행 가능 판정에 쓰는 몸통 반경(m). 시뮬 로봇 충돌 반경 0.162 + 여유.")]
    public float bodyRadius = 0.18f;
    [Tooltip("여유 점수를 매기는 추가 반경 단계(m).")]
    public float[] clearanceSteps = { 0.10f, 0.20f, 0.32f };
    public float wGoal = 1.0f, wHeading = 0.3f, wClearance = 0.3f, wSpeed = 0.2f;

    public int StuckTicks { get; private set; }
    public int Ticks { get; private set; }

    private GO1Agent agent;
    private bool active;
    private float yaw;          // 도, 진행 방향 = (sin, 0, cos)
    private float v, w;         // m/s, deg/s
    private float nextTick;
    private float progress;     // 전역 경로 위 진행 거리
    private readonly List<Vector3> path = new List<Vector3>();
    private float planeY;

    public void Begin(GO1Agent a)
    {
        agent = a;
        path.Clear();
        path.AddRange(a.ProactiveLocalReplayPath);
        Vector3 f = -a.transform.right; f.y = 0f;
        yaw = Mathf.Atan2(f.x, f.z) * Mathf.Rad2Deg;
        v = 0f; w = 0f; progress = 0f; nextTick = 0f;
        StuckTicks = 0; Ticks = 0;
        planeY = a.transform.position.y;
        mask = a.ProactiveObstacleLayerMask;
        a.ProactiveReplayExternallyDriven = true;
        active = true;
    }

    public void End()
    {
        active = false;
        if (agent != null) agent.ProactiveReplayExternallyDriven = false;
    }

    private static Vector3 Dir(float yawDeg)
    {
        float r = yawDeg * Mathf.Deg2Rad;
        return new Vector3(Mathf.Sin(r), 0f, Mathf.Cos(r));
    }

    private int mask;

    // 몸통 반경 + extra 인 캡슐이 충돌체와 겹치지 않는가
    private bool Free(Vector3 p, float extra = 0f) =>
        !Physics.CheckCapsule(p + Vector3.up * 0.2f, p + Vector3.up * 0.5f, bodyRadius + extra, mask, QueryTriggerInteraction.Ignore);

    // 여유 단계: 0 = 몸통만 통과, clearanceSteps.Length = 가장 넓은 여유까지 비어 있음. upTo 단계까지만 검사.
    private int ClearLevel(Vector3 p, int upTo)
    {
        int level = 0;
        while (level < upTo && Free(p, clearanceSteps[level])) level++;
        return level;
    }

    private void Update()
    {
        if (!active || agent == null || !agent.ProactiveIsLocalReplayActive || path.Count < 2)
            return;

        Vector3 pos = agent.transform.position;
        Vector3 goal = agent.target.position;
        Vector2 dg = new Vector2(goal.x - pos.x, goal.z - pos.z);
        if (dg.magnitude <= agent.ProactiveGoalArrivalDistance)
        {
            active = false;
            agent.ProactiveExternalComplete(true, "local_replay_goal", dg.magnitude);
            return;
        }

        if (Time.time >= nextTick)
        {
            nextTick = Time.time + controlPeriod;
            Choose(pos);
        }

        float dt = Time.deltaTime;
        yaw += w * dt;
        Vector3 next = pos + Dir(yaw) * (v * dt);
        next.y = planeY;
        agent.ProactiveExternalSetPose(next, Quaternion.LookRotation(Dir(yaw)) * Quaternion.Euler(0f, 90f, 0f));
    }

    private void Choose(Vector3 pos)
    {
        Ticks++;
        Vector3 target = LookaheadPoint(pos);
        bool startFree = Free(pos);

        float dv = accel * controlPeriod, dw = yawAccelDeg * controlPeriod;
        float vMin = Mathf.Max(0f, v - dv), vMax = Mathf.Min(maxSpeed, v + dv);
        float wMin = Mathf.Max(-maxYawRateDeg, w - dw), wMax = Mathf.Min(maxYawRateDeg, w + dw);

        float bestScore = float.NegativeInfinity, bestV = 0f, bestW = 0f;
        bool found = false;
        float norm = lookahead + maxSpeed * horizon;
        int steps = Mathf.Max(1, Mathf.RoundToInt(horizon / rolloutStep));

        for (int i = 0; i < speedSamples; i++)
        {
            float cv = speedSamples > 1 ? Mathf.Lerp(vMin, vMax, (float)i / (speedSamples - 1)) : vMax;
            if (cv < 0.02f) continue;
            for (int j = 0; j < yawSamples; j++)
            {
                float cw = yawSamples > 1 ? Mathf.Lerp(wMin, wMax, (float)j / (yawSamples - 1)) : 0f;
                Vector3 p = pos; float y = yaw; int minLevel = clearanceSteps.Length; bool ok = true;
                for (int s = 1; s <= steps; s++)
                {
                    y += cw * rolloutStep;
                    p += Dir(y) * (cv * rolloutStep);
                    if (!Free(p))
                    {
                        // 이미 겹친 상태(아주 늦게 탐지)에서 시작했으면 처음 0.5초는 봐준다
                        if (startFree || s * rolloutStep > 0.5f) { ok = false; break; }
                        minLevel = 0;
                        continue;
                    }
                    minLevel = ClearLevel(p, minLevel);
                }
                if (!ok) continue;
                // 멈출 수 있어야 한다: 끝점에서 정지 거리만큼 더 나아간 곳도 비어 있어야 함
                if (!Free(p + Dir(y) * (cv * cv / (2f * accel)))) continue;

                Vector3 toT = target - p; toT.y = 0f;
                float goalScore = 1f - Mathf.Clamp01(toT.magnitude / norm);
                float headScore = toT.sqrMagnitude > 1e-6f ? 1f - Vector3.Angle(Dir(y), toT) / 180f : 1f;
                float score = wGoal * goalScore + wHeading * headScore +
                              wClearance * ((float)minLevel / clearanceSteps.Length) + wSpeed * (cv / maxSpeed);
                if (score > bestScore) { bestScore = score; bestV = cv; bestW = cw; found = true; }
            }
        }

        if (found) { v = bestV; w = bestW; return; }

        // 갈 수 있는 후보가 없음: 제자리에서 돈다. 목표 방향에서 가까운 순서로, 앞으로 0.4 m가 비어 있는 방향을 찾는다.
        StuckTicks++;
        v = 0f;
        Vector3 d = target - pos; d.y = 0f;
        float targetYaw = d.sqrMagnitude > 1e-6f ? Mathf.Atan2(d.x, d.z) * Mathf.Rad2Deg : yaw;
        float wantYaw = targetYaw;
        for (int k = 0; k <= 12; k++)
        {
            bool hit = false;
            foreach (float sign in new[] { 1f, -1f })
            {
                float cand = targetYaw + sign * k * 15f;
                bool free = true;
                for (float s = 0.1f; s <= 0.4f && free; s += 0.1f) free = Free(pos + Dir(cand) * s);
                if (free) { wantYaw = cand; hit = true; break; }
            }
            if (hit) break;
        }
        float err = Mathf.DeltaAngle(yaw, wantYaw);
        w = Mathf.Abs(err) < 3f ? 0f : Mathf.Sign(err) * Mathf.Min(maxYawRateDeg, Mathf.Abs(w) + dw);
        if (Mathf.Abs(err) < 3f) v = Mathf.Min(maxSpeed, dv);   // 방향이 맞으면 천천히 출발
    }

    // 전역 경로에서 현재 진행 거리 + lookahead 지점. 그 지점이 지도 밖이면(장애물 안) 더 앞으로 민다.
    private Vector3 LookaheadPoint(Vector3 pos)
    {
        float acc = 0f, bestS = progress, bestD = float.MaxValue;
        for (int i = 0; i < path.Count - 1; i++)
        {
            Vector3 a = path[i], b = path[i + 1];
            float len = Planar(a, b);
            if (len > 1e-4f)
            {
                Vector2 ab = new Vector2(b.x - a.x, b.z - a.z);
                float t = Mathf.Clamp01(Vector2.Dot(new Vector2(pos.x - a.x, pos.z - a.z), ab) / ab.sqrMagnitude);
                float s = acc + t * len;
                float d = Planar(pos, Vector3.Lerp(a, b, t));
                if (s >= progress - 0.3f && d < bestD) { bestD = d; bestS = s; }
            }
            acc += len;
        }
        progress = Mathf.Max(progress, bestS);
        float total = acc;
        for (float extra = 0f; extra <= 2.0f; extra += 0.2f)
        {
            float s = Mathf.Min(total, progress + lookahead + extra);
            Vector3 p = PointAt(s);
            if (Free(p) || s >= total) return p;
        }
        return PointAt(Mathf.Min(total, progress + lookahead));
    }

    private Vector3 PointAt(float s)
    {
        for (int i = 0; i < path.Count - 1; i++)
        {
            float len = Planar(path[i], path[i + 1]);
            if (s <= len || i == path.Count - 2)
                return Vector3.Lerp(path[i], path[i + 1], len > 1e-4f ? Mathf.Clamp01(s / len) : 0f);
            s -= len;
        }
        return path[path.Count - 1];
    }

    private static float Planar(Vector3 a, Vector3 b)
    {
        a.y = 0f; b.y = 0f;
        return Vector3.Distance(a, b);
    }
}
