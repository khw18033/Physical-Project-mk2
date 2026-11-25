using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

/// <summary>
/// 360° 카메라가 본 로봇 등 위 ArUco 마커(anchor360_marker_live.py → UDP 5013)로 가상 Go1 을 실제 위치·방향에 맞춘다.
///
/// 좌표 변환은 장애물 검출과 같은 보정값(Anchor360ObstacleReceiver 의 앵커 위치, yawOffsetDeg, distanceScale, invertX)을 쓴다.
/// 그래서 장애물이 맞는 자리에 놓이도록 보정돼 있으면 로봇도 같은 정확도로 맞는다.
///
/// 맞추는 방식
///  - 로봇 SDK 상태를 받고 있으면: 추측 항법의 기준점을 옮긴다(UnityTeleopAndMirror.RebaseStateFollowToCurrentVirtualPose).
///    마커가 안 보이게 돼도 그 자리에서 추측 항법이 이어지고, 순간이동이 없다.
///  - SDK 상태가 없으면(로봇 미연결): 가상 Go1 의 위치·방향을 직접 옮긴다.
///
/// 처음에는 여러 장을 모아 평균으로 한 번에 맞추고(초기 정합), 그 뒤로는 차이의 일부만 반영한다(주행 중 보정).
///
/// 씬을 고치지 않아도 보정 파일(anchor360_calib.json)에 "robotMarkerEnabled": true 가 있으면 Play 때 자동으로 뜬다.
/// </summary>
public class Robot360MarkerReceiver : MonoBehaviour
{
    public int listenPort = 5013;
    public int markerId = 7;
    [Tooltip("이 로봇 이름의 UnityTeleopAndMirror 가 움직이는 가상 Go1 을 맞춘다.")]
    public string robotId = "GO1_A";
    [Tooltip("마커 중심이 로봇 기준점보다 앞(+)/뒤(-)로 떨어진 거리(m).")]
    public float markerForwardOffsetM = 0f;
    [Tooltip("처음 맞출 때 모으는 장 수.")]
    public int initialSamples = 8;
    [Tooltip("처음 맞춘 뒤, 한 번 받을 때마다 차이의 이 비율만큼만 옮긴다 (0 = 처음 한 번만 맞춤).")]
    [Range(0f, 1f)] public float followGain = 0.2f;
    [Tooltip("처음 맞춘 뒤 이보다 크게 어긋난 값(m)은 오인식으로 보고 버린다.")]
    public float maxJumpM = 1.0f;
    [Tooltip("이 값보다 작은 차이(m / 도)는 건드리지 않는다.")]
    public float deadbandM = 0.01f;
    public float deadbandDeg = 0.5f;
    public bool logEveryFix = false;

    [Serializable] class Marker { public int id; public float x, z, yaw_deg, side_px; }
    [Serializable] class Packet { public string type; public float frame_age_s; public Marker[] markers; }
    [Serializable] class Cfg { public bool robotMarkerEnabled = false; public int robotMarkerId = -1; public string go1RobotId; public float robotMarkerForwardOffsetM = 0f; }

    public bool Aligned { get; private set; }
    public int Fixes { get; private set; }
    public Vector3 LastWorldPos { get; private set; }
    public float LastWorldYawDeg { get; private set; }
    public Vector3 PoseBeforeAlign { get; private set; }
    public float YawBeforeAlign { get; private set; }

    UdpClient udp; Thread thread; volatile bool running;
    readonly object gate = new object(); string latest;
    Anchor360ObstacleReceiver calib; UnityTeleopAndMirror utm; Transform robot;
    readonly List<Vector3> bufPos = new List<Vector3>(); readonly List<float> bufYaw = new List<float>();
    float nextSearch;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Bootstrap()
    {
        if (FindFirstObjectByType<Robot360MarkerReceiver>() != null) return;
        Cfg cfg = ReadCfg();
        if (cfg == null || !cfg.robotMarkerEnabled) return;
        var r = new GameObject("Robot360Marker").AddComponent<Robot360MarkerReceiver>();
        if (cfg.robotMarkerId >= 0) r.markerId = cfg.robotMarkerId;
        if (!string.IsNullOrEmpty(cfg.go1RobotId)) r.robotId = cfg.go1RobotId;
        r.markerForwardOffsetM = cfg.robotMarkerForwardOffsetM;
        DontDestroyOnLoad(r.gameObject);
    }

    static Cfg ReadCfg()
    {
        try
        {
            string p = Path.Combine(Application.streamingAssetsPath, "anchor360_calib.json");
            return File.Exists(p) ? JsonUtility.FromJson<Cfg>(File.ReadAllText(p, Encoding.UTF8)) : null;
        }
        catch { return null; }
    }

    void Start()
    {
        try
        {
            udp = new UdpClient(new IPEndPoint(IPAddress.Any, listenPort));
            running = true;
            thread = new Thread(Loop) { IsBackground = true };
            thread.Start();
            Debug.Log($"[Robot360Marker] UDP {listenPort} 수신 시작. 마커 ID {markerId} → 가상 로봇 {robotId}");
        }
        catch (Exception e) { Debug.LogWarning($"[Robot360Marker] 포트 {listenPort} 열기 실패: {e.Message}"); }
    }

    void Loop()
    {
        var ep = new IPEndPoint(IPAddress.Any, 0);
        while (running)
        {
            try { string s = Encoding.UTF8.GetString(udp.Receive(ref ep)); lock (gate) latest = s; }
            catch { if (!running) break; }
        }
    }

    void FindRefs()
    {
        if (Time.unscaledTime < nextSearch) return;
        nextSearch = Time.unscaledTime + 2f;
        if (calib == null)
            foreach (var r in FindObjectsByType<Anchor360ObstacleReceiver>(FindObjectsSortMode.None))
                if (r.isActiveAndEnabled && !r.loadFromFile) { calib = r; break; }
        if (robot == null)
            foreach (var u in FindObjectsByType<UnityTeleopAndMirror>(FindObjectsSortMode.None))
            {
                if (u.robotId != robotId) continue;
                utm = u;
                robot = u.driver != null ? u.driver.transform : u.robotRoot;
                break;
            }
    }

    /// <summary>카메라 기준 좌표(검출과 같은 규약) → 맵 좌표와 방향(도, 위에서 보아 시계방향 +, 0 = 맵 +Z).</summary>
    public bool ToWorld(float x, float z, float yawDeg, out Vector3 world, out float worldYaw)
    {
        world = Vector3.zero; worldYaw = 0f;
        if (calib == null) return false;
        Transform a = calib.anchorTransform != null ? calib.anchorTransform : calib.transform;
        float lx = x * (calib.invertX ? -1f : 1f) * calib.distanceScale, lz = z * calib.distanceScale;
        world = a.TransformPoint(Quaternion.Euler(0f, calib.yawOffsetDeg, 0f) * new Vector3(lx, 0f, lz));
        worldYaw = Mathf.Repeat(a.eulerAngles.y + calib.yawOffsetDeg + (calib.invertX ? -yawDeg : yawDeg), 360f);
        return true;
    }

    void Update()
    {
        FindRefs();
        string s = null;
        lock (gate) { s = latest; latest = null; }
        if (s == null || calib == null || robot == null) return;

        Packet p;
        try { p = JsonUtility.FromJson<Packet>(s); } catch { return; }
        if (p == null || p.markers == null) return;
        Marker m = null;
        foreach (var k in p.markers) if (k.id == markerId) { m = k; break; }
        if (m == null) return;
        if (!ToWorld(m.x, m.z, m.yaw_deg, out Vector3 w, out float yaw)) return;

        // 마커 중심 → 로봇 기준점
        Vector3 fwd = Quaternion.Euler(0f, yaw, 0f) * Vector3.forward;
        w -= fwd * markerForwardOffsetM;
        w.y = robot.position.y;
        LastWorldPos = w; LastWorldYawDeg = yaw; Fixes++;
        if (logEveryFix) Debug.Log($"[Robot360Marker] fix ({w.x:F3}, {w.z:F3}) yaw {yaw:F1}");

        if (!Aligned)
        {
            bufPos.Add(w); bufYaw.Add(yaw);
            if (bufPos.Count < Mathf.Max(1, initialSamples)) return;
            Vector3 mean = Vector3.zero; float sx = 0f, cx = 0f;
            for (int i = 0; i < bufPos.Count; i++)
            {
                mean += bufPos[i];
                sx += Mathf.Sin(bufYaw[i] * Mathf.Deg2Rad); cx += Mathf.Cos(bufYaw[i] * Mathf.Deg2Rad);
            }
            mean /= bufPos.Count;
            float meanYaw = Mathf.Repeat(Mathf.Atan2(sx, cx) * Mathf.Rad2Deg, 360f);
            PoseBeforeAlign = robot.position; YawBeforeAlign = RobotYaw();
            Apply(mean, meanYaw, "initial");
            Aligned = true;
            Vector3 d = mean - PoseBeforeAlign; d.y = 0f;
            Debug.Log($"[Robot360Marker] 초기 정합 완료 | 전 ({PoseBeforeAlign.x:F3}, {PoseBeforeAlign.z:F3}) yaw {YawBeforeAlign:F1}" +
                      $" → 후 ({mean.x:F3}, {mean.z:F3}) yaw {meanYaw:F1} | 옮긴 거리 {d.magnitude * 100f:F1} cm, " +
                      $"돌린 각 {Mathf.DeltaAngle(YawBeforeAlign, meanYaw):F1}도 ({bufPos.Count}장 평균)");
            return;
        }

        if (followGain <= 0f) return;
        Vector3 cur = robot.position;
        Vector3 err = w - cur; err.y = 0f;
        if (err.magnitude > maxJumpM) return;                       // 오인식
        float yawErr = Mathf.DeltaAngle(RobotYaw(), yaw);
        if (err.magnitude < deadbandM && Mathf.Abs(yawErr) < deadbandDeg) return;
        Apply(cur + err * followGain, RobotYaw() + yawErr * followGain, "follow");
    }

    // 가상 Go1 의 진행 방향(전진축 = -transform.right)을 맵 방위로
    float RobotYaw()
    {
        Vector3 f = -robot.right; f.y = 0f;
        return Mathf.Repeat(Mathf.Atan2(f.x, f.z) * Mathf.Rad2Deg, 360f);
    }

    void Apply(Vector3 pos, float yawDeg, string reason)
    {
        // 진행 방향이 yawDeg 가 되도록: 전진축이 -X 이므로 +90도
        Quaternion rot = Quaternion.Euler(0f, yawDeg + 90f, 0f);
        pos.y = robot.position.y;
        bool done = false;
        if (utm != null && utm.isActiveAndEnabled)
        {
            // 방향 먼저: 로봇 상태값이 가상 로봇의 방향을 계속 덮어쓰므로, Z 키와 같은 정식 yaw 정렬로 기준을 옮긴다.
            // (transform 만 돌려 놓으면 다음 상태 패킷에서 원래 방향으로 돌아간다)
            try { utm.AlignVirtualYawToExternal(yawDeg + 90f); }
            catch (Exception e) { Debug.LogWarning("[Robot360Marker] yaw 정렬 실패: " + e.Message); }
            try { done = utm.RebaseStateFollowToCurrentVirtualPose(pos, rot, "marker360-" + reason); }
            catch (Exception e) { Debug.LogWarning("[Robot360Marker] 기준점 옮기기 실패: " + e.Message); }
        }
        if (done) return;
        // SDK 상태가 없으면 직접 옮긴다 (CharacterController 는 켜진 채로 transform 을 바꾸면 되돌린다)
        var cc = robot.GetComponent<CharacterController>();
        bool was = cc != null && cc.enabled;
        if (was) cc.enabled = false;
        robot.SetPositionAndRotation(pos, rot);
        if (was) cc.enabled = true;
    }

    void OnDestroy()
    {
        running = false;
        try { udp?.Close(); } catch { }
    }
}
