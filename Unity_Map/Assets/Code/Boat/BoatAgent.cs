using UnityEngine;

/// <summary>
/// 기존 GO1Agent의 이동, 관측, 보상, 경로 생성 로직을 그대로 사용하고,
/// 함선에서는 도착 거리, 기본 이동값, 생성 경로 로컬 재주행 설정만 변경합니다.
/// </summary>
public class BoatAgent : GO1Agent
{
    private const float DefaultBoatMoveSpeed = 4f;
    private const float DefaultBoatRotateSpeedDeg = 30f;
    private const float DefaultBoatBlockedMoveThreshold = 0.001f;
    private const int DefaultBoatBlockedFrameLimit = 200;

    [Header("Boat Goal Arrival")]
    [Tooltip("함선 중심과 GoalPoint 사이의 도착 판정 거리입니다.")]
    [Min(0.1f)]
    [SerializeField]
    private float boatGoalArrivalDistance = 3.5f;

    [Header("Local Generated Path Replay")]
    [Tooltip("생성한 경로를 UDP/C++로 보내지 않고 Unity에서 직접 다시 따라갑니다.")]
    [SerializeField]
    private bool replayGeneratedPathLocally = true;

    [Tooltip("체크하면 기록된 원본 경로를 사용하고, 해제하면 단순화된 전송 예정 경로를 사용합니다.")]
    [SerializeField]
    private bool useRawRecordedPath = false;

    [Tooltip("생성 경로 재주행 속도입니다.")]
    [Min(0.05f)]
    [SerializeField]
    private float localReplayMoveSpeed = DefaultBoatMoveSpeed;

    [Tooltip("생성 경로 재주행 회전 속도입니다.")]
    [Min(1f)]
    [SerializeField]
    private float localReplayRotateSpeedDeg = DefaultBoatRotateSpeedDeg;

    [Tooltip("각 경로점에 이 거리 이내로 접근하면 다음 경로점으로 넘어갑니다.")]
    [Min(0.05f)]
    [SerializeField]
    private float localReplayWaypointTolerance = 0.8f;

    [Tooltip("이 시간 안에 최종 목적지에 도달하지 못하면 재주행 실패로 처리합니다.")]
    [Min(1f)]
    [SerializeField]
    private float localReplayTimeoutSeconds = 180f;

    [Header("ML-Agent Runtime Replanning")]
    [Tooltip("로컬 재주행 중 부표가 놓이면 기존 재주행을 멈추고 ML-Agent 정책으로 새 경로를 다시 생성합니다.")]
    [SerializeField]
    private bool enableLocalReplayMlAgentReplan = true;

    [Tooltip("한 미션에서 허용할 ML-Agent 재탐색 횟수입니다. 0이면 제한 없이 여러 번 가능합니다.")]
    [Min(0)]
    [SerializeField]
    private int localReplayMlAgentReplanLimit = 0;

    [Tooltip("부표의 NavMeshObstacle carving 반영을 기다리는 시간입니다.")]
    [Min(0f)]
    [SerializeField]
    private float localReplayMlAgentReplanDelay = 0.6f;

    [Tooltip("완전한 우회 NavMesh 경로가 생길 때까지 기다리는 최대 시간입니다.")]
    [Min(0.5f)]
    [SerializeField]
    private float localReplayMlAgentReplanReadyTimeout = 5f;

    protected override float GoalArrivalDistance =>
        boatGoalArrivalDistance;

    protected override bool UseLocalGeneratedPathReplay =>
        replayGeneratedPathLocally;

    protected override bool LocalReplayUseRawRecordedPath =>
        useRawRecordedPath;

    protected override float LocalReplayMoveSpeed =>
        localReplayMoveSpeed;

    protected override float LocalReplayRotateSpeedDeg =>
        localReplayRotateSpeedDeg;

    protected override float LocalReplayWaypointTolerance =>
        localReplayWaypointTolerance;

    protected override float LocalReplayTimeoutSeconds =>
        localReplayTimeoutSeconds;

    protected override bool EnableLocalReplayMlAgentReplan =>
        enableLocalReplayMlAgentReplan;

    protected override int LocalReplayMlAgentReplanLimit =>
        localReplayMlAgentReplanLimit;

    protected override float LocalReplayMlAgentReplanDelay =>
        localReplayMlAgentReplanDelay;

    protected override float LocalReplayMlAgentReplanReadyTimeout =>
        localReplayMlAgentReplanReadyTimeout;

    /// <summary>
    /// BoatAgent를 처음 추가하거나 Inspector에서 Reset을 실행할 때 적용됩니다.
    /// 기존에 저장된 Inspector 값은 스크립트 교체만으로 바뀌지 않으므로,
    /// 기존 컴포넌트에서는 우측 메뉴의 Reset 또는 아래 Context Menu를 사용하세요.
    /// </summary>
    private void Reset()
    {
        ApplyBoatDefaultSettings();
    }

    [ContextMenu("Apply Boat Default Settings")]
    private void ApplyBoatDefaultSettings()
    {
        moveSpeed = DefaultBoatMoveSpeed;
        rotateSpeedDeg = DefaultBoatRotateSpeedDeg;

        enableStuckDetection = true;
        blockedMoveThreshold = DefaultBoatBlockedMoveThreshold;
        blockedFrameLimit = DefaultBoatBlockedFrameLimit;

        boatGoalArrivalDistance = 3.5f;

        replayGeneratedPathLocally = true;
        useRawRecordedPath = false;
        localReplayMoveSpeed = DefaultBoatMoveSpeed;
        localReplayRotateSpeedDeg = DefaultBoatRotateSpeedDeg;
        localReplayWaypointTolerance = 0.8f;
        localReplayTimeoutSeconds = 180f;

        enableLocalReplayMlAgentReplan = true;
        localReplayMlAgentReplanLimit = 0;
        localReplayMlAgentReplanDelay = 0.6f;
        localReplayMlAgentReplanReadyTimeout = 5f;
    }
}
