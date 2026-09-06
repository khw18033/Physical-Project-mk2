using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using UnityEngine;
using UnityEngine.Events;

public class GO1AutoPolicyController : MonoBehaviour
{
    public enum PolicyState
    {
        Idle,
        AutoDriving,
        Reversing,
        StopBeforeReplan,
        Replanning
    }

    public enum PolicyCondition
    {
        AutoDriving_ObstacleTooClose,
        Reversing_ReverseDistanceReached,
        StopBeforeReplan_HoldFinished,
        Replanning_DelayFinished
    }

    public enum PolicyAction
    {
        StartReverse,
        StopAndWaitBeforeReplan,
        RequestReplan,
        ResumeAutoDriving
    }

    [Serializable]
    public class PolicyRule
    {
        public bool enabled = true;
        public PolicyCondition condition;
        public PolicyAction action;
        public string memo;
    }

    [Header("References")]
    [Tooltip("가상 또는 실제 Go1 위치를 반영하는 Transform")]
    public Transform go1Transform;

    [Tooltip("기존 자율주행/재탐색 흐름을 담당하는 GO1Agent")]
    public GO1Agent linkedAgent;

    [Tooltip("직접 등록할 장애물 Transform 목록")]
    public List<Transform> obstacleTransforms = new List<Transform>();

    [Header("Obstacle Search")]
    [Tooltip("동적으로 생성되는 장애물을 태그로 자동 검색할지 여부")]
    public bool findObstaclesByTag = true;

    [Tooltip("장애물 프리팹에 지정할 태그")]
    public string obstacleTag = "Obstacle";

    [Tooltip("몇 초마다 장애물 거리를 검사할지")]
    public float obstacleCheckInterval = 0.1f;

    [Header("Policy Thresholds")]
    [Tooltip("이 거리보다 가까우면 후진 정책 실행")]
    public float tooCloseObstacleDistance = 0.7f;

    [Tooltip("후진할 거리")]
    public float reverseDistance = 0.4f;

    [Tooltip("후진 속도. C++ 쪽 vx 기준으로 음수 전송됨")]
    public float reverseSpeed = 0.12f;

    [Tooltip("후진 후 정지 상태로 유지할 시간")]
    public float stopHoldSeconds = 0.5f;

    [Tooltip("경로 재탐색 요청 후 다시 자율주행 상태로 전환하기 전 대기 시간")]
    public float replanDelaySeconds = 0.5f;

    [Tooltip("위치 갱신이 안 될 때 무한 후진 방지용 최대 후진 시간")]
    public float reverseTimeoutSeconds = 5.0f;

    [Header("Robot Command UDP")]
    [Tooltip("C++ teleop 명령을 받는 IP. 같은 PC면 127.0.0.1")]
    public string commandHost = "127.0.0.1";

    [Tooltip("C++ teleop 명령 수신 포트")]
    public int commandPort = 15100;

    [Tooltip("후진/정지 명령을 C++로 직접 보낼지 여부")]
    public bool sendCommandToCpp = true;

    [Tooltip("후진 명령 전송 주기")]
    public float commandSendInterval = 0.05f;

    [Header("Policy Table")]
    public List<PolicyRule> policyTable = new List<PolicyRule>();

    [Header("Events")]
    [Tooltip("장애물이 너무 가까워졌을 때 호출")]
    public UnityEvent onObstacleTooClose;

    [Tooltip("현재 자율주행을 멈춰야 할 때 호출")]
    public UnityEvent onStopAutoDriving;

    [Tooltip("경로 재탐색을 요청할 때 호출")]
    public UnityEvent onRequestReplan;

    [Tooltip("재탐색 후 다시 자율주행을 시작할 때 호출")]
    public UnityEvent onResumeAutoDriving;

    [Header("Debug")]
    public bool debugLog = true;
    public bool drawDebugLine = true;

    [SerializeField]
    private PolicyState currentState = PolicyState.Idle;

    [SerializeField]
    private float nearestObstacleDistance = Mathf.Infinity;

    [SerializeField]
    private Transform nearestObstacle;

    private UdpClient udpClient;
    private IPEndPoint commandEndPoint;

    private float lastObstacleCheckTime;
    private float lastCommandSendTime;
    private float stateEnterTime;

    private Vector3 reverseStartPosition;

    private void ResolveReferences()
    {
        if (linkedAgent == null)
        {
            linkedAgent = FindFirstObjectByType<GO1Agent>();
        }

        if (go1Transform == null && linkedAgent != null)
        {
            go1Transform = linkedAgent.transform;
        }

        if (linkedAgent == null && go1Transform != null)
        {
            linkedAgent = go1Transform.GetComponent<GO1Agent>();
        }
    }

    private void Reset()
    {
        MakeDefaultPolicyTable();
    }

    private void Awake()
    {
        ResolveReferences();

        if (policyTable == null || policyTable.Count == 0)
        {
            MakeDefaultPolicyTable();
        }

        if (sendCommandToCpp)
        {
            udpClient = new UdpClient();
            commandEndPoint = new IPEndPoint(IPAddress.Parse(commandHost), commandPort);
        }
    }

    private void OnDestroy()
    {
        if (udpClient != null)
        {
            udpClient.Close();
            udpClient = null;
        }
    }

    private void Update()
    {
        if (go1Transform == null)
        {
            return;
        }

        if (Time.time - lastObstacleCheckTime >= obstacleCheckInterval)
        {
            lastObstacleCheckTime = Time.time;
            UpdateNearestObstacleDistance();
        }

        if (currentState == PolicyState.Reversing)
        {
            SendReverseCommandRepeatedly();
        }

        EvaluatePolicyTable();

        if (drawDebugLine && nearestObstacle != null)
        {
            Debug.DrawLine(go1Transform.position, nearestObstacle.position, Color.red);
        }
    }

    private void MakeDefaultPolicyTable()
    {
        policyTable = new List<PolicyRule>
        {
            new PolicyRule
            {
                enabled = true,
                condition = PolicyCondition.AutoDriving_ObstacleTooClose,
                action = PolicyAction.StartReverse,
                memo = "자율주행 중 장애물이 너무 가까우면 후진 시작"
            },
            new PolicyRule
            {
                enabled = true,
                condition = PolicyCondition.Reversing_ReverseDistanceReached,
                action = PolicyAction.StopAndWaitBeforeReplan,
                memo = "설정한 거리만큼 후진하면 정지"
            },
            new PolicyRule
            {
                enabled = true,
                condition = PolicyCondition.StopBeforeReplan_HoldFinished,
                action = PolicyAction.RequestReplan,
                memo = "정지 후 경로 재탐색 요청"
            },
            new PolicyRule
            {
                enabled = true,
                condition = PolicyCondition.Replanning_DelayFinished,
                action = PolicyAction.ResumeAutoDriving,
                memo = "재탐색 후 자율주행 재개"
            }
        };
    }

    private void EvaluatePolicyTable()
    {
        foreach (PolicyRule rule in policyTable)
        {
            if (rule == null || !rule.enabled)
            {
                continue;
            }

            if (IsConditionTrue(rule.condition))
            {
                ExecuteAction(rule.action);
                break;
            }
        }
    }

    private bool IsConditionTrue(PolicyCondition condition)
    {
        switch (condition)
        {
            case PolicyCondition.AutoDriving_ObstacleTooClose:
                return currentState == PolicyState.AutoDriving &&
                       nearestObstacle != null &&
                       nearestObstacleDistance <= tooCloseObstacleDistance;

            case PolicyCondition.Reversing_ReverseDistanceReached:
                return currentState == PolicyState.Reversing &&
                       HasReversedEnough();

            case PolicyCondition.StopBeforeReplan_HoldFinished:
                return currentState == PolicyState.StopBeforeReplan &&
                       Time.time - stateEnterTime >= stopHoldSeconds;

            case PolicyCondition.Replanning_DelayFinished:
                return currentState == PolicyState.Replanning &&
                       Time.time - stateEnterTime >= replanDelaySeconds;
        }

        return false;
    }

    private void ExecuteAction(PolicyAction action)
    {
        switch (action)
        {
            case PolicyAction.StartReverse:
                StartReverse();
                break;

            case PolicyAction.StopAndWaitBeforeReplan:
                StopAndWaitBeforeReplan();
                break;

            case PolicyAction.RequestReplan:
                RequestReplan();
                break;

            case PolicyAction.ResumeAutoDriving:
                ResumeAutoDriving();
                break;
        }
    }

    private void StartReverse()
    {
        if (currentState != PolicyState.AutoDriving)
        {
            return;
        }

        if (debugLog)
        {
            Debug.Log(
                $"[POLICY] 장애물 너무 가까움. " +
                $"dist={nearestObstacleDistance:F3}m, 기준={tooCloseObstacleDistance:F3}m"
            );
        }

        onObstacleTooClose?.Invoke();

        StopLinkedAutoDriving();

        reverseStartPosition = go1Transform.position;
        ChangeState(PolicyState.Reversing);

        SendRobotCommand(-Mathf.Abs(reverseSpeed), 0f, 0f, false);
    }

    private void StopAndWaitBeforeReplan()
    {
        if (currentState != PolicyState.Reversing)
        {
            return;
        }

        SendRobotCommand(0f, 0f, 0f, false);

        if (debugLog)
        {
            Debug.Log(
                $"[POLICY] 후진 완료. " +
                $"reversed={GetReverseMovedDistance():F3}m, 목표={reverseDistance:F3}m"
            );
        }

        ChangeState(PolicyState.StopBeforeReplan);
    }

    private void RequestReplan()
    {
        if (currentState != PolicyState.StopBeforeReplan)
        {
            return;
        }

        SendRobotCommand(0f, 0f, 0f, false);

        if (debugLog)
        {
            Debug.Log("[POLICY] 경로 재탐색 요청");
        }

        RequestLinkedReplan();

        ChangeState(PolicyState.Replanning);
    }

    private void ResumeAutoDriving()
    {
        if (currentState != PolicyState.Replanning)
        {
            return;
        }

        if (debugLog)
        {
            Debug.Log("[POLICY] 자율주행 재개");
        }

        ResumeLinkedAutoDriving();

        ChangeState(PolicyState.AutoDriving);
    }

    private void StopLinkedAutoDriving()
    {
        if (linkedAgent != null)
        {
            linkedAgent.StopCurrentMissionFromPolicy();
            return;
        }

        onStopAutoDriving?.Invoke();
    }

    private void RequestLinkedReplan()
    {
        if (linkedAgent != null)
        {
            linkedAgent.RequestObstacleTriggeredReplanFromPolicy(nearestObstacle);
            return;
        }

        onRequestReplan?.Invoke();
    }

    private void ResumeLinkedAutoDriving()
    {
        if (linkedAgent != null)
        {
            linkedAgent.ResumeAutoDrivingFromPolicy();
            return;
        }

        onResumeAutoDriving?.Invoke();
    }

    private void SendReverseCommandRepeatedly()
    {
        if (Time.time - lastCommandSendTime < commandSendInterval)
        {
            return;
        }

        lastCommandSendTime = Time.time;
        SendRobotCommand(-Mathf.Abs(reverseSpeed), 0f, 0f, false);
    }

    private bool HasReversedEnough()
    {
        float movedDistance = GetReverseMovedDistance();

        if (movedDistance >= reverseDistance)
        {
            return true;
        }

        float elapsed = Time.time - stateEnterTime;

        if (elapsed >= reverseTimeoutSeconds)
        {
            if (debugLog)
            {
                Debug.LogWarning(
                    $"[POLICY] 후진 거리 기준에 도달하지 못했지만 timeout으로 정지. " +
                    $"moved={movedDistance:F3}m, timeout={reverseTimeoutSeconds:F3}s"
                );
            }

            return true;
        }

        return false;
    }

    private float GetReverseMovedDistance()
    {
        Vector3 current = go1Transform.position;

        Vector2 startXZ = new Vector2(reverseStartPosition.x, reverseStartPosition.z);
        Vector2 currentXZ = new Vector2(current.x, current.z);

        return Vector2.Distance(startXZ, currentXZ);
    }

    private void UpdateNearestObstacleDistance()
    {
        nearestObstacle = null;
        nearestObstacleDistance = Mathf.Infinity;

        CheckObstacleList(obstacleTransforms);

        if (findObstaclesByTag && !string.IsNullOrEmpty(obstacleTag))
        {
            GameObject[] taggedObjects = GameObject.FindGameObjectsWithTag(obstacleTag);

            for (int i = 0; i < taggedObjects.Length; i++)
            {
                if (taggedObjects[i] == null)
                {
                    continue;
                }

                CheckObstacle(taggedObjects[i].transform);
            }
        }
    }

    private void CheckObstacleList(List<Transform> list)
    {
        if (list == null)
        {
            return;
        }

        for (int i = 0; i < list.Count; i++)
        {
            CheckObstacle(list[i]);
        }
    }

    private void CheckObstacle(Transform obstacle)
    {
        if (obstacle == null || obstacle == go1Transform)
        {
            return;
        }

        Vector3 go1Pos = go1Transform.position;
        Vector3 obsPos = obstacle.position;

        float distanceXZ = Vector2.Distance(
            new Vector2(go1Pos.x, go1Pos.z),
            new Vector2(obsPos.x, obsPos.z)
        );

        if (distanceXZ < nearestObstacleDistance)
        {
            nearestObstacleDistance = distanceXZ;
            nearestObstacle = obstacle;
        }
    }

    private void SendRobotCommand(float vx, float vy, float wz, bool estop)
    {
        if (!sendCommandToCpp)
        {
            return;
        }

        if (udpClient == null)
        {
            return;
        }

        // 기존 C++ teleop 형식: vx vy wz estop
        string message = $"{vx:F3} {vy:F3} {wz:F3} {(estop ? 1 : 0)}";

        byte[] data = System.Text.Encoding.ASCII.GetBytes(message);
        udpClient.Send(data, data.Length, commandEndPoint);

        if (debugLog)
        {
            Debug.Log($"[POLICY CMD] {message}");
        }
    }

    private void ChangeState(PolicyState nextState)
    {
        currentState = nextState;
        stateEnterTime = Time.time;

        if (debugLog)
        {
            Debug.Log($"[POLICY STATE] {nextState}");
        }
    }

    public void NotifyAutoDrivingStarted()
    {
        ChangeState(PolicyState.AutoDriving);
    }

    public void NotifyAutoDrivingStopped()
    {
        SendRobotCommand(0f, 0f, 0f, false);
        ChangeState(PolicyState.Idle);
    }

    public void ForceStopPolicy()
    {
        SendRobotCommand(0f, 0f, 0f, false);
        ChangeState(PolicyState.Idle);
    }

    public float GetNearestObstacleDistance()
    {
        return nearestObstacleDistance;
    }

    public PolicyState GetCurrentState()
    {
        return currentState;
    }
}