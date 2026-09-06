using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// ML-Agent로 가상 GO1을 직접 이동시키지 않고,
/// NavMesh.CalculatePath로 목표 지점까지의 경로를 계산한 뒤
/// GO1LocalPathUdpSender를 통해 C++/SDK path follower로 전송하는 스크립트입니다.
///
/// 권장 사용:
/// - 기존 GO1Agent의 M키 자율주행 기능은 끄거나, 이 스크립트와 키가 겹치지 않게 설정
/// - GO1LocalPathUdpSender는 기존에 쓰던 path sender를 연결
/// - Go1ObstacleJsonReceiver는 5009번 장애물/소화기/state_change 수신 스크립트를 연결
/// </summary>
public class GO1NavMeshPathSender : MonoBehaviour
{
    [Header("Target / Sender")]
    [Tooltip("목표 지점 Transform")]
    public Transform target;

    [Tooltip("기존 GO1LocalPathUdpSender 연결")]
    public GO1LocalPathUdpSender pathSender;

    [Tooltip("5009번 포트 장애물/소화기/state_change 수신 스크립트")]
    public Go1ObstacleJsonReceiver obstacleReceiver;

    [Tooltip("실제 GO1 state를 Unity 가상 GO1에 반영하는 스크립트. 비워두면 자동 탐색")]
    public UnityTeleopAndMirror unityTeleopAndMirror;

    [Header("Keys")]
    [Tooltip("NavMesh 경로 계산 및 전송 시작 키")]
    public KeyCode sendNavMeshPathKey = KeyCode.M;

    [Tooltip("현재 전송 경로 취소 키")]
    public KeyCode cancelPathKey = KeyCode.N;

    [Header("NavMesh Path")]
    [Tooltip("NavMesh 경로 계산 전에 현재 SDK state pose를 가상 GO1 위치에 반영")]
    public bool syncPoseFromSdkBeforePath = true;

    [Tooltip("경로 계산 직전에 5009 JSON 큐를 먼저 처리해서 소화기 위치 보정을 선적용")]
    public bool processQueuedJsonBeforePath = true;

    [Tooltip("경로 계산 전 처리할 최대 JSON 패킷 수")]
    public int maxPrePathJsonPackets = 50;

    [Tooltip("소화기 보정/장애물 생성 후 NavMeshObstacle carving 반영 대기 시간")]
    public float navMeshCarvingWaitTime = 0.35f;

    [Tooltip("NavMesh 코너 사이에 중간 waypoint를 추가할 간격")]
    public float waypointSpacing = 0.20f;

    [Tooltip("너무 가까운 waypoint 제거 거리")]
    public float minWaypointSpacing = 0.05f;

    [Tooltip("C++로 보낼 최대 waypoint 개수")]
    public int maxWaypointCount = 120;

    [Tooltip("NavMeshPath 상태가 Complete일 때만 전송")]
    public bool requireCompletePath = true;

    [Header("Path Validation")]
    [Tooltip("전송 직전 Collider 기준으로 경로가 장애물을 통과하는지 검사")]
    public bool validatePathBeforeSend = true;

    [Tooltip("장애물 검사에 사용할 레이어. 반드시 Obstacle만 선택 권장")]
    public LayerMask obstacleLayerMask;

    [Tooltip("CapsuleCast 반경")]
    public float pathCheckRadius = 0.25f;

    [Tooltip("CapsuleCast 높이")]
    public float pathCheckHeight = 0.5f;

    [Tooltip("Trigger Collider도 장애물로 검사")]
    public bool includeTriggerColliders = true;

    [Header("State Change Gate")]
    [Tooltip("경로 전송 직후 바로 이동 중으로 보지 않고, 5009 state_change=true를 기다림")]
    public bool waitForStateChangeTrue = true;

    [Tooltip("state_change=true를 기다릴 시간")]
    public float stateChangeWaitTimeoutSec = 5.0f;

    [Tooltip("timeout 동안 true가 안 오면 같은 경로를 다시 전송")]
    public bool resendPathOnTimeout = true;

    [Tooltip("state_change timeout 후 동일 경로 재전송 최대 횟수")]
    public int maxResendCount = 1;

    [Tooltip("재전송 전 대기 시간")]
    public float resendDelaySec = 0.25f;

    [Tooltip("state_change=true가 계속 안 와도 timeout 시 강제로 이동 중으로 처리")]
    public bool activateOnTimeout = false;

    [Tooltip("state_change=false가 오면 실제 경로 추종 상태를 false로 동기화")]
    public bool syncInactiveFromStateChangeFalse = true;

    [Header("Cancel / Stop")]
    [Tooltip("N키 또는 취소 시 PATH_CANCEL 전송")]
    public bool sendPathCancelOnStop = true;

    [Tooltip("N키 또는 취소 시 0속도 estop 명령도 같이 전송")]
    public bool sendStopTeleopOnCancel = true;

    [Tooltip("취소 시 보낼 estop 값. 1이면 정지 성격, 0이면 일반 0속도")]
    public int stopEstopValue = 1;

    [Header("Debug / Draw")]
    public bool printLog = true;
    public bool drawPathGizmos = true;
    public Color pathGizmoColor = Color.cyan;
    public float gizmoPointRadius = 0.06f;

    private readonly List<Vector3> currentSentPath = new List<Vector3>();
    private NavMeshPath navMeshPath;
    private Coroutine sendRoutine;
    private Coroutine stateWaitRoutine;

    private bool isSendingPath = false;
    private bool realPathActive = false;
    private bool waitingStateChange = false;
    private int resendCount = 0;

    public bool IsRealPathActive()
    {
        return realPathActive;
    }

    public bool IsWaitingStateChange()
    {
        return waitingStateChange;
    }

    public IReadOnlyList<Vector3> GetCurrentSentPath()
    {
        return currentSentPath;
    }

    private void Awake()
    {
        navMeshPath = new NavMeshPath();
    }

    private void Start()
    {
        AutoFindReferences();
    }

    private void Update()
    {
        if (Input.GetKeyDown(sendNavMeshPathKey))
        {
            StartNavMeshPathSend();
        }

        if (Input.GetKeyDown(cancelPathKey))
        {
            CancelCurrentPath("manual-cancel-key");
        }

        if (syncInactiveFromStateChangeFalse && realPathActive && obstacleReceiver != null)
        {
            bool hasRecent = InvokeBoolMethod(obstacleReceiver, "HasRecentGo1MotionState", false);
            bool moving = InvokeBoolMethod(obstacleReceiver, "ShouldMoveVirtualGo1AfterPathSent", false);

            if (hasRecent && !moving)
            {
                realPathActive = false;
                if (printLog)
                    Debug.Log("[GO1NavMeshPathSender] state_change=false 수신 → realPathActive=false");
            }
        }
    }

    public void StartNavMeshPathSend()
    {
        if (isSendingPath || waitingStateChange || realPathActive)
        {
            if (printLog)
                Debug.Log("[GO1NavMeshPathSender] 이미 경로 전송/대기/추종 중이라 시작 요청을 무시합니다.");
            return;
        }

        if (sendRoutine != null)
            StopCoroutine(sendRoutine);

        sendRoutine = StartCoroutine(SendNavMeshPathRoutine());
    }

    public void CancelCurrentPath(string reason = "cancel")
    {
        if (sendRoutine != null)
        {
            StopCoroutine(sendRoutine);
            sendRoutine = null;
        }

        if (stateWaitRoutine != null)
        {
            StopCoroutine(stateWaitRoutine);
            stateWaitRoutine = null;
        }

        isSendingPath = false;
        waitingStateChange = false;
        realPathActive = false;
        resendCount = 0;
        currentSentPath.Clear();

        if (sendPathCancelOnStop && pathSender != null)
            pathSender.SendPathCancel();

        if (sendStopTeleopOnCancel && unityTeleopAndMirror != null)
        {
            unityTeleopAndMirror.enableTeleop = true;
            unityTeleopAndMirror.driveByState = true;
            unityTeleopAndMirror.SendTeleopCmd(0f, 0f, 0f, stopEstopValue);
        }

        if (printLog)
            Debug.Log("[GO1NavMeshPathSender] 경로 취소 완료 | reason=" + reason);
    }

    private IEnumerator SendNavMeshPathRoutine()
    {
        isSendingPath = true;
        realPathActive = false;
        waitingStateChange = false;
        resendCount = 0;

        AutoFindReferences();

        if (target == null)
        {
            Debug.LogWarning("[GO1NavMeshPathSender] target이 없습니다.");
            isSendingPath = false;
            yield break;
        }

        if (pathSender == null)
        {
            Debug.LogWarning("[GO1NavMeshPathSender] pathSender가 없습니다.");
            isSendingPath = false;
            yield break;
        }

        if (unityTeleopAndMirror != null)
        {
            unityTeleopAndMirror.driveByState = true;
            unityTeleopAndMirror.enableTeleop = true;
        }

        if (syncPoseFromSdkBeforePath)
        {
            TrySyncPoseFromSdkState("before-navmesh-path");
        }

        if (processQueuedJsonBeforePath && obstacleReceiver != null)
        {
            int processed = InvokeIntMethod(
                obstacleReceiver,
                "ProcessQueuedJsonForPathPlanningGate",
                maxPrePathJsonPackets,
                0
            );

            if (printLog && processed > 0)
                Debug.Log("[GO1NavMeshPathSender] 경로 계산 전 5009 JSON 선처리 완료 | processed=" + processed);
        }

        if (navMeshCarvingWaitTime > 0f)
            yield return new WaitForSeconds(navMeshCarvingWaitTime);

        List<Vector3> pathToSend = BuildNavMeshPathToTarget();

        if (pathToSend == null || pathToSend.Count < 2)
        {
            Debug.LogWarning("[GO1NavMeshPathSender] NavMesh 경로 생성 실패 또는 경로가 너무 짧습니다.");
            isSendingPath = false;
            yield break;
        }

        if (validatePathBeforeSend && IsWorldPathPhysicallyBlocked(pathToSend, "navmesh-send-path"))
        {
            Debug.LogWarning("[GO1NavMeshPathSender] NavMesh 경로가 장애물을 통과한다고 판단되어 C++로 전송하지 않습니다.");
            isSendingPath = false;
            yield break;
        }

        bool sent = SendPathToCpp(pathToSend, "initial-navmesh");
        isSendingPath = false;

        if (!sent)
            yield break;

        if (waitForStateChangeTrue)
        {
            if (stateWaitRoutine != null)
                StopCoroutine(stateWaitRoutine);

            stateWaitRoutine = StartCoroutine(WaitStateChangeTrueRoutine());
        }
        else
        {
            realPathActive = true;
            if (printLog)
                Debug.Log("[GO1NavMeshPathSender] state_change 대기 없이 realPathActive=true");
        }
    }

    private List<Vector3> BuildNavMeshPathToTarget()
    {
        Vector3 start = transform.position;
        Vector3 end = target.position;

        NavMeshHit startHit;
        if (NavMesh.SamplePosition(start, out startHit, 1.0f, NavMesh.AllAreas))
            start = startHit.position;

        NavMeshHit endHit;
        if (NavMesh.SamplePosition(end, out endHit, 1.0f, NavMesh.AllAreas))
            end = endHit.position;

        bool ok = NavMesh.CalculatePath(start, end, NavMesh.AllAreas, navMeshPath);
        if (!ok)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] NavMesh.CalculatePath 실패");
            return null;
        }

        if (requireCompletePath && navMeshPath.status != NavMeshPathStatus.PathComplete)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] NavMesh 경로가 Complete가 아닙니다. status=" + navMeshPath.status);
            return null;
        }

        if (navMeshPath.corners == null || navMeshPath.corners.Length < 2)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] NavMesh corners가 부족합니다.");
            return null;
        }

        List<Vector3> dense = BuildDensePathFromCorners(navMeshPath.corners, waypointSpacing);
        dense = RemoveTooClosePoints(dense, minWaypointSpacing);
        dense = LimitPointCount(dense, maxWaypointCount);

        if (dense.Count > 0)
        {
            dense[0] = transform.position;
            dense[dense.Count - 1] = target.position;
        }

        if (printLog)
        {
            Debug.Log(
                "[GO1NavMeshPathSender] NavMesh 경로 생성 | " +
                "corners=" + navMeshPath.corners.Length +
                ", sendPoints=" + dense.Count +
                ", status=" + navMeshPath.status
            );
        }

        return dense;
    }

    private List<Vector3> BuildDensePathFromCorners(Vector3[] corners, float spacing)
    {
        List<Vector3> result = new List<Vector3>();
        if (corners == null || corners.Length == 0)
            return result;

        spacing = Mathf.Max(0.05f, spacing);
        result.Add(corners[0]);

        for (int i = 0; i < corners.Length - 1; i++)
        {
            Vector3 a = corners[i];
            Vector3 b = corners[i + 1];
            float dist = Vector3.Distance(a, b);
            int stepCount = Mathf.Max(1, Mathf.CeilToInt(dist / spacing));

            for (int s = 1; s <= stepCount; s++)
            {
                float t = (float)s / stepCount;
                Vector3 p = Vector3.Lerp(a, b, t);
                result.Add(p);
            }
        }

        return result;
    }

    private List<Vector3> RemoveTooClosePoints(List<Vector3> points, float minSpacing)
    {
        List<Vector3> result = new List<Vector3>();
        if (points == null || points.Count == 0)
            return result;

        minSpacing = Mathf.Max(0.01f, minSpacing);
        result.Add(points[0]);
        Vector3 last = points[0];

        for (int i = 1; i < points.Count - 1; i++)
        {
            if (Vector3.Distance(last, points[i]) >= minSpacing)
            {
                result.Add(points[i]);
                last = points[i];
            }
        }

        if (points.Count > 1)
            result.Add(points[points.Count - 1]);

        return result;
    }

    private List<Vector3> LimitPointCount(List<Vector3> points, int maxCount)
    {
        if (points == null)
            return new List<Vector3>();

        if (maxCount <= 1 || points.Count <= maxCount)
            return points;

        List<Vector3> result = new List<Vector3>();
        int lastIndex = points.Count - 1;

        for (int i = 0; i < maxCount; i++)
        {
            float t = maxCount == 1 ? 0f : (float)i / (maxCount - 1);
            int index = Mathf.RoundToInt(t * lastIndex);
            index = Mathf.Clamp(index, 0, lastIndex);
            result.Add(points[index]);
        }

        return result;
    }

    private bool SendPathToCpp(List<Vector3> path, string reason)
    {
        if (pathSender == null || path == null || path.Count < 2)
            return false;

        currentSentPath.Clear();
        currentSentPath.AddRange(path);

        Quaternion startRot = transform.rotation;
        pathSender.CaptureStartPose(path[0], startRot);
        pathSender.SendPathFromCorners(path.ToArray());

        if (printLog)
        {
            Debug.Log(
                "[GO1NavMeshPathSender] C++로 NavMesh path 전송 | " +
                "reason=" + reason +
                ", points=" + path.Count +
                ", start=" + path[0] +
                ", target=" + path[path.Count - 1]
            );
        }

        return true;
    }

    private IEnumerator WaitStateChangeTrueRoutine()
    {
        waitingStateChange = true;
        realPathActive = false;

        if (printLog)
            Debug.Log("[GO1NavMeshPathSender] state_change=true 대기 시작");

        while (true)
        {
            float startTime = Time.time;
            float timeout = Mathf.Max(0.1f, stateChangeWaitTimeoutSec);

            while (Time.time - startTime < timeout)
            {
                bool moving = obstacleReceiver != null && InvokeBoolMethod(obstacleReceiver, "ShouldMoveVirtualGo1AfterPathSent", false);
                if (moving)
                {
                    waitingStateChange = false;
                    realPathActive = true;
                    resendCount = 0;

                    if (printLog)
                        Debug.Log("[GO1NavMeshPathSender] state_change=true 확인 → realPathActive=true");

                    stateWaitRoutine = null;
                    yield break;
                }

                yield return null;
            }

            if (resendPathOnTimeout && resendCount < Mathf.Max(0, maxResendCount) && currentSentPath.Count >= 2)
            {
                resendCount++;

                if (printLog)
                {
                    Debug.LogWarning(
                        "[GO1NavMeshPathSender] state_change=true 대기 timeout → 동일 NavMesh path 재전송 " +
                        resendCount + "/" + maxResendCount
                    );
                }

                if (resendDelaySec > 0f)
                    yield return new WaitForSeconds(resendDelaySec);

                SendPathToCpp(new List<Vector3>(currentSentPath), "state-timeout-resend");
                continue;
            }

            waitingStateChange = false;

            if (activateOnTimeout)
            {
                realPathActive = true;
                if (printLog)
                    Debug.LogWarning("[GO1NavMeshPathSender] state_change timeout이지만 설정에 따라 realPathActive=true 처리");
            }
            else
            {
                realPathActive = false;
                if (printLog)
                    Debug.LogWarning("[GO1NavMeshPathSender] state_change=true 대기 최종 timeout → realPathActive=false 유지");
            }

            stateWaitRoutine = null;
            yield break;
        }
    }

    private bool IsWorldPathPhysicallyBlocked(List<Vector3> worldPath, string context)
    {
        if (worldPath == null || worldPath.Count < 2)
            return true;

        QueryTriggerInteraction triggerMode = includeTriggerColliders
            ? QueryTriggerInteraction.Collide
            : QueryTriggerInteraction.Ignore;

        for (int i = 0; i < worldPath.Count - 1; i++)
        {
            Vector3 a = worldPath[i];
            Vector3 b = worldPath[i + 1];
            Vector3 dir = b - a;
            dir.y = 0f;

            float dist = dir.magnitude;
            if (dist < 0.01f)
                continue;

            dir.Normalize();
            Vector3 p1 = a + Vector3.up * 0.2f;
            Vector3 p2 = a + Vector3.up * Mathf.Max(0.25f, pathCheckHeight);

            bool hit = Physics.CapsuleCast(
                p1,
                p2,
                Mathf.Max(0.01f, pathCheckRadius),
                dir,
                out RaycastHit hitInfo,
                dist,
                obstacleLayerMask,
                triggerMode
            );

            Debug.DrawLine(
                a + Vector3.up * 0.08f,
                b + Vector3.up * 0.08f,
                hit ? Color.red : Color.cyan,
                1.5f
            );

            if (hit)
            {
                if (printLog)
                {
                    Debug.LogWarning(
                        "[GO1NavMeshPathSender] 경로 장애물 통과 감지 | " +
                        "context=" + context +
                        ", obstacle=" + hitInfo.collider.name +
                        ", segment=" + i +
                        ", hitDist=" + hitInfo.distance.ToString("F2")
                    );
                }

                return true;
            }
        }

        return false;
    }

    private void TrySyncPoseFromSdkState(string reason)
    {
        if (unityTeleopAndMirror == null)
            return;

        bool hasState = InvokeBoolMethod(unityTeleopAndMirror, "HasSdkState", false);
        if (!hasState)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] SDK state가 아직 없어 pose 동기화를 건너뜁니다. reason=" + reason);
            return;
        }

        bool gotPos = InvokeVector3Method(unityTeleopAndMirror, "GetCurrentSdkUnityMappedPosition", out Vector3 pos);
        bool gotRot = InvokeQuaternionMethod(unityTeleopAndMirror, "GetCurrentSdkUnityMappedRotation", out Quaternion rot);

        if (!gotPos || !gotRot)
            return;

        CharacterController cc = GetComponent<CharacterController>();
        bool ccWasEnabled = cc != null && cc.enabled;
        if (cc != null)
            cc.enabled = false;

        transform.SetPositionAndRotation(pos, rot);

        NavMeshAgent navAgent = GetComponent<NavMeshAgent>();
        if (navAgent != null && navAgent.enabled && navAgent.isOnNavMesh)
            navAgent.Warp(pos);

        if (cc != null)
            cc.enabled = ccWasEnabled;

        if (printLog)
        {
            Debug.Log(
                "[GO1NavMeshPathSender] SDK state 기준 pose 동기화 | " +
                "reason=" + reason +
                ", pos=" + pos +
                ", yaw=" + rot.eulerAngles.y.ToString("F1") + "deg"
            );
        }
    }

    private void AutoFindReferences()
    {
        if (pathSender == null)
            pathSender = FindFirstObjectByType<GO1LocalPathUdpSender>();

        if (obstacleReceiver == null)
            obstacleReceiver = FindFirstObjectByType<Go1ObstacleJsonReceiver>();

        if (unityTeleopAndMirror == null)
            unityTeleopAndMirror = FindFirstObjectByType<UnityTeleopAndMirror>();
    }

    private bool InvokeBoolMethod(object targetObject, string methodName, bool defaultValue)
    {
        if (targetObject == null)
            return defaultValue;

        MethodInfo method = targetObject.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (method == null)
            return defaultValue;

        try
        {
            object value = method.Invoke(targetObject, null);
            if (value is bool b)
                return b;
        }
        catch (Exception e)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] " + methodName + " 호출 실패: " + e.Message);
        }

        return defaultValue;
    }

    private int InvokeIntMethod(object targetObject, string methodName, int arg, int defaultValue)
    {
        if (targetObject == null)
            return defaultValue;

        MethodInfo method = targetObject.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (method == null)
            return defaultValue;

        try
        {
            object value = method.Invoke(targetObject, new object[] { arg });
            if (value is int i)
                return i;
        }
        catch (Exception e)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] " + methodName + " 호출 실패: " + e.Message);
        }

        return defaultValue;
    }

    private bool InvokeVector3Method(object targetObject, string methodName, out Vector3 result)
    {
        result = Vector3.zero;
        if (targetObject == null)
            return false;

        MethodInfo method = targetObject.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (method == null)
            return false;

        try
        {
            object value = method.Invoke(targetObject, null);
            if (value is Vector3 v)
            {
                result = v;
                return true;
            }
        }
        catch (Exception e)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] " + methodName + " 호출 실패: " + e.Message);
        }

        return false;
    }

    private bool InvokeQuaternionMethod(object targetObject, string methodName, out Quaternion result)
    {
        result = Quaternion.identity;
        if (targetObject == null)
            return false;

        MethodInfo method = targetObject.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (method == null)
            return false;

        try
        {
            object value = method.Invoke(targetObject, null);
            if (value is Quaternion q)
            {
                result = q;
                return true;
            }
        }
        catch (Exception e)
        {
            if (printLog)
                Debug.LogWarning("[GO1NavMeshPathSender] " + methodName + " 호출 실패: " + e.Message);
        }

        return false;
    }

    private void OnDrawGizmos()
    {
        if (!drawPathGizmos || currentSentPath == null || currentSentPath.Count < 2)
            return;

        Gizmos.color = pathGizmoColor;
        for (int i = 0; i < currentSentPath.Count; i++)
        {
            Vector3 p = currentSentPath[i] + Vector3.up * 0.08f;
            Gizmos.DrawSphere(p, gizmoPointRadius);

            if (i < currentSentPath.Count - 1)
            {
                Vector3 next = currentSentPath[i + 1] + Vector3.up * 0.08f;
                Gizmos.DrawLine(p, next);
            }
        }
    }
}
