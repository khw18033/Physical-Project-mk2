using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// GO1Agent에서 장애물 기반 재탐색 흐름을 분리한 컴포넌트입니다.
///
/// 담당 범위:
/// 1) 실제 전송 경로와 새 장애물의 교차/근접 판정
/// 2) C2/C3 재탐색 활성 여부 및 횟수/cooldown 관리
/// 3) PATH_CANCEL + 정지 + ACK 대기
/// 4) 실제 GO1 pose 동기화 후 새 가상 경로 생성 요청
/// 5) 생성 경로가 유효하지 않을 때 재생성 재시도
/// 6) 재전송 직후 추가 JSON/재탐색 잠금
///
/// ML-Agents의 관측, 행동, 보상, waypoint 추종은 GO1Agent가 계속 담당합니다.
/// 기존 Inspector 값 보존을 위해 재탐색 설정값은 현재 GO1Agent에 유지하고,
/// 이 클래스가 해당 값을 읽어 실행합니다.
/// </summary>
[DisallowMultipleComponent]
[RequireComponent(typeof(GO1PathPlanner))]
public class GO1ReplanController : MonoBehaviour
{
    [Header("References")]
    [Tooltip("주행 정책과 실제 GO1 연동 상태를 소유한 GO1Agent입니다.")]
    public GO1Agent agent;

    [Tooltip("NavMesh 경로 계산을 담당하는 컴포넌트입니다.")]
    public GO1PathPlanner pathPlanner;

    private Coroutine obstacleReplanCoroutine;
    private Coroutine generatedPathRetryCoroutine;

    private int obstacleReplanCountThisMission;
    private bool replanLimitLogPrintedThisMission;
    private int generatedPathRetryCount;

    private bool runtimePathWaitingForSend;
    private float lastReplanTime = -999f;
    private float postReplanJsonBlockUntilTime = -999f;

    /// <summary>
    /// PATH_CANCEL/재탐색 코루틴 또는 생성 경로 재시도 코루틴이 실행 중인지 나타냅니다.
    /// </summary>
    public bool IsBusy =>
        obstacleReplanCoroutine != null ||
        generatedPathRetryCoroutine != null;

    /// <summary>
    /// 재탐색으로 만든 가상 경로가 실제 GO1에 전송되기를 기다리는 상태입니다.
    /// GO1Agent.StartMission()은 이 값으로 수동 미션과 재탐색 미션을 구분합니다.
    /// </summary>
    public bool IsRuntimePathWaitingForSend => runtimePathWaitingForSend;

    public int ObstacleReplanCountThisMission => obstacleReplanCountThisMission;

    private void Awake()
    {
        EnsureReferences();
    }

    private void OnDisable()
    {
        StopOwnedCoroutines();
        runtimePathWaitingForSend = false;
        generatedPathRetryCount = 0;
        postReplanJsonBlockUntilTime = -999f;
    }

    public void EnsureReferences(
        GO1Agent preferredAgent = null,
        GO1PathPlanner preferredPathPlanner = null)
    {
        if (preferredAgent != null)
            agent = preferredAgent;

        if (agent == null)
            agent = GetComponent<GO1Agent>();

        if (preferredPathPlanner != null)
            pathPlanner = preferredPathPlanner;

        if (pathPlanner == null)
            pathPlanner = GetComponent<GO1PathPlanner>();

        if (agent != null && agent.replanController != this)
            agent.replanController = this;
    }

    /// <summary>
    /// 사용자가 새 M키 미션을 시작할 때 호출합니다.
    /// 이전 미션의 재탐색 횟수, 잠금, 재시도 상태를 초기화합니다.
    /// </summary>
    public void ResetForManualMission()
    {
        StopOwnedCoroutines();

        obstacleReplanCountThisMission = 0;
        replanLimitLogPrintedThisMission = false;
        generatedPathRetryCount = 0;
        runtimePathWaitingForSend = false;
        postReplanJsonBlockUntilTime = -999f;
        lastReplanTime = -999f;
    }

    /// <summary>
    /// 미션 정지 또는 실제 경로 완료 시 컨트롤러의 모든 런타임 상태를 초기화합니다.
    /// </summary>
    public void ResetAll(string reason)
    {
        StopOwnedCoroutines();

        obstacleReplanCountThisMission = 0;
        replanLimitLogPrintedThisMission = false;
        generatedPathRetryCount = 0;
        runtimePathWaitingForSend = false;
        postReplanJsonBlockUntilTime = -999f;
        lastReplanTime = -999f;

        if (agent != null && agent.debugRuntimeReplan)
            Debug.Log("[GO1ReplanController] 상태 초기화 | reason=" + reason, this);
    }

    public bool IsPostReplanJsonBlocked()
    {
        return Time.time < postReplanJsonBlockUntilTime;
    }

    public float GetPostReplanJsonBlockRemaining()
    {
        return Mathf.Max(0f, postReplanJsonBlockUntilTime - Time.time);
    }

    /// <summary>
    /// 소화기 landmark 보정 등 GO1Agent 내부의 다른 재탐색 흐름도
    /// 동일한 경로 전송/재시도 상태를 사용할 수 있도록 제공합니다.
    /// </summary>
    public void MarkRuntimePathWaitingForSend()
    {
        runtimePathWaitingForSend = true;
    }

    /// <summary>
    /// GO1Agent가 새 경로를 C++에 실제 전송한 직후 호출합니다.
    /// 재탐색 경로가 아니면 아무 동작도 하지 않습니다.
    /// </summary>
    public void NotifyPathSent()
    {
        if (!runtimePathWaitingForSend)
            return;

        runtimePathWaitingForSend = false;
        generatedPathRetryCount = 0;
        BeginPostReplanLock();
    }

    /// <summary>
    /// Go1ObstacleJsonReceiver가 새 장애물을 Unity에 생성/갱신한 뒤 호출합니다.
    /// C2에서도 경로 차단 여부는 기록하고, C3에서만 재탐색을 실행합니다.
    /// </summary>
    public void OnRuntimeObstacleUpdated(GameObject obstacle)
    {
        EnsureReferences();

        if (agent == null || obstacle == null)
            return;

        // 실제 GO1이 전송 경로를 따라가는 동안만 현재 전송 경로 차단을 판정합니다.
        if (!agent.IsRealPathFollowing())
            return;

        float obstacleDistanceToPath;
        float obstacleBlockThreshold;
        int obstacleClosestSegment;

        bool pathBlocked = IsObstacleBlockingCurrentPath(
            obstacle,
            out obstacleDistanceToPath,
            out obstacleBlockThreshold,
            out obstacleClosestSegment
        );

        bool replanRequested = false;
        string skipReason = pathBlocked ? "" : "not_blocking_path";

        if (pathBlocked)
        {
            if (!agent.enableRuntimeReplanning)
            {
                skipReason = "runtime_replanning_disabled";
            }
            else if (!agent.enableObstacleTriggeredReplan)
            {
                // C2_NO_REPLAN에서 주로 이 경로를 사용합니다.
                skipReason = "obstacle_triggered_replan_disabled";
            }
            else if (IsBusy)
            {
                skipReason = "already_replanning";
            }
            else if (IsPostReplanJsonBlocked())
            {
                skipReason = "post_replan_lock";
            }
            else if (Time.time - lastReplanTime < agent.replanCooldown)
            {
                skipReason = "replan_cooldown";
            }
            else
            {
                int maxCount = Mathf.Max(0, agent.maxObstacleReplanCountPerMission);

                if (obstacleReplanCountThisMission >= maxCount)
                {
                    skipReason = "replan_limit_reached";

                    if (agent.printReplanLimitLog && !replanLimitLogPrintedThisMission)
                    {
                        Debug.LogWarning(
                            "[GO1ReplanController] 장애물 기반 경로 재설정 제한 도달 | " +
                            "count=" + obstacleReplanCountThisMission +
                            "/" + maxCount +
                            ". 이후 장애물은 감지해도 재탐색하지 않습니다.",
                            this
                        );

                        replanLimitLogPrintedThisMission = true;
                    }
                }
                else
                {
                    replanRequested = true;
                    skipReason = "";
                }
            }
        }

        agent.ReplanWriteObstacleEvent(
            obstacle,
            obstacleDistanceToPath,
            obstacleBlockThreshold,
            obstacleClosestSegment,
            pathBlocked,
            replanRequested,
            skipReason
        );

        if (!replanRequested)
            return;

        int allowedMaxCount = Mathf.Max(0, agent.maxObstacleReplanCountPerMission);
        obstacleReplanCountThisMission++;
        agent.ReplanBeginExperiment(obstacle);

        if (agent.debugRuntimeReplan)
        {
            Debug.Log(
                "[GO1ReplanController] 장애물 기반 재탐색 실행 | " +
                "count=" + obstacleReplanCountThisMission +
                "/" + allowedMaxCount,
                this
            );
        }

        StartObstacleReplan(obstacle);
    }

    /// <summary>
    /// 외부 정책/스크립트가 장애물을 직접 지정해 재탐색을 요청할 때 사용합니다.
    /// 기존 GO1Agent API와의 호환을 위해 경로 차단 거리 검사는 생략합니다.
    /// </summary>
    public bool RequestObstacleTriggeredReplanFromPolicy(Transform blockingObstacle = null)
    {
        EnsureReferences();

        if (agent == null ||
            !agent.enableRuntimeReplanning ||
            !agent.enableObstacleTriggeredReplan ||
            IsBusy)
        {
            return false;
        }

        StartObstacleReplan(
            blockingObstacle != null ? blockingObstacle.gameObject : null
        );

        return true;
    }

    /// <summary>
    /// SendPathToRobot()에서 재탐색 경로가 너무 짧거나 장애물을 통과할 때 호출합니다.
    /// </summary>
    public bool TryScheduleGeneratedPathRetry(string reason)
    {
        EnsureReferences();

        if (agent == null ||
            !runtimePathWaitingForSend ||
            !agent.retryRuntimeReplanWhenGeneratedPathInvalid)
        {
            return false;
        }

        int maxRetry = Mathf.Max(0, agent.maxRuntimeReplanGenerateRetryCount);

        if (generatedPathRetryCount >= maxRetry)
        {
            Debug.LogWarning(
                "[GO1ReplanController] 재탐색 경로 재생성 최대 횟수 도달. " +
                "더 이상 새 경로를 보내지 않습니다. reason=" + reason +
                ", retry=" + generatedPathRetryCount + "/" + maxRetry,
                this
            );

            runtimePathWaitingForSend = false;
            generatedPathRetryCount = 0;
            agent.ReplanAbortAndEnableManualControl();
            return false;
        }

        generatedPathRetryCount++;

        if (generatedPathRetryCoroutine != null)
            StopCoroutine(generatedPathRetryCoroutine);

        generatedPathRetryCoroutine = StartCoroutine(
            RetryGeneratedPathRoutine(reason, generatedPathRetryCount, maxRetry)
        );

        return true;
    }

    private void StartObstacleReplan(GameObject blockingObstacle)
    {
        if (obstacleReplanCoroutine != null)
            StopCoroutine(obstacleReplanCoroutine);

        obstacleReplanCoroutine = StartCoroutine(
            StopAndReplanRoutine(blockingObstacle)
        );
    }

    private IEnumerator StopAndReplanRoutine(GameObject blockingObstacle)
    {
        lastReplanTime = Time.time;

        if (agent.debugRuntimeReplan)
        {
            string obstacleName = blockingObstacle != null
                ? blockingObstacle.name
                : "policy_request";

            Debug.Log(
                "[GO1ReplanController] 경로 차단 감지 → 실제 GO1 정지 + 재탐색 시작 | " +
                "obstacle=" + obstacleName,
                this
            );
        }

        // 1. 기존 실제 경로 명령과 가상 주행 상태를 정리합니다.
        agent.ReplanPrepareForRuntimeStop();
        generatedPathRetryCount = 0;

        if (generatedPathRetryCoroutine != null)
        {
            StopCoroutine(generatedPathRetryCoroutine);
            generatedPathRetryCoroutine = null;
        }

        // 2. C++ path follower의 기존 waypoint를 확실히 취소하고 실제 GO1을 정지합니다.
        if (agent.useSafeCancelBeforeReplan)
        {
            yield return StartCoroutine(agent.ReplanExecuteCancelAndStopBurst());
        }
        else
        {
            if (agent.pathSender != null)
                agent.pathSender.SendPathCancel();

            UnityTeleopAndMirror utm = agent.ReplanTeleop;
            if (utm != null)
            {
                utm.enableTeleop = true;
                utm.SendTeleopCmd(0f, 0f, 0f, 1);
                utm.driveByState = true;
            }

            if (agent.replanStopWaitTime > 0f)
                yield return new WaitForSeconds(agent.replanStopWaitTime);

            if (agent.releaseEstopBeforeReplan && utm != null)
                utm.SendTeleopCmd(0f, 0f, 0f, 0);
        }

        // 3. NavMeshObstacle carving 반영을 기다립니다.
        if (agent.navMeshCarvingWaitTime > 0f)
            yield return new WaitForSeconds(agent.navMeshCarvingWaitTime);

        // 4. PATH_CANCEL ACK 또는 최신 SDK state를 기준으로 가상 GO1 pose를 맞춥니다.
        agent.ReplanSyncVirtualPoseToSdk(
            "runtime-replan-before-new-path",
            true,
            agent.debugReplanPoseSync
        );

        string validationFailure;
        if (!agent.ReplanValidatePathToCurrentTarget(out validationFailure))
        {
            Debug.LogWarning(
                "[GO1ReplanController] 재탐색 실패: " +
                GetValidationFailureMessage(validationFailure),
                this
            );

            runtimePathWaitingForSend = false;
            obstacleReplanCoroutine = null;
            agent.ReplanAbortAndEnableManualControl();
            yield break;
        }

        if (agent.debugRuntimeReplan)
        {
            Debug.Log(
                "[GO1ReplanController] 새 장애물 반영 후 현재 pose 기준 " +
                "가상 GO1 재경로 탐색 시작",
                this
            );
        }

        // 5. GO1Agent가 ML-Agents 정책으로 새 경로를 기록하게 합니다.
        // SendPathToRobot()가 성공하면 NotifyPathSent()가 이 상태를 해제합니다.
        runtimePathWaitingForSend = true;
        agent.ReplanCompleteExperiment("obstacle_replan_ready");
        agent.ReplanStartVirtualPathGeneration();

        obstacleReplanCoroutine = null;
    }

    private IEnumerator RetryGeneratedPathRoutine(
        string reason,
        int attempt,
        int maxRetry)
    {
        if (agent.debugRuntimeReplanRetry)
        {
            Debug.LogWarning(
                "[GO1ReplanController] 생성된 재탐색 경로가 유효하지 않아 " +
                "다시 경로를 생성합니다. attempt=" + attempt + "/" + maxRetry +
                ", reason=" + reason,
                this
            );
        }

        agent.ReplanPrepareGeneratedPathRetry();

        if (agent.runtimeReplanRetryDelay > 0f)
            yield return new WaitForSeconds(agent.runtimeReplanRetryDelay);

        if (agent.navMeshCarvingWaitTime > 0f)
            yield return new WaitForSeconds(agent.navMeshCarvingWaitTime);

        string validationFailure;
        if (!agent.ReplanValidatePathToCurrentTarget(out validationFailure))
        {
            Debug.LogWarning(
                "[GO1ReplanController] 재탐색 재시도 실패: " +
                GetValidationFailureMessage(validationFailure),
                this
            );

            runtimePathWaitingForSend = false;
            generatedPathRetryCoroutine = null;
            agent.ReplanAbortAndEnableManualControl();
            yield break;
        }

        runtimePathWaitingForSend = true;
        agent.ReplanStartVirtualPathGeneration();
        generatedPathRetryCoroutine = null;
    }

    private bool IsObstacleBlockingCurrentPath(
        GameObject obstacle,
        out float minimumDistance,
        out float threshold,
        out int closestSegment)
    {
        minimumDistance = -1f;
        threshold = -1f;
        closestSegment = -1;

        IReadOnlyList<Vector3> sentPath = agent.ReplanCurrentSentPath;

        if (obstacle == null || sentPath == null || sentPath.Count < 2)
            return false;

        Bounds obstacleBounds = GetObstacleBounds(obstacle);
        Vector3 obstacleCenter = obstacleBounds.center;
        float obstacleRadius = Mathf.Max(
            obstacleBounds.extents.x,
            obstacleBounds.extents.z
        ) + agent.obstacleBoundsMargin;

        threshold = obstacleRadius + agent.pathBlockCheckRadius;

        int startSegment = GetClosestPathSegmentIndex(
            agent.transform.position,
            sentPath
        );
        startSegment = Mathf.Clamp(startSegment, 0, sentPath.Count - 2);

        minimumDistance = float.MaxValue;

        for (int i = startSegment; i < sentPath.Count - 1; i++)
        {
            float distance = DistancePointToSegmentXZ(
                obstacleCenter,
                sentPath[i],
                sentPath[i + 1]
            );

            if (distance < minimumDistance)
            {
                minimumDistance = distance;
                closestSegment = i;
            }
        }

        if (minimumDistance == float.MaxValue)
            minimumDistance = -1f;

        bool blocked = minimumDistance >= 0f && minimumDistance <= threshold;

        if (blocked && agent.debugRuntimeReplan)
        {
            Debug.Log(
                "[GO1ReplanController] 현재 이동 경로 차단 장애물 감지 | " +
                "obstacle=" + obstacle.name +
                ", segment=" + closestSegment +
                ", dist=" + minimumDistance.ToString("F2") +
                ", threshold=" + threshold.ToString("F2"),
                this
            );
        }

        return blocked;
    }

    private int GetClosestPathSegmentIndex(
        Vector3 position,
        IReadOnlyList<Vector3> path)
    {
        if (path == null || path.Count < 2)
            return 0;

        int bestIndex = 0;
        float bestDistance = float.MaxValue;

        for (int i = 0; i < path.Count - 1; i++)
        {
            float distance = DistancePointToSegmentXZ(
                position,
                path[i],
                path[i + 1]
            );

            if (distance < bestDistance)
            {
                bestDistance = distance;
                bestIndex = i;
            }
        }

        return bestIndex;
    }

    private Bounds GetObstacleBounds(GameObject obstacle)
    {
        Renderer renderer = obstacle.GetComponent<Renderer>();
        if (renderer == null)
            renderer = obstacle.GetComponentInChildren<Renderer>();

        if (renderer != null)
            return renderer.bounds;

        Collider collider = obstacle.GetComponent<Collider>();
        if (collider == null)
            collider = obstacle.GetComponentInChildren<Collider>();

        if (collider != null)
            return collider.bounds;

        return new Bounds(obstacle.transform.position, Vector3.one * 0.3f);
    }

    private float DistancePointToSegmentXZ(Vector3 point, Vector3 start, Vector3 end)
    {
        Vector2 p = new Vector2(point.x, point.z);
        Vector2 a = new Vector2(start.x, start.z);
        Vector2 b = new Vector2(end.x, end.z);
        Vector2 ab = b - a;

        if (ab.sqrMagnitude < 0.0001f)
            return Vector2.Distance(p, a);

        float t = Vector2.Dot(p - a, ab) / ab.sqrMagnitude;
        t = Mathf.Clamp01(t);

        Vector2 closest = a + ab * t;
        return Vector2.Distance(p, closest);
    }

    private void BeginPostReplanLock()
    {
        postReplanJsonBlockUntilTime =
            Time.time + Mathf.Max(0f, agent.postReplanLockSeconds);
        lastReplanTime = Time.time;

        if (agent.debugRuntimeReplan)
        {
            Debug.Log(
                "[GO1ReplanController] 재탐색 경로 전송 완료 → " +
                agent.postReplanLockSeconds.ToString("F1") +
                "초 동안 추가 재탐색/JSON 반영 잠금",
                this
            );
        }
    }

    private string GetValidationFailureMessage(string failureReason)
    {
        switch (failureReason)
        {
            case "target_missing":
                return "target이 없습니다.";
            case "navmesh_path_incomplete":
                return "현재 장애물 기준 목표까지 완전한 NavMesh 경로가 없습니다.";
            case "physical_path_blocked":
                return "현재 Collider 기준 경로가 막혀 있습니다.";
            default:
                return string.IsNullOrEmpty(failureReason)
                    ? "알 수 없는 경로 검증 오류"
                    : failureReason;
        }
    }

    private void StopOwnedCoroutines()
    {
        if (obstacleReplanCoroutine != null)
        {
            StopCoroutine(obstacleReplanCoroutine);
            obstacleReplanCoroutine = null;
        }

        if (generatedPathRetryCoroutine != null)
        {
            StopCoroutine(generatedPathRetryCoroutine);
            generatedPathRetryCoroutine = null;
        }
    }
}
