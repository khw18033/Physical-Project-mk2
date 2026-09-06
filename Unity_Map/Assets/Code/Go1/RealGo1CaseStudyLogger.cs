using System;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

/// <summary>
/// 실제 Unitree Go1 폐루프 케이스 스터디 전용 이벤트 로거입니다.
/// 논문 Section 6.3 "실제 Go1 사례연구" 그림/표의 시퀀스 데이터를 추출합니다.
///
/// 캡처하는 이벤트 시퀀스:
///   1) path_mission_start   - M키로 가상 경로 생성 시작
///   2) virtual_path_done    - 가상 경로 생성 완료
///   3) path_sent_to_robot   - point-to-point 경로 실제 Go1에 전송
///   4) real_go1_started     - 실제 Go1 주행 시작 (state_change=true)
///   5) obstacle_detected    - 실제 Go1이 장애물 탐지 (ArUco/YOLO)
///   6) obstacle_in_unity    - Unity에 장애물 반영 완료
///   7) replan_triggered     - 재탐색 시작
///   8) virtual_replan_done  - 재탐색 가상 경로 생성 완료
///   9) replan_path_sent     - 재탐색 경로 실제 Go1에 전송
///  10) goal_reached         - 실제 Go1 목표 도달
///
/// 사용법:
///   - GO1Agent와 같은 GameObject에 추가합니다.
///   - GO1Agent의 각 단계에서 LogEvent() 또는 전용 메서드를 호출합니다.
///   - 실험 종료 후 case_study_log.csv가 GO1_CaseStudy_Log 폴더에 생성됩니다.
/// </summary>
[DisallowMultipleComponent]
public class RealGo1CaseStudyLogger : MonoBehaviour
{
    [Header("References")]
    public GO1Agent agent;

    [Header("Output")]
    public string outputFolderName = "GO1_CaseStudy_Log";
    public bool createSessionSubfolder = true;

    [Header("Settings")]
    [Tooltip("케이스 스터디 세션 ID입니다. 비우면 타임스탬프를 사용합니다.")]
    public string caseStudyId = "";

    [Tooltip("로그를 Console에 출력합니다.")]
    public bool debugLogs = true;

    // ─── 런타임 ───
    private static readonly string autoSessionId =
        DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);

    private string logCsvPath;
    private bool initialized;
    private float sessionStartTime;
    private int eventIndex;

    // ─── 이벤트 타입 상수 ───
    public const string EVT_MISSION_START        = "path_mission_start";
    public const string EVT_VIRTUAL_PATH_DONE    = "virtual_path_done";
    public const string EVT_PATH_SENT            = "path_sent_to_robot";
    public const string EVT_REAL_GO1_STARTED     = "real_go1_started";
    public const string EVT_OBSTACLE_DETECTED    = "obstacle_detected";
    public const string EVT_OBSTACLE_IN_UNITY    = "obstacle_in_unity";
    public const string EVT_REPLAN_TRIGGERED     = "replan_triggered";
    public const string EVT_VIRTUAL_REPLAN_DONE  = "virtual_replan_done";
    public const string EVT_REPLAN_PATH_SENT     = "replan_path_sent";
    public const string EVT_GOAL_REACHED         = "goal_reached";
    public const string EVT_MISSION_ABORTED      = "mission_aborted";
    public const string EVT_CUSTOM               = "custom";

    private void Awake()
    {
        if (agent == null)
            agent = GetComponent<GO1Agent>();
    }

    private void EnsureInit()
    {
        if (initialized) return;
        initialized = true;

        string sid = string.IsNullOrEmpty(caseStudyId) ? autoSessionId : caseStudyId;
        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        string baseDir = Path.Combine(projectRoot, outputFolderName);
        string dir = createSessionSubfolder ? Path.Combine(baseDir, sid) : baseDir;
        Directory.CreateDirectory(dir);

        logCsvPath = Path.Combine(dir, "case_study_log.csv");
        sessionStartTime = Time.time;
        eventIndex = 0;

        if (!File.Exists(logCsvPath) || new FileInfo(logCsvPath).Length == 0)
        {
            const string header =
                "session_id,event_index,event_type,elapsed_sec,real_time_iso," +
                "agent_x,agent_z,agent_yaw_deg,target_x,target_z," +
                "obstacle_x,obstacle_z,waypoints_sent,detail\n";
            File.WriteAllText(logCsvPath, header, new UTF8Encoding(true));
        }

        if (debugLogs)
            Debug.Log("[RealGo1CaseStudyLogger] 초기화 완료 | path=" + logCsvPath, this);
    }

    // ─── 공개 로깅 API ──────────────────────────────────────────────────────

    public void LogMissionStart()
    {
        LogEvent(EVT_MISSION_START, Vector3.zero, "virtual_path_generation_begin");
    }

    public void LogVirtualPathDone(int rawWaypointCount)
    {
        LogEvent(EVT_VIRTUAL_PATH_DONE, Vector3.zero,
            "raw_waypoints=" + rawWaypointCount);
    }

    public void LogPathSentToRobot(int sentWaypointCount, float pathLengthM)
    {
        LogEvent(EVT_PATH_SENT, Vector3.zero,
            "sent_wpts=" + sentWaypointCount + ";path_len=" + pathLengthM.ToString("F2", CultureInfo.InvariantCulture) + "m");
    }

    public void LogRealGo1Started()
    {
        LogEvent(EVT_REAL_GO1_STARTED, Vector3.zero, "state_change_true");
    }

    public void LogObstacleDetected(Vector3 obstacleWorldPos, string detectorType)
    {
        LogEvent(EVT_OBSTACLE_DETECTED, obstacleWorldPos,
            "detector=" + detectorType);
    }

    /// <summary>
    /// 실물 센서(카메라/서버)가 패킷에 실어 보낸 자기 시각(sourceTimestamp)을 함께 기록합니다.
    /// 이 행의 real_time_iso(트윈 수신 시각)와의 차이가 "탐지→트윈 도달" 편도 지연이 됩니다
    /// (양쪽 시계가 NTP 등으로 동기화되어 있을 때). 인과 타임라인 표의 첫 사슬을 담당합니다.
    /// </summary>
    public void LogObstacleDetected(Vector3 obstacleWorldPos, string detectorType, string sourceTimestamp, int detectionCount)
    {
        LogEvent(EVT_OBSTACLE_DETECTED, obstacleWorldPos,
            "detector=" + detectorType +
            ";source_ts=" + (sourceTimestamp ?? "") +
            ";detections=" + detectionCount);
    }

    public void LogObstacleInUnity(GameObject obstacle)
    {
        Vector3 pos = obstacle != null ? obstacle.transform.position : Vector3.zero;
        string name = obstacle != null ? obstacle.name : "null";
        LogEvent(EVT_OBSTACLE_IN_UNITY, pos, "obstacle=" + name);
    }

    public void LogReplanTriggered(string obstacleTag)
    {
        LogEvent(EVT_REPLAN_TRIGGERED, Vector3.zero, "trigger=" + obstacleTag);
    }

    public void LogVirtualReplanDone(int waypointCount)
    {
        LogEvent(EVT_VIRTUAL_REPLAN_DONE, Vector3.zero,
            "replan_waypoints=" + waypointCount);
    }

    public void LogReplanPathSent(int sentWaypointCount, float pathLengthM)
    {
        LogEvent(EVT_REPLAN_PATH_SENT, Vector3.zero,
            "sent_wpts=" + sentWaypointCount + ";path_len=" + pathLengthM.ToString("F2", CultureInfo.InvariantCulture) + "m");
    }

    public void LogGoalReached(float finalErrorM)
    {
        LogEvent(EVT_GOAL_REACHED, Vector3.zero,
            "final_error=" + finalErrorM.ToString("F3", CultureInfo.InvariantCulture) + "m");
    }

    public void LogMissionAborted(string reason)
    {
        LogEvent(EVT_MISSION_ABORTED, Vector3.zero, "reason=" + reason);
    }

    /// <summary>임의 이벤트를 기록합니다.</summary>
    public void LogEvent(string eventType, Vector3 obstaclePos, string detail = "")
    {
        EnsureInit();

        eventIndex++;
        float elapsed = Time.time - sessionStartTime;

        Vector3 agentPos   = agent != null ? agent.transform.position : Vector3.zero;
        float   agentYaw   = agent != null ? agent.transform.eulerAngles.y : 0f;
        Vector3 targetPos  = agent != null && agent.target != null
            ? agent.target.position
            : Vector3.zero;

        string sid = string.IsNullOrEmpty(caseStudyId) ? autoSessionId : caseStudyId;

        string row = string.Join(",", new[]
        {
            Q(sid),
            eventIndex.ToString(CultureInfo.InvariantCulture),
            Q(eventType),
            F(elapsed),
            Q(DateTime.Now.ToString("o", CultureInfo.InvariantCulture)),
            F(agentPos.x), F(agentPos.z), F(agentYaw),
            F(targetPos.x), F(targetPos.z),
            F(obstaclePos.x), F(obstaclePos.z),
            string.Empty,
            Q(detail)
        });

        try { File.AppendAllText(logCsvPath, row + "\n", new UTF8Encoding(false)); }
        catch (Exception e)
        { Debug.LogError("[RealGo1CaseStudyLogger] CSV 저장 실패: " + e.Message); }

        if (debugLogs)
        {
            Debug.Log(
                $"[RealGo1CaseStudyLogger] [{eventIndex}] {eventType} | " +
                $"elapsed={elapsed:F3}s | {detail}",
                this
            );
        }
    }

    [ContextMenu("Print Log Summary")]
    public void PrintLogSummary()
    {
        Debug.Log(
            "[RealGo1CaseStudyLogger] 이벤트 수=" + eventIndex +
            ", 경과=" + (Time.time - sessionStartTime).ToString("F1") + "s" +
            ", csv=" + logCsvPath,
            this
        );
    }

    private string F(float v) => v.ToString("F6", CultureInfo.InvariantCulture);
    private string Q(string v) => "\"" + (v ?? "").Replace("\"", "\"\"") + "\"";
}
