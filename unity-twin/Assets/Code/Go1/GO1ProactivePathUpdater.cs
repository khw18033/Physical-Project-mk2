using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 실제 GO1이 경로를 따라가는 동안 디지털 트윈(360 카메라 장애물 포함)을 주기적으로 보고
/// 멈추지 않고 경로를 갱신하는 컴포넌트입니다.
///
/// 흐름:
/// 1) 실제 GO1의 남은 경로(현재 위치 ~ 목표)가 트윈 장애물과 겹치는지 검사
///    - 안 겹치면 아무것도 보내지 않음 → 기존 경로로 계속 주행
/// 2) 겹치면 현재 위치에서 목표까지 NavMesh로 새 경로 계산
///    - 새 경로가 남은 경로와 거의 같으면 그대로 주행
///    - 다르면 PATH_CANCEL/정지 없이 현재 위치 기준으로 새 경로만 전송
/// 3) 우회 경로를 못 찾으면 false 반환 → 기존 정지 + ML-Agents 재탐색이 비상용으로 동작
///
/// 이 컴포넌트를 끄거나 빼면 기존 동작과 완전히 같습니다.
/// </summary>
[DisallowMultipleComponent]
[RequireComponent(typeof(GO1Agent))]
public class GO1ProactivePathUpdater : MonoBehaviour
{
    [Header("References")]
    public GO1Agent agent;
    public GO1PathPlanner pathPlanner;

    public enum ResponseMode
    {
        NoStopSwap,      // 제안: 막히면 트윈에서 새 경로를 계산해 정지 없이 교체
        StopAndReplan    // 기존: 막히면 정지 후 현재 위치에서 ML-Agent로 경로 재생성 (가상 전용에서만 이 컴포넌트가 실행)
    }

    [Header("Condition")]
    [Tooltip("막힘을 감지했을 때의 대응. 감지 방식(주기, 연속 횟수, 검사 반경)은 두 조건이 같습니다.")]
    public ResponseMode responseMode = ResponseMode.NoStopSwap;

    [Tooltip("NoStopSwap에서 우회 경로 계산이 연속 이 횟수만큼 실패하면 정지 재탐색으로 넘깁니다 (가상 전용).")]
    public int fallbackAfterFailedChecks = 2;

    [Header("Check")]
    [Tooltip("남은 경로 안전 검사 주기(초).")]
    public float checkInterval = 0.25f;

    [Tooltip("360 카메라 인식 흔들림 대비: 연속으로 이 횟수만큼 막혀야 경로를 바꿉니다.")]
    public int confirmBlockedChecks = 2;

    [Tooltip("새 경로와 남은 경로의 최대 차이가 이 값(m) 이하면 같은 경로로 보고 보내지 않습니다.")]
    public float samePathTolerance = 0.20f;

    [Tooltip("경로를 바꾼 직후 다음 교체까지 최소 간격(초). 경로가 왔다 갔다 하는 것을 막습니다.")]
    public float minSwitchInterval = 1.5f;

    [Header("Twin NavMesh")]
    [Tooltip("Obstacle 레이어 장애물에 NavMeshObstacle(carve)이 없으면 자동으로 붙입니다. " +
             "없으면 NavMesh 경로가 360 큐브를 무시합니다.")]
    public bool autoCarveObstacles = true;
    public string obstacleTagName = "Obstacle";

    [Header("Virtual Test")]
    [Tooltip("가상 전용 테스트: 이 키를 누르면 남은 경로 앞쪽에 장애물 큐브를 하나 놓습니다.")]
    public KeyCode spawnTestObstacleKey = KeyCode.K;
    [Tooltip("테스트 장애물을 현재 위치에서 경로를 따라 몇 m 앞에 둘지.")]
    public float testObstacleAhead = 1.5f;
    public Vector3 testObstacleSize = new Vector3(0.5f, 0.6f, 0.5f);

    [Header("Debug")]
    public bool debugLog = true;

    public int SwitchCountThisMission { get; private set; }
    public int StopReplanRequests { get; private set; }
    public int FallbackStopReplans { get; private set; }
    public int BlockedDetections { get; private set; }
    public float FirstBlockedTime { get; private set; } = -1f;

    private int failedUpdateStreak;

    /// <summary>평가 러너가 trial 시작 때 호출.</summary>
    public void ResetCounters()
    {
        SwitchCountThisMission = 0;
        StopReplanRequests = 0;
        FallbackStopReplans = 0;
        BlockedDetections = 0;
        FirstBlockedTime = -1f;
        blockedStreak = 0;
        failedUpdateStreak = 0;
        lastSwitchTime = -999f;
    }

    private float nextCheckTime;
    private float lastSwitchTime = -999f;
    private int blockedStreak;
    private readonly List<Vector3> remainingBuffer = new List<Vector3>();
    private NavMeshPath navPath;

    private void Awake()
    {
        if (agent == null) agent = GetComponent<GO1Agent>();
        if (pathPlanner == null) pathPlanner = GetComponent<GO1PathPlanner>();
        navPath = new NavMeshPath();
    }

    private void Update()
    {
        if (agent != null && Input.GetKeyDown(spawnTestObstacleKey))
            SpawnTestObstacleAhead();

        if (agent == null || !CanRun())
        {
            blockedStreak = 0;
            return;
        }

        if (Time.time < nextCheckTime)
            return;
        nextCheckTime = Time.time + Mathf.Max(0.05f, checkInterval);

        if (autoCarveObstacles)
            EnsureObstaclesCarve();

        if (!BuildRemainingPath(remainingBuffer))
            return;

        if (!agent.ProactiveIsWorldPathBlocked(remainingBuffer, "proactive-remaining"))
        {
            blockedStreak = 0;   // 남은 경로 안전 → 그대로 주행
            return;
        }

        blockedStreak++;
        if (blockedStreak < Mathf.Max(1, confirmBlockedChecks))
            return;

        BlockedDetections++;
        if (FirstBlockedTime < 0f)
            FirstBlockedTime = Time.time;

        if (IsVirtual() && responseMode == ResponseMode.StopAndReplan)
        {
            RequestStopReplan("stop_replan");
            return;
        }

        if (TryUpdateNow("twin_periodic"))
        {
            failedUpdateStreak = 0;
            return;
        }

        failedUpdateStreak++;
        if (IsVirtual() && failedUpdateStreak >= Mathf.Max(1, fallbackAfterFailedChecks))
        {
            failedUpdateStreak = 0;
            if (RequestStopReplan("fallback_no_detour"))
                FallbackStopReplans++;
        }
    }

    private bool RequestStopReplan(string reason)
    {
        blockedStreak = 0;
        bool ok = agent.RequestMlAgentReplanFromLocalReplay(reason);
        if (ok)
        {
            StopReplanRequests++;
            Log("정지 후 재탐색 요청(가상) | reason=" + reason + ", count=" + StopReplanRequests);
        }
        return ok;
    }

    /// <summary>
    /// 지금 바로 새 경로 계산과 전송을 시도합니다.
    /// true: 남은 경로가 안전하거나, 정지 없이 새 경로로 교체함 (정지 재탐색 불필요)
    /// false: 우회 경로 없음 → 호출한 쪽이 기존 정지 재탐색을 실행해야 함
    /// </summary>
    public bool TryUpdateNow(string reason)
    {
        if (agent == null || !CanRun())
            return false;

        if (autoCarveObstacles)
            EnsureObstaclesCarve();

        if (!BuildRemainingPath(remainingBuffer))
            return false;

        if (!agent.ProactiveIsWorldPathBlocked(remainingBuffer, "proactive-remaining"))
        {
            blockedStreak = 0;
            return true;
        }

        List<Vector3> newPath;
        if (!TryPlanFromCurrentPose(out newPath))
        {
            Log("우회 경로 없음 → 기존 정지 재탐색으로 넘김 | reason=" + reason);
            return false;
        }

        float diff = MaxDeviation(newPath, remainingBuffer);
        if (diff <= samePathTolerance)
        {
            // 경로가 사실상 같음 → 보내지 않고 계속 주행
            blockedStreak = 0;
            return true;
        }

        if (Time.time - lastSwitchTime < minSwitchInterval)
        {
            // 방금 바꿨으면 잠깐 기다렸다가 다음 검사에서 다시 판단 (정지 안 함)
            return true;
        }

        bool sent = IsVirtual()
            ? agent.ProactiveSwapLocalReplayPath(newPath, reason)
            : agent.ProactiveSendPathWithoutStop(newPath, reason);
        if (!sent)
            return false;

        lastSwitchTime = Time.time;
        blockedStreak = 0;
        SwitchCountThisMission++;

        Log("정지 없이 경로 교체" + (IsVirtual() ? "(가상)" : "(실제)") + " | reason=" + reason +
            ", points=" + newPath.Count +
            ", diff=" + diff.ToString("F2") + "m" +
            ", count=" + SwitchCountThisMission);
        return true;
    }

    private bool CanRun()
    {
        return isActiveAndEnabled &&
               agent.enableRuntimeReplanning &&
               agent.enableObstacleTriggeredReplan &&   // C2_NO_REPLAN 실험 조건 존중
               IsFollowing() &&
               agent.target != null;
    }

    private bool IsVirtual() => agent.virtualOnlyMode;

    // 가상 전용이면 가상 GO1의 Unity 내 경로 재생, 아니면 실제 GO1 경로 추종
    private bool IsFollowing() =>
        IsVirtual() ? agent.ProactiveIsLocalReplayActive : agent.IsRealPathFollowing();

    private IReadOnlyList<Vector3> CurrentPath() =>
        IsVirtual() ? agent.ProactiveLocalReplayPath : agent.ReplanCurrentSentPath;

    private void SpawnTestObstacleAhead()
    {
        if (!IsFollowing() || !BuildRemainingPath(remainingBuffer))
        {
            Log("테스트 장애물: 주행 중이 아니라서 놓지 않음");
            return;
        }

        // 남은 경로를 따라 testObstacleAhead 만큼 앞 지점
        Vector3 point = remainingBuffer[remainingBuffer.Count - 1];
        float left = testObstacleAhead;
        for (int i = 0; i < remainingBuffer.Count - 1; i++)
        {
            float len = Vector3.Distance(remainingBuffer[i], remainingBuffer[i + 1]);
            if (len >= left)
            {
                point = Vector3.Lerp(remainingBuffer[i], remainingBuffer[i + 1], left / Mathf.Max(0.0001f, len));
                break;
            }
            left -= len;
        }

        GameObject cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
        cube.name = "ProactiveTestObstacle";
        cube.transform.position = new Vector3(point.x, point.y + testObstacleSize.y * 0.5f, point.z);
        cube.transform.localScale = testObstacleSize;
        try { cube.tag = obstacleTagName; } catch { Log("Tag '" + obstacleTagName + "' 없음"); }
        int layer = LayerMask.NameToLayer("Obstacle");
        if (layer >= 0) cube.layer = layer;
        Log("테스트 장애물 생성 | pos=" + cube.transform.position);
    }

    // 현재 위치를 첫 점으로 하는 남은 경로 (현재 위치 → 가장 가까운 구간 끝 → ... → 마지막 점)
    private bool BuildRemainingPath(List<Vector3> output)
    {
        output.Clear();
        IReadOnlyList<Vector3> sent = CurrentPath();
        if (sent == null || sent.Count < 2)
            return false;

        Vector3 pos = agent.transform.position;
        int best = 0;
        float bestDist = float.MaxValue;
        for (int i = 0; i < sent.Count - 1; i++)
        {
            float d = DistancePointToSegmentXZ(pos, sent[i], sent[i + 1]);
            if (d < bestDist) { bestDist = d; best = i; }
        }

        output.Add(pos);
        for (int i = best + 1; i < sent.Count; i++)
            output.Add(sent[i]);

        return output.Count >= 2;
    }

    /// <summary>평가용: NavMesh 대신 쓸 경로 계획기 (현재 위치, 목표) → 경로. null이면 NavMesh.</summary>
    public System.Func<Vector3, Vector3, List<Vector3>> customPlanner;

    /// <summary>마지막 경로 계산에 걸린 시간(ms)과 누적 횟수/시간.</summary>
    public double LastPlanMs { get; private set; }
    public double TotalPlanMs { get; private set; }
    public int PlanCalls { get; private set; }
    public void ResetPlanStats() { LastPlanMs = 0; TotalPlanMs = 0; PlanCalls = 0; }

    private bool TryPlanFromCurrentPose(out List<Vector3> path)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        bool ok = PlanCore(out path);
        sw.Stop();
        LastPlanMs = sw.Elapsed.TotalMilliseconds;
        TotalPlanMs += LastPlanMs;
        PlanCalls++;
        // 장애물을 통과하는 경로면 쓰지 않음
        return ok && !agent.ProactiveIsWorldPathBlocked(path, "proactive-new");
    }

    private bool PlanCore(out List<Vector3> path)
    {
        path = null;
        if (customPlanner != null)
        {
            path = customPlanner(agent.transform.position, agent.target.position);
            return path != null && path.Count >= 2;
        }
        int mask = pathPlanner != null ? pathPlanner.areaMask : NavMesh.AllAreas;

        Vector3 from = agent.transform.position;
        NavMeshHit hit;
        if (NavMesh.SamplePosition(from, out hit, 0.5f, mask))
            from = hit.position;

        if (!NavMesh.CalculatePath(from, agent.target.position, mask, navPath) ||
            navPath.status != NavMeshPathStatus.PathComplete ||
            navPath.corners == null || navPath.corners.Length < 2)
        {
            return false;
        }

        path = new List<Vector3>(navPath.corners.Length);
        Vector3 start = agent.transform.position;
        start.y = navPath.corners[0].y;
        path.Add(start);   // 첫 점 = 현재 로봇 위치 (C++ 로컬 프레임 원점)
        for (int i = 1; i < navPath.corners.Length; i++)
            path.Add(navPath.corners[i]);

        return true;
    }

    private void EnsureObstaclesCarve()
    {
        GameObject[] obstacles;
        try { obstacles = GameObject.FindGameObjectsWithTag(obstacleTagName); }
        catch { return; }

        foreach (GameObject obj in obstacles)
        {
            if (obj == null || obj.GetComponent<NavMeshObstacle>() != null)
                continue;

            NavMeshObstacle nmo = obj.AddComponent<NavMeshObstacle>();
            nmo.shape = NavMeshObstacleShape.Box;
            nmo.carving = true;
            nmo.carveOnlyStationary = false;   // 360 큐브는 패킷마다 다시 생기므로 즉시 반영
            nmo.size = Vector3.one;            // 로컬 스케일을 따라감
            nmo.center = Vector3.zero;
        }
    }

    // 두 경로를 0.1 m 간격으로 샘플링한 대칭 최대 거리 (Hausdorff, XZ 평면)
    private static float MaxDeviation(List<Vector3> a, List<Vector3> b)
    {
        return Mathf.Max(OneSided(a, b), OneSided(b, a));
    }

    private static float OneSided(List<Vector3> from, List<Vector3> to)
    {
        float worst = 0f;
        for (int i = 0; i < from.Count - 1; i++)
        {
            float len = Vector3.Distance(from[i], from[i + 1]);
            int steps = Mathf.Max(1, Mathf.CeilToInt(len / 0.1f));
            for (int s = 0; s <= steps; s++)
            {
                Vector3 p = Vector3.Lerp(from[i], from[i + 1], (float)s / steps);
                float best = float.MaxValue;
                for (int j = 0; j < to.Count - 1; j++)
                    best = Mathf.Min(best, DistancePointToSegmentXZ(p, to[j], to[j + 1]));
                worst = Mathf.Max(worst, best);
            }
        }
        return worst;
    }

    private static float DistancePointToSegmentXZ(Vector3 point, Vector3 start, Vector3 end)
    {
        Vector2 p = new Vector2(point.x, point.z);
        Vector2 a = new Vector2(start.x, start.z);
        Vector2 ab = new Vector2(end.x, end.z) - a;
        if (ab.sqrMagnitude < 0.0001f)
            return Vector2.Distance(p, a);
        float t = Mathf.Clamp01(Vector2.Dot(p - a, ab) / ab.sqrMagnitude);
        return Vector2.Distance(p, a + ab * t);
    }

    private void Log(string msg)
    {
        if (debugLog)
            Debug.Log("[GO1ProactivePathUpdater] " + msg, this);
    }
}
