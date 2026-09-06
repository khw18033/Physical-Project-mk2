using Unity.MLAgents;
using Unity.MLAgents.Actuators;
using Unity.MLAgents.Sensors;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// NavMesh 기반 경로를 따라 목표에 항해하며 COLREGS(Rule 13/14/15/16/17)를 준수하는 에이전트.
/// 타선은 물리적으로 레이어 분리되지만, COLREGS 판단을 위한 관측 5차원은 추가된다.
/// </summary>
[RequireComponent(typeof(Rigidbody))]
public class BoatColregAgent : Agent
{
    // ── 이동 ─────────────────────────────────────────────────────────────
    [Header("Movement")]
    public float maxForwardSpeed = 10f;
    public float maxTurnSpeedDeg = 30f;
    [Range(0.01f, 1f)] public float thrustSmoothFactor = 0.5f;
    [Range(0.01f, 1f)] public float turnSmoothFactor   = 0.4f;

    // ── 목표 ─────────────────────────────────────────────────────────────
    [Header("Goal")]
    public Transform goalTransform;
    public float goalArrivalDistance = 12f;
    public float maxEpisodeTimeSec   = 200f;

    // ── 장애물 감지 ───────────────────────────────────────────────────────
    [Header("Obstacle Detection")]
    [Tooltip("레이캐스트 최대 거리 (m)")]
    public float obstacleRayLength = 50f;
    [Tooltip("360° 균등 분포 레이 수. Behavior Parameters > Space Size = 4+3+2+이값")]
    public int   obstacleRayCount  = 8;
    [Tooltip("런타임에 gameObject.layer로 자동 갱신됨. Inspector 설정 불필요.")]
    public LayerMask obstacleLayerMask;

    // ── 경계 ─────────────────────────────────────────────────────────────
    [Header("Boundary")]
    [Tooltip("BoatTrainingManager가 런타임에 설정. Inspector 수정 불필요.")]
    public Vector3 boundaryCenter = Vector3.zero;
    public float   boundaryRadius = 100f;

    // ── NavMesh 경로 ──────────────────────────────────────────────────────
    private NavMeshPath navPath;
    private float       navPathLength;
    private Vector3     nextNavWaypoint;

    // ── 보상 ─────────────────────────────────────────────────────────────
    [Header("Reward Weights")]
    public float rewardGoalArrival      =  5.0f;
    public float penaltyCollision       = -1.0f;
    public float penaltyTimeout         = -0.5f;
    public float penaltyStepBase        = -0.001f;
    public float rewardGoalApproachScale =  0.1f;
    public float penaltyTurnJerk         =  0.003f;

    // ── COLREGS ──────────────────────────────────────────────────────────
    [Header("COLREGS")]
    [Tooltip("이 거리 이내의 타선을 관측 · 상황 분류에 포함 (m)")]
    public float colregsDetectRange = 50f;
    [Tooltip("이 거리 이내에서 COLREGS 보상/패널티 적용 (m)")]
    public float colregsAlertRange  = 25f;

    // ── 디버그 ───────────────────────────────────────────────────────────
    [Header("Debug")]
    public bool drawDebugGizmos = true;

    // ── 학습 매니저 ──────────────────────────────────────────────────────
    [Header("Training Manager")]
    public BoatTrainingManager trainingManager;

    // ── 인퍼런스 콜백 ────────────────────────────────────────────────────
    [HideInInspector] public System.Action onGoalReached;

    // ── 내부 ─────────────────────────────────────────────────────────────
    private Rigidbody rb;
    private float currentThrust;
    private float currentTurn;
    private float prevTurn;
    private float episodeTimer;
    private float prevGoalDistance;
    private bool  episodeEnded;

    // COLREGS 판단 상태 (CollectObservations에서 갱신 → ComputeAndAddRewards에서 사용)
    private enum ColregsSituation
    {
        None,
        HeadOn,            // Rule 14: 마주치는 상태 → 양측 우현 선회
        CrossingGiveWay,   // Rule 15/16: 우현에 타선 → 피항선 (우현 선회)
        CrossingStandOn,   // Rule 15/17: 좌현에 타선 → 유지선 (침로 유지)
        Overtaking,        // Rule 13: 타선 선미 구역에서 접근 → 피항선
        BeingOvertaken,    // Rule 13: 타선이 우리를 추월 → 유지선
    }

    private BoatColregAgent  nearestBoat;
    private float            nearestDist       = float.MaxValue;
    private float            nearestBearDeg    = 0f;  // 우현 방위각 (+우현, -좌현)
    private float            nearestRelHeadDeg = 0f;  // 상대방 선수 방향 (자선 기준)
    private ColregsSituation colregsSituation  = ColregsSituation.None;

    // U_Boat 자식 메쉬가 Y축 +90° 회전되어 있으므로
    // 시각적 선수(bow) = transform.right, 우현(starboard) = -transform.forward
    internal Vector3 BowDir       => transform.right;
    internal Vector3 StarboardDir => -transform.forward;

    // ═══════════════════════════════════════════════════════════════════
    // ML-Agents 생명주기
    // ═══════════════════════════════════════════════════════════════════

    public override void Initialize()
    {
        rb = GetComponent<Rigidbody>();
        rb.linearDamping  = 0.5f;
        rb.angularDamping = 1.0f;
        rb.constraints    = RigidbodyConstraints.FreezePositionY
                          | RigidbodyConstraints.FreezeRotationX
                          | RigidbodyConstraints.FreezeRotationZ;
        rb.useGravity = false;

        navPath          = new NavMeshPath();
        navPathLength    = float.MaxValue;
        nextNavWaypoint  = transform.position;
    }

    public override void OnEpisodeBegin()
    {
        currentThrust = 0f;
        currentTurn   = 0f;
        prevTurn      = 0f;
        episodeTimer  = 0f;
        episodeEnded  = false;

        rb.linearVelocity  = Vector3.zero;
        rb.angularVelocity = Vector3.zero;

        // 자신의 레이어를 장애물 마스크로 사용 (같은 레이어에 장애물이 배치됨)
        obstacleLayerMask = 1 << gameObject.layer;

        navPathLength     = float.MaxValue;
        nextNavWaypoint   = transform.position;
        nearestBoat       = null;
        nearestDist       = float.MaxValue;
        nearestBearDeg    = 0f;
        nearestRelHeadDeg = 0f;
        colregsSituation  = ColregsSituation.None;

        trainingManager?.OnBoatEpisodeBegin(this);

        if (goalTransform != null)
        {
            UpdateNavPath();
            prevGoalDistance = navPathLength < float.MaxValue
                ? navPathLength
                : HorizontalDistance(transform.position, goalTransform.position);
        }
        else
        {
            prevGoalDistance = float.MaxValue;
        }
    }

    public void SetGoal(Transform goal) => goalTransform = goal;

    private void FixedUpdate()
    {
        if (!episodeEnded)
            RequestDecision();
    }

    // ═══════════════════════════════════════════════════════════════════
    // 디지털 트윈 경로계획(롤아웃) 지원
    // ═══════════════════════════════════════════════════════════════════

    /// <summary>현재 에피소드 종료 여부 (외부 롤아웃 제어용 읽기 전용).</summary>
    public bool EpisodeEnded => episodeEnded;

    /// <summary>
    /// 디지털 트윈 경로계획용 롤아웃 시작.
    /// 지정 위치/방향에 배치하고 내부 상태를 초기화해 목표까지 정책 주행을 개시한다.
    /// (BoatTrainingManager 재배치와 무관하게 단독 동작 — trainingManager는 null이어야 함)
    /// </summary>
    public void BeginPlanningRollout(Vector3 startPos, Quaternion startRot, Transform goal)
    {
        if (rb == null) rb = GetComponent<Rigidbody>();

        goalTransform      = goal;
        rb.position        = startPos;
        rb.rotation        = startRot;
        rb.linearVelocity  = Vector3.zero;
        rb.angularVelocity = Vector3.zero;

        currentThrust = 0f;
        currentTurn   = 0f;
        prevTurn      = 0f;
        episodeTimer  = 0f;
        episodeEnded  = false;

        // 같은 레이어에 배치된 장애물을 레이캐스트로 감지
        obstacleLayerMask = 1 << gameObject.layer;

        navPathLength   = float.MaxValue;
        nextNavWaypoint = startPos;

        if (goalTransform != null)
        {
            UpdateNavPath();
            prevGoalDistance = navPathLength < float.MaxValue
                ? navPathLength
                : HorizontalDistance(startPos, goalTransform.position);
        }
        else
        {
            prevGoalDistance = float.MaxValue;
        }
    }

    /// <summary>롤아웃 종료 — 주행 정지(추가 물리력·의사결정 차단).</summary>
    public void StopPlanningRollout()
    {
        episodeEnded = true;
        if (rb != null)
        {
            rb.linearVelocity  = Vector3.zero;
            rb.angularVelocity = Vector3.zero;
        }
    }

    // ── 관측 (4 + 3 + 2 + obstacleRayCount + 5 = 22 차원) ─────────────
    public override void CollectObservations(VectorSensor sensor)
    {
        // 선수 방향(BowDir)의 월드 방위각 — eulerAngles.y 대신 실제 BowDir 벡터에서 계산
        float headingRad = Mathf.Atan2(BowDir.x, BowDir.z);
        float speedMs    = rb != null ? Vector3.Dot(rb.linearVelocity, BowDir) : 0f;
        float turnRate   = rb != null ? rb.angularVelocity.y : 0f;

        // 자선 상태 (4)
        sensor.AddObservation(Mathf.Sin(headingRad));
        sensor.AddObservation(Mathf.Cos(headingRad));
        sensor.AddObservation(Mathf.Clamp(speedMs  / maxForwardSpeed,  -1f, 1f));
        sensor.AddObservation(Mathf.Clamp(turnRate / (maxTurnSpeedDeg * Mathf.Deg2Rad), -1f, 1f));

        // 다음 NavMesh 웨이포인트 방향 (3) — GO1Agent 방식
        UpdateNavPath();
        if (goalTransform != null)
        {
            Vector3 toWP    = nextNavWaypoint - transform.position;
            toWP.y          = 0f;
            float wpDist    = toWP.magnitude;
            float wpBearRad = Mathf.Atan2(toWP.x, toWP.z) - headingRad;

            sensor.AddObservation(Mathf.Sin(wpBearRad));
            sensor.AddObservation(Mathf.Cos(wpBearRad));
            sensor.AddObservation(Mathf.Clamp01(wpDist / 50f));
        }
        else
        {
            sensor.AddObservation(0f);
            sensor.AddObservation(0f);
            sensor.AddObservation(1f);
        }

        // 경계 정보 (2): 중심 방향 + 경계까지 거리
        {
            Vector3 toCenter    = boundaryCenter - transform.position;
            toCenter.y          = 0f;
            float distFromCenter = toCenter.magnitude;
            float bearRad        = Mathf.Atan2(toCenter.x, toCenter.z) - headingRad;

            sensor.AddObservation(Mathf.Sin(bearRad));                           // 중심 방향
            sensor.AddObservation(Mathf.Clamp01(distFromCenter / boundaryRadius)); // 0=중심, 1=경계
        }

        // 장애물 레이캐스트 (obstacleRayCount) — 선수(BowDir) 기준으로 360° 균등 분포
        for (int i = 0; i < obstacleRayCount; i++)
        {
            float   angle = 360f / obstacleRayCount * i;
            Vector3 dir   = Quaternion.Euler(0f, angle, 0f) * BowDir;
            dir.y = 0f;

            float obs = 0f;
            if (Physics.Raycast(transform.position, dir, out RaycastHit hit,
                                obstacleRayLength, obstacleLayerMask))
                obs = 1f - (hit.distance / obstacleRayLength);

            sensor.AddObservation(obs);
        }

        // COLREGS: 가장 가까운 타선 정보 (5) ─────────────────────────────
        // bearSin, bearCos, dist, headSin, headCos
        UpdateNearestVessel();
        if (nearestBoat != null && nearestDist < colregsDetectRange)
        {
            float bearRad = nearestBearDeg    * Mathf.Deg2Rad;
            float headRad = nearestRelHeadDeg * Mathf.Deg2Rad;
            sensor.AddObservation(Mathf.Sin(bearRad));
            sensor.AddObservation(Mathf.Cos(bearRad));
            sensor.AddObservation(Mathf.Clamp01(nearestDist / colregsDetectRange));
            sensor.AddObservation(Mathf.Sin(headRad));
            sensor.AddObservation(Mathf.Cos(headRad));
        }
        else
        {
            sensor.AddObservation(0f);  // sin(0) = 정면
            sensor.AddObservation(1f);  // cos(0)
            sensor.AddObservation(1f);  // 최대 거리
            sensor.AddObservation(0f);  // 같은 방향
            sensor.AddObservation(1f);  // cos(0)
        }
    }

    // ── 행동 처리 ─────────────────────────────────────────────────────────
    // action[0]: 추력  [-1,1] → 리매핑 [0,1]
    // action[1]: 선회  [-1,1] (음수=좌, 양수=우)
    public override void OnActionReceived(ActionBuffers actions)
    {
        if (episodeEnded)
            return;

        float thrustInput = (actions.ContinuousActions[0] + 1f) * 0.5f;
        float turnInput   = Mathf.Clamp(actions.ContinuousActions[1], -1f, 1f);

        currentThrust = Mathf.Lerp(currentThrust, thrustInput, thrustSmoothFactor);
        currentTurn   = Mathf.Lerp(currentTurn,   turnInput,   turnSmoothFactor);

        ApplyMovement();
        ComputeAndAddRewards();

        prevTurn      = currentTurn;
        episodeTimer += Time.fixedDeltaTime;

        // 경계 이탈 체크
        float distFromCenter = HorizontalDistance(transform.position, boundaryCenter);
        if (distFromCenter > boundaryRadius)
        {
            AddReward(penaltyCollision);
            trainingManager?.OnBoatFailed(this);
            episodeEnded = true;
            EndEpisode();
            return;
        }

        if (episodeTimer >= maxEpisodeTimeSec)
        {
            AddReward(penaltyTimeout);
            trainingManager?.OnBoatFailed(this);
            episodeEnded = true;
            EndEpisode();
            return;
        }

        if (goalTransform != null)
        {
            float dist = HorizontalDistance(transform.position, goalTransform.position);
            if (dist <= goalArrivalDistance)
            {
                AddReward(rewardGoalArrival);
                trainingManager?.OnBoatReachedGoal(this);
                onGoalReached?.Invoke();
                episodeEnded = true;
                EndEpisode();
            }
        }
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        ActionSegment<float> cont = actionsOut.ContinuousActions;
        // 추력: 키 미입력 시 0 → 리매핑으로 50% 추력이 걸리는 문제 방지
        // action[0]=-1 이 "정지"(thrustInput=0)에 해당하므로 W만 전진, 나머지는 -1
        float vert = Input.GetAxis("Vertical");
        cont[0] = vert > 0f ? vert : -1f;
        cont[1] = Input.GetAxis("Horizontal");
    }

    // ═══════════════════════════════════════════════════════════════════
    // 이동
    // ═══════════════════════════════════════════════════════════════════

    private void ApplyMovement()
    {
        float speedTarget     = currentThrust * maxForwardSpeed;
        float currentSpeedFwd = Vector3.Dot(rb.linearVelocity, BowDir);
        float thrustForce     = (speedTarget - currentSpeedFwd) * rb.mass * 12f;
        rb.AddForce(BowDir * thrustForce, ForceMode.Force);

        // AddTorque는 자동 계산된 관성모멘트(I_y≈24)로 인해 회전력이 극히 약해짐.
        // 목표 각속도를 직접 지정하면 관성모멘트 크기와 무관하게 maxTurnSpeedDeg를 그대로 적용할 수 있음.
        float speedRatio  = Mathf.Max(0.2f, Mathf.Clamp01(Mathf.Abs(currentSpeedFwd) / maxForwardSpeed));
        float targetOmega = currentTurn * maxTurnSpeedDeg * Mathf.Deg2Rad * speedRatio;
        Vector3 av = rb.angularVelocity;
        av.y = Mathf.Lerp(av.y, targetOmega, 0.3f);
        rb.angularVelocity = av;
    }

    // ═══════════════════════════════════════════════════════════════════
    // 보상
    // ═══════════════════════════════════════════════════════════════════

    private void ComputeAndAddRewards()
    {
        AddReward(penaltyStepBase);
        AddReward(-Mathf.Abs(currentTurn - prevTurn) * penaltyTurnJerk);

        if (goalTransform == null) return;

        // 다음 NavMesh 웨이포인트 방향 정렬 보상 (GO1Agent 구조, 배 속도에 맞게 스케일 축소)
        Vector3 toWP = nextNavWaypoint - transform.position;
        toWP.y = 0f;
        if (toWP.sqrMagnitude > 0.01f)
        {
            float facing = Vector3.Dot(BowDir, toWP.normalized);
            AddReward(facing * 0.003f);          // GO1: 0.01 → 배: 0.003

            if (facing > 0.95f) AddReward(0.001f);  // 정면 정렬 보너스
            if (facing < 0f)    AddReward(-0.002f);  // 반대 방향 패널티
        }

        // NavMesh 경로 단축 보상 (GO1Agent 구조, 클램프로 스케일 무관)
        float currDist = navPathLength < float.MaxValue
                       ? navPathLength
                       : HorizontalDistance(transform.position, goalTransform.position);
        float approach = (prevGoalDistance - currDist) * rewardGoalApproachScale;
        AddReward(Mathf.Clamp(approach, -0.02f, 0.05f));
        prevGoalDistance = currDist;

        // COLREGS 규칙 준수 보상
        AddColregsReward();
    }

    // ═══════════════════════════════════════════════════════════════════
    // 충돌
    // ═══════════════════════════════════════════════════════════════════

    private void OnCollisionEnter(Collision collision)
    {
        HandleHit(collision.gameObject);
    }

    private void OnTriggerEnter(Collider other)
    {
        HandleHit(other.gameObject);
    }

    private void HandleHit(GameObject other)
    {
        if (episodeEnded) return;
        if (episodeTimer < 0.1f) return;

        // 장애물 레이어가 아닌 오브젝트 (물 표면, 하늘 등) 무시
        if (obstacleLayerMask.value != 0 && ((1 << other.layer) & obstacleLayerMask.value) == 0)
            return;

        if (goalTransform != null && other == goalTransform.gameObject) return;
        if (goalTransform != null && goalTransform.parent != null &&
            other == goalTransform.parent.gameObject) return;

        AddReward(penaltyCollision);
        trainingManager?.OnBoatFailed(this);
        episodeEnded = true;
        EndEpisode();
    }

    // ═══════════════════════════════════════════════════════════════════
    // COLREGS
    // ═══════════════════════════════════════════════════════════════════

    private void UpdateNearestVessel()
    {
        nearestBoat = trainingManager?.GetNearestOtherBoat(this);

        if (nearestBoat == null)
        {
            nearestDist       = float.MaxValue;
            nearestBearDeg    = 0f;
            nearestRelHeadDeg = 0f;
            colregsSituation  = ColregsSituation.None;
            return;
        }

        Vector3 toOther = nearestBoat.transform.position - transform.position;
        toOther.y    = 0f;
        nearestDist  = toOther.magnitude;

        if (nearestDist < 0.01f) { colregsSituation = ColregsSituation.None; return; }

        Vector3 dir = toOther / nearestDist;

        // 선수(BowDir) 기준 우현 방위각 (도, 우현+ / 좌현-)
        // Atan2(우현성분, 선수성분)
        nearestBearDeg = Mathf.Rad2Deg * Mathf.Atan2(
            Vector3.Dot(dir, StarboardDir),
            Vector3.Dot(dir, BowDir));

        // 자선 대비 타선의 선수 방향 (BowDir 기반 실제 헤딩 비교)
        float myHeadDeg    = Mathf.Atan2(BowDir.x,                   BowDir.z)                   * Mathf.Rad2Deg;
        float otherHeadDeg = Mathf.Atan2(nearestBoat.BowDir.x,       nearestBoat.BowDir.z)       * Mathf.Rad2Deg;
        nearestRelHeadDeg  = Mathf.DeltaAngle(myHeadDeg, otherHeadDeg);

        colregsSituation = ClassifyColregs();
    }

    private ColregsSituation ClassifyColregs()
    {
        if (nearestDist > colregsDetectRange) return ColregsSituation.None;

        float b = nearestBearDeg;    // 타선 방위 (+우현)
        float h = nearestRelHeadDeg; // 타선 선수 방향 (자선 기준)

        // Rule 14: 마주치는 상태 ─ 타선이 정선수 ±15°, 서로 역침로
        if (Mathf.Abs(b) < 15f && Mathf.Abs(h) > 150f)
            return ColregsSituation.HeadOn;

        // Rule 13: 추월 ─ 자선이 타선의 선미 구역(±22.5° 초과)에서 접근
        Vector3 toBySelf = transform.position - nearestBoat.transform.position;
        toBySelf.y = 0f;
        if (toBySelf.sqrMagnitude > 0.01f)
        {
            float bearFromOther = Mathf.Rad2Deg * Mathf.Atan2(
                Vector3.Dot(toBySelf.normalized, nearestBoat.StarboardDir),
                Vector3.Dot(toBySelf.normalized, nearestBoat.BowDir));
            if (Mathf.Abs(bearFromOther) > 112.5f)
                return ColregsSituation.Overtaking;
        }

        // Rule 15: 횡단 ─ 타선이 우현(피항선) / 좌현(유지선)
        if (b >   5f && b <  112.5f) return ColregsSituation.CrossingGiveWay;
        if (b <  -5f && b > -112.5f) return ColregsSituation.CrossingStandOn;

        // 타선이 선미 방향 → 추월당하는 중
        if (Mathf.Abs(b) > 157.5f) return ColregsSituation.BeingOvertaken;

        return ColregsSituation.None;
    }

    private void AddColregsReward()
    {
        if (nearestBoat == null || nearestDist > colregsAlertRange) return;
        if (colregsSituation == ColregsSituation.None) return;

        // 거리가 가까울수록 보상·패널티 강도 증가
        float urgency = 1f - Mathf.Clamp01(nearestDist / colregsAlertRange);

        switch (colregsSituation)
        {
            case ColregsSituation.HeadOn:
                // Rule 14: 우현으로 선회 (양선 모두)
                if (currentTurn > 0.15f)       AddReward( 0.005f * urgency);
                else if (currentTurn < -0.15f) AddReward(-0.010f * urgency); // 좌현 선회 위반
                break;

            case ColregsSituation.CrossingGiveWay:
                // Rule 15/16: 우현 선회하여 충분히 피항
                if (currentTurn > 0.15f) AddReward(0.005f * urgency);

                // 타선 선수를 가로지를 위험 → 패널티 (선수 방향 직진 + 가까운 거리)
                Vector3 toOther = nearestBoat.transform.position - transform.position;
                toOther.y = 0f;
                if (Vector3.Dot(BowDir, toOther.normalized) > 0.7f && nearestDist < 12f)
                    AddReward(-0.015f * urgency);
                break;

            case ColregsSituation.CrossingStandOn:
                // Rule 17: 침로·속력 유지
                if (Mathf.Abs(currentTurn) < 0.15f) AddReward(0.002f * urgency);
                break;

            case ColregsSituation.Overtaking:
                // Rule 13: 피항 의무 — 능동적 피항 행동 장려
                if (Mathf.Abs(currentTurn) > 0.15f && nearestDist < 15f)
                    AddReward(0.002f * urgency);
                break;

            case ColregsSituation.BeingOvertaken:
                // Rule 13: 유지선 — 침로 유지
                if (Mathf.Abs(currentTurn) < 0.15f) AddReward(0.001f * urgency);
                break;
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    // 유틸리티
    // ═══════════════════════════════════════════════════════════════════

    // ═══════════════════════════════════════════════════════════════════
    // NavMesh
    // ═══════════════════════════════════════════════════════════════════

    private void UpdateNavPath()
    {
        if (goalTransform == null || navPath == null) return;

        // NavMesh.SamplePosition으로 가장 가까운 NavMesh 지점을 자동 탐지
        // navMeshY 하드코딩 불필요 — 검색 반경 10m 안에 NavMesh가 있으면 찾음
        NavMeshHit fromHit, toHit;
        bool fromOk = NavMesh.SamplePosition(transform.position,      out fromHit, 10f, NavMesh.AllAreas);
        bool toOk   = NavMesh.SamplePosition(goalTransform.position,  out toHit,   10f, NavMesh.AllAreas);

        Vector3 from = fromOk ? fromHit.position : transform.position;
        Vector3 to   = toOk   ? toHit.position   : goalTransform.position;

        bool ok = NavMesh.CalculatePath(from, to, NavMesh.AllAreas, navPath);

        if (ok && navPath.status != NavMeshPathStatus.PathInvalid && navPath.corners.Length >= 2)
        {
            // 총 경로 길이 계산
            navPathLength = 0f;
            for (int i = 0; i < navPath.corners.Length - 1; i++)
                navPathLength += Vector3.Distance(navPath.corners[i], navPath.corners[i + 1]);

            // 다음 웨이포인트: 너무 가까우면 그 다음 코너로 넘김 (GO1Agent 방식)
            nextNavWaypoint = navPath.corners[1];
            if (navPath.corners.Length > 2 &&
                HorizontalDistance(transform.position, nextNavWaypoint) < 3f)
                nextNavWaypoint = navPath.corners[2];
        }
        else
        {
            // NavMesh 실패 시 직선 폴백
            navPathLength   = HorizontalDistance(transform.position, goalTransform.position);
            nextNavWaypoint = goalTransform.position;
        }
    }

    private static float HorizontalDistance(Vector3 a, Vector3 b)
    {
        float dx = a.x - b.x;
        float dz = a.z - b.z;
        return Mathf.Sqrt(dx * dx + dz * dz);
    }

    private void OnDrawGizmosSelected()
    {
        if (!drawDebugGizmos) return;

        if (goalTransform != null)
        {
            Gizmos.color = Color.green;
            Gizmos.DrawLine(transform.position, goalTransform.position);
            Gizmos.DrawWireSphere(goalTransform.position, goalArrivalDistance);
        }

        Gizmos.color = Color.yellow;
        for (int i = 0; i < obstacleRayCount; i++)
        {
            float   angle = 360f / obstacleRayCount * i;
            Vector3 dir   = Quaternion.Euler(0f, angle, 0f) * BowDir;
            dir.y = 0f;
            Gizmos.DrawRay(transform.position, dir.normalized * obstacleRayLength);
        }
    }
}
