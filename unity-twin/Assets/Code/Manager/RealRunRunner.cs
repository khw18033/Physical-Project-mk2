// 실제 Go1 한 번 주행을 에디터 창 없이 제어하고 기록한다.
//
// 순서
//   1) 로봇 상태 수신 확인                         (움직임 없음)
//   2) 360 카메라 마커로 가상 로봇을 실제 위치에 맞춤  (움직임 없음, anchor360_marker_live.py 가 보내 줘야 함)
//   3) 목표 설정, 360/Go1 탐지 설정, '원래 있던 물건' 기록 (움직임 없음)
//   4) real_run/GO 파일이 생길 때까지 대기 → 생기면 미션 시작 (여기서부터 로봇이 움직인다)
//   5) 도착/정지/시간 초과까지 화면과 로그 기록. real_run/STOP 파일이 생기면 즉시 미션 정지(PATH_CANCEL)
//
// 설정: GO1_Proactive_Evaluation/real_run/config.json     상태: real_run/status.txt

using System;
using System.Collections;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

public class RealRunRunner : MonoBehaviour
{
    public const string Dir = "GO1_Proactive_Evaluation/real_run";

    [Serializable]
    public class Config
    {
        public string robotId = "GO1_A";
        public string robotHost = "";      // 비어 있지 않으면 경로를 이 주소로 보낸다 (씬에 저장된 주소 대신)
        public float targetX = 1.74f, targetZ = 6.29f;
        public float navMeshPadding = -0.03f;
        public float minConf360 = 0.30f, maxFootprint360 = 0.8f, nearFloor360 = 0.3f;
        public bool useBaseline360 = true;
        public float baselineSec = 6f;
        public bool go1GuardAsObstacle = true;
        public float waitMarkerSec = 240f, waitGoSec = 1800f, missionTimeoutSec = 240f;
        public bool requireMarker = true;
        [Tooltip("진단 모드: 경로를 로봇이 아니라 이 PC(127.0.0.1)로 보내 로봇이 움직일 수 없게 하고, 출발 신호 없이 바로 미션을 시작해 경로 계산이 되는지만 본다.")]
        public bool diagnoseNoRobot = false;
        [Tooltip("진단용: 경로 계산 중에 로봇 상태값이 가상 로봇을 붙잡지 못하게 매 프레임 driveByState 를 끈다.")]
        public bool diagnoseForceNoStateDrive = false;
    }

    private string dir;
    private StringBuilder log = new StringBuilder();
    private GO1Agent agent; private UnityTeleopAndMirror utm; private Transform robot;

    private void Awake()
    {
        Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
        Application.SetStackTraceLogType(LogType.Warning, StackTraceLogType.None);
    }

    private void Start() { StartCoroutine(Run()); }

    private void Status(string s)
    {
        string line = DateTime.Now.ToString("HH:mm:ss") + " " + s;
        log.AppendLine(line);
        Debug.Log("[RealRun] " + s);
        try { File.WriteAllText(Path.Combine(dir, "status.txt"), log.ToString(), new UTF8Encoding(true)); } catch { }
    }

    private static float Yaw(Transform t)
    {
        Vector3 f = -t.right; f.y = 0f;
        return Mathf.Repeat(Mathf.Atan2(f.x, f.z) * Mathf.Rad2Deg, 360f);
    }

    private bool HasState()
    {
        FieldInfo f = typeof(UnityTeleopAndMirror).GetField("hasState", BindingFlags.Instance | BindingFlags.NonPublic);
        return f != null && utm != null && (bool)f.GetValue(utm);
    }

    private bool Flag(string name) => File.Exists(Path.Combine(dir, name));

    private IEnumerator Run()
    {
        dir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, Dir);
        Directory.CreateDirectory(dir);
        foreach (string f in new[] { "GO", "STOP", "status.txt" }) { try { File.Delete(Path.Combine(dir, f)); } catch { } }
        Config cfg = new Config();
        string cp = Path.Combine(dir, "config.json");
        if (File.Exists(cp)) cfg = JsonUtility.FromJson<Config>(File.ReadAllText(cp));
        var ci = CultureInfo.InvariantCulture;

        yield return new WaitForSecondsRealtime(4f);

        foreach (var u in FindObjectsByType<UnityTeleopAndMirror>(FindObjectsSortMode.None))
            if (u.robotId == cfg.robotId) { utm = u; robot = u.driver != null ? u.driver.transform : u.robotRoot; }
        agent = robot != null ? robot.GetComponentInChildren<GO1Agent>() : null;
        if (agent == null) agent = FindFirstObjectByType<GO1Agent>();
        if (utm == null || robot == null || agent == null || agent.target == null)
        { Status("FAILED: 로봇/에이전트/목표를 찾지 못함"); Quit(1); yield break; }
        if (!string.IsNullOrEmpty(cfg.robotHost) && agent.pathSender != null)
            agent.pathSender.remoteIp = cfg.robotHost;      // 프리팹 값은 Play 진입 때 되돌아가므로 여기서 다시 맞춘다
        Status("로봇 '" + robot.name + "', 로봇 쪽 주소 " + utm.sdkPcIp + ", 경로 전송 " +
               (agent.pathSender != null ? agent.pathSender.remoteIp + ":" + agent.pathSender.remotePort : "없음") +
               ", virtualOnlyMode=" + agent.virtualOnlyMode);

        // 1) 로봇 상태 수신
        float t0 = Time.realtimeSinceStartup;
        while (!HasState() && Time.realtimeSinceStartup - t0 < 20f) yield return null;
        Status(HasState() ? "로봇 상태 수신 OK" : "경고: 20초 동안 로봇 상태를 받지 못함");

        // 2) 마커 정합
        var marker = FindFirstObjectByType<Robot360MarkerReceiver>();
        if (marker == null) marker = new GameObject("Robot360Marker").AddComponent<Robot360MarkerReceiver>();
        marker.robotId = cfg.robotId;
        marker.followGain = 0f;                      // 출발 전 한 번만 맞춘다 (주행 중에는 360 탐지가 카메라를 쓴다)
        Status("마커 대기 (UDP " + marker.listenPort + ")");
        t0 = Time.realtimeSinceStartup;
        while (!marker.Aligned && Time.realtimeSinceStartup - t0 < cfg.waitMarkerSec && !Flag("STOP")) yield return null;
        if (!marker.Aligned)
        {
            Status("마커 정합 안 됨");
            if (cfg.requireMarker) { Status("FAILED: 마커 없이 진행하지 않음"); Quit(1); yield break; }
        }
        else
        {
            Vector3 want = marker.LastWorldPos; float wantYaw = marker.LastWorldYawDeg;
            yield return new WaitForSecondsRealtime(3f);
            Vector3 d = robot.position - want; d.y = 0f;
            Status("마커 정합: (" + want.x.ToString("F3", ci) + ", " + want.z.ToString("F3", ci) + ") " + wantYaw.ToString("F1", ci) +
                   "도 | 3초 뒤 가상 로봇 (" + robot.position.x.ToString("F3", ci) + ", " + robot.position.z.ToString("F3", ci) + ") " +
                   Yaw(robot).ToString("F1", ci) + "도 | 차이 " + (d.magnitude * 100f).ToString("F1", ci) + " cm, " +
                   Mathf.DeltaAngle(wantYaw, Yaw(robot)).ToString("F1", ci) + "도");
        }

        // 3) 목표와 탐지 설정
        agent.target.position = new Vector3(cfg.targetX, agent.target.position.y, cfg.targetZ);
        var rx = FindActive360();
        if (rx != null)
        {
            rx.navMeshPadding = cfg.navMeshPadding;
            rx.minPlaceConfidence = cfg.minConf360; rx.maxFootprintM = cfg.maxFootprint360; rx.nearFloorM = cfg.nearFloor360;
            rx.useBaseline = cfg.useBaseline360;
        }
        var guard = FindFirstObjectByType<Go1FrontGuardReceiver>();
        if (guard != null) { guard.asObstacle = cfg.go1GuardAsObstacle; guard.navMeshPadding = cfg.navMeshPadding; }
        Status("목표 (" + cfg.targetX.ToString("F2", ci) + ", " + cfg.targetZ.ToString("F2", ci) + ") | 360 탐지 수신기 " +
               (rx != null ? "있음" : "없음") + ", Go1 정면 수신기 " + (guard != null ? "있음" : "없음"));

        // 360 탐지가 들어오기 시작하면 그때 보이는 것을 '원래 있던 물건'으로 기록
        if (rx != null && cfg.useBaseline360)
        {
            Status("360 탐지 대기 (anchor360_local.py 를 켜 주세요)");
            t0 = Time.realtimeSinceStartup;
            while (rx.statDetections == 0 && Time.realtimeSinceStartup - t0 < cfg.waitGoSec && !Flag("STOP") && !Flag("SKIP360")) yield return null;
            if (rx.statDetections > 0)
            {
                rx.BeginBaselineCapture(cfg.baselineSec);
                yield return new WaitForSecondsRealtime(cfg.baselineSec + 1.5f);
                Status("원래 있던 물건 " + rx.BaselineCount + "개 기록. 지금 큐브 " + CountCubes() + "개");
            }
            else Status("360 탐지 없이 진행");
        }

        // 계획 경로(참고): 가상 맵의 NavMesh 경로
        var p = new NavMeshPath();
        bool okPath = NavMesh.SamplePosition(robot.position, out NavMeshHit ha, 1f, NavMesh.AllAreas) &&
                      NavMesh.SamplePosition(agent.target.position, out NavMeshHit hb, 1f, NavMesh.AllAreas) &&
                      NavMesh.CalculatePath(ha.position, hb.position, NavMesh.AllAreas, p) && p.status == NavMeshPathStatus.PathComplete;
        float len = 0f; var sbp = new StringBuilder();
        for (int i = 0; okPath && i < p.corners.Length; i++)
        {
            if (i > 0) len += Vector3.Distance(p.corners[i - 1], p.corners[i]);
            sbp.Append('(').Append(p.corners[i].x.ToString("F2", ci)).Append(", ").Append(p.corners[i].z.ToString("F2", ci)).Append(") ");
        }
        Status(okPath ? "참고 경로 " + len.ToString("F2", ci) + " m: " + sbp : "경고: 가상 맵에서 목표까지 경로가 이어지지 않음");

        if (cfg.diagnoseNoRobot)
        {
            if (agent.pathSender != null) agent.pathSender.remoteIp = "127.0.0.1";
            Status("진단 모드: 경로 전송 주소를 127.0.0.1 로 바꿈 — 로봇은 움직일 수 없음");
            File.WriteAllText(Path.Combine(dir, "GO"), "diagnose");
        }
        // M 키가 출발 전에 하는 검사와 같은 것 (결과만 기록)
        Status("출발 전 검사 | 목표까지 NavMesh 경로 막힘=" + Call("IsPathBlockedByNavMesh", robot.position, agent.target.position) +
               ", 충돌체 기준 막힘=" + Call("IsPathPhysicallyBlocked", robot.position, agent.target.position) +
               " | DecisionRequester=" + DescribeRequester() + " | driveByState=" + utm.driveByState);

        // 4) 출발 신호 대기
        Status("READY — real_run/GO 파일을 만들면 출발, STOP 파일을 만들면 종료");
        t0 = Time.realtimeSinceStartup;
        while (!Flag("GO") && !Flag("STOP") && Time.realtimeSinceStartup - t0 < cfg.waitGoSec) yield return null;
        if (!Flag("GO")) { Status("출발 신호 없이 종료"); Quit(0); yield break; }

        // 5) 주행 + 기록
        var rec = gameObject.AddComponent<ProactiveRunRecorder>();
        rec.outputDir = Path.Combine(dir, "frames");
        rec.fps = 8;
        rec.realTime = true;
        rec.Setup(agent);
        Vector3 startPos = robot.position;
        rec.BeginRun("unity_top", startPos, agent.target.position);
        var csv = new StringBuilder("t,x,z,yaw,busy,planning,real_following,cubes,dist_to_goal\n");
        Status("GO — 미션 시작");
        agent.StartNewMission();
        float tStart = Time.realtimeSinceStartup, lastLog = -1f, idleSince = -1f, lastDiag = -5f;
        int flips = 0;
        bool everBusy = false, stopped = false; string end = "timeout";
        while (Time.realtimeSinceStartup - tStart < cfg.missionTimeoutSec)
        {
            yield return null;
            float t = Time.realtimeSinceStartup - tStart;
            bool busy = agent.IsMissionBusy();
            // 경로 계산 중에는 로봇 상태값이 가상 로봇을 움직이면 안 된다 (StartMission 이 끄지만 직후에 한 번 다시 켜진다).
            // 켜져 있으면 가상 로봇이 제자리에 붙잡혀 경로가 만들어지지 않는다. 2026-11-24 진단으로 확인.
            if (agent.IsVirtualPathPlanning() && utm.driveByState)
            {
                flips++;
                utm.driveByState = false;
            }
            if (busy) { everBusy = true; idleSince = -1f; }
            if (t - lastLog >= 0.2f)
            {
                lastLog = t;
                Vector3 g = agent.target.position - robot.position; g.y = 0f;
                csv.Append(t.ToString("F2", ci)).Append(',').Append(robot.position.x.ToString("F3", ci)).Append(',')
                   .Append(robot.position.z.ToString("F3", ci)).Append(',').Append(Yaw(robot).ToString("F1", ci)).Append(',')
                   .Append(busy ? 1 : 0).Append(',').Append(agent.IsVirtualPathPlanning() ? 1 : 0).Append(',')
                   .Append(agent.IsRealPathFollowing() ? 1 : 0).Append(',').Append(CountCubes()).Append(',')
                   .Append(g.magnitude.ToString("F3", ci)).Append('\n');
            }
            if (t - lastDiag >= 5f)
            {
                lastDiag = t;
                var ccd = robot.GetComponent<CharacterController>();
                Status("진행 t=" + t.ToString("F0", ci) + "s | 가상 로봇 (" + robot.position.x.ToString("F2", ci) + ", " + robot.position.z.ToString("F2", ci) +
                       ") " + Yaw(robot).ToString("F0", ci) + "도 | busy=" + busy + " planning=" + agent.IsVirtualPathPlanning() +
                       " realFollowing=" + agent.IsRealPathFollowing() + " waitingStart=" + agent.IsWaitingRealGo1Start() +
                       " | driveByState=" + utm.driveByState + " steps=" + agent.StepCount + " cc=" + (ccd != null && ccd.enabled) +
                       " 계산중_driveByState켜진_프레임=" + flips);
            }
            if (Flag("STOP") && !stopped)
            {
                stopped = true;
                Status("STOP 신호 — 미션 정지(PATH_CANCEL)");
                agent.StopCurrentMissionFromPolicy();
                if (agent.pathSender != null) agent.pathSender.SendPathCancel();
                end = "stopped";
            }
            if (everBusy && !busy)
            {
                if (idleSince < 0f) idleSince = t;
                if (t - idleSince > 3f) { if (!stopped) end = "mission_finished"; break; }
            }
            if (!everBusy && t > 20f) { end = "mission_did_not_start"; break; }
        }
        rec.EndRun();
        File.WriteAllText(Path.Combine(dir, "run_log.csv"), csv.ToString(), new UTF8Encoding(false));
        Vector3 e = agent.target.position - robot.position; e.y = 0f;
        Status("종료: " + end + " | 걸린 시간 " + (Time.realtimeSinceStartup - tStart).ToString("F1", ci) + " s | 가상 로봇 (" +
               robot.position.x.ToString("F3", ci) + ", " + robot.position.z.ToString("F3", ci) + ") | 목표까지 " +
               e.magnitude.ToString("F2", ci) + " m (가상 로봇 기준)");
        yield return new WaitForSecondsRealtime(1f);
        Quit(0);
    }

    private string Call(string method, Vector3 a, Vector3 b)
    {
        try
        {
            MethodInfo m = typeof(GO1Agent).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public,
                                                      null, new[] { typeof(Vector3), typeof(Vector3) }, null);
            return m != null ? m.Invoke(agent, new object[] { a, b }).ToString() : "(없음)";
        }
        catch (Exception e) { return "오류:" + (e.InnerException != null ? e.InnerException.Message : e.Message); }
    }

    private string DescribeRequester()
    {
        var dr = agent.GetComponent<Unity.MLAgents.DecisionRequester>();
        return dr == null ? "없음" : (dr.enabled ? "켜짐(주기 " + dr.DecisionPeriod + ")" : "꺼짐");
    }

    private static Anchor360ObstacleReceiver FindActive360()
    {
        foreach (var r in FindObjectsByType<Anchor360ObstacleReceiver>(FindObjectsSortMode.None))
            if (r.isActiveAndEnabled && !r.loadFromFile) return r;
        return null;
    }

    private static int CountCubes()
    {
        GameObject root = GameObject.Find("Anchor360_Obstacles");
        return root != null ? root.transform.childCount : 0;
    }

    private static void Quit(int code)
    {
#if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(code);
#else
        Application.Quit(code);
#endif
    }
}
