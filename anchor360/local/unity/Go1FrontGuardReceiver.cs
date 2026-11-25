using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

/// <summary>
/// Go1 정면 카메라가 찾은 물체를 씬에 표시한다 (go1_front_guard.py → UDP 5012).
///
/// 색 구분: 360° 카메라 = 주황(Anchor360ObstacleReceiver), Go1 = 하늘색(이 스크립트).
///
/// 위치는 "가상 Go1 기준 오른쪽·앞 몇 m" 로 온다. 그래서 씬의 가상 Go1 이 실제 로봇과 같은 곳에
/// 있을 때만 큐브가 맞는 자리에 놓인다. 거리도 부정확하다(낮은 어안 카메라 한 대의 추정).
/// → 표시와 경고용이다. NavMesh 는 파지 않는다.
///
/// 씬을 고치지 않아도 Play 하면 자동으로 뜬다. 끄려면 보정 파일에 "go1GuardEnabled": false.
/// </summary>
public class Go1FrontGuardReceiver : MonoBehaviour
{
    public int listenPort = 5012;
    [Tooltip("이 로봇 이름의 UnityTeleopAndMirror 가 움직이는 가상 Go1 을 기준으로 삼는다. 보정 파일의 go1RobotId 가 우선.")]
    public string robotId = "GO1_A";
    public Color cubeColor = new Color(0.1f, 0.8f, 1f);
    public Color warnColor = new Color(1f, 0.1f, 0.1f);
    public Vector3 cubeSize = new Vector3(0.2f, 0.5f, 0.2f);
    [Tooltip("NavMesh 에서 파낼 영역을 큐브보다 넓히는(+)/줄이는(-) 값(m). 보정 파일의 navMeshPadding 이 우선.")]
    public float navMeshPadding = -0.1f;
    public float staleSec = 1.5f;
    public bool showBanner = true;
    [Tooltip("로봇에서 이 거리(m) 안의 검출만 표시한다. 보정 파일의 rangeGo1M 이 우선.")]
    public float detectRangeM = 1.5f;
    [Tooltip("정면 기준 좌우 표시 각도(도)")]
    public float halfAngleDeg = 60f;
    public Color rangeZoneColor = new Color(0.1f, 0.9f, 0.2f, 0.22f);
    GameObject rangeZone; float nextCfgRead;
    [Tooltip("Go1 이 찾은 물체도 NavMesh 에서 파낸다. 위치가 부정확하므로 가만히 있을 때만 판다.")]
    public bool addNavMeshObstacle = true;

    [Serializable] class Det { public string name; public float conf, right_m, forward_m, dist_m; public bool in_path; }
    [Serializable] class Packet { public string type, level, nearest_name; public float nearest_forward_m, video_age_s, warn_m, stop_m; public Det[] detections; }
    [Serializable] class Cfg
    {
        public string go1RobotId; public bool go1GuardEnabled = true; public float rangeGo1M = -1f; public float navMeshPadding = -99f;
        public bool go1GuardAsObstacle = false;   // true면 Go1이 본 물체를 트윈 장애물로 남겨 경로 재계획에 쓴다
        public float go1GuardKeepSec = 30f;       // 마지막으로 본 뒤 이 시간(초) 동안 트윈에 남긴다
    }

    // Go1 이 본 물체를 트윈 장애물로 남기는 모드 (보정 파일 go1GuardAsObstacle). 기본은 꺼짐 = 예전처럼 표시만.
    // 표시용 큐브는 시야에서 벗어나면 바로 사라지고 충돌체도 없어서 경로 검사에 잡히지 않는다.
    // 이 모드에서는 처음 본 자리에 충돌체 + Obstacle 태그/레이어 + NavMesh 파내기를 가진 큐브를 따로 두고,
    // 로봇이 고개를 돌려 안 보이게 돼도 keepSec 동안 유지한다. 그래야 주행 중 경로 교체가 흔들리지 않는다.
    [Header("Go1 검출을 트윈 장애물로 (보정 파일이 우선)")]
    public bool asObstacle = false;
    public float keepSec = 30f;
    [Tooltip("같은 물체로 보는 거리(m). 이 안에서 다시 보이면 새로 만들지 않는다.")]
    public float sameObjectDist = 0.4f;
    public Vector3 keptSize = new Vector3(0.3f, 0.5f, 0.3f);
    public Color keptColor = new Color(0.1f, 0.3f, 1f);
    class Kept { public GameObject go; public float lastSeen; public int seen; }
    readonly List<Kept> kept = new List<Kept>();
    bool updaterChecked;

    void Remember(Vector3 p)
    {
        foreach (var k in kept)
        {
            Vector3 d = k.go.transform.position - p; d.y = 0f;
            if (d.magnitude > sameObjectDist) continue;
            k.lastSeen = Time.unscaledTime;
            if (k.seen < 5)   // 처음 몇 번만 평균을 내 자리를 잡고, 그 뒤로는 고정한다
            {
                k.seen++;
                Vector3 q = Vector3.Lerp(k.go.transform.position, new Vector3(p.x, k.go.transform.position.y, p.z), 1f / k.seen);
                k.go.transform.position = q;
            }
            return;
        }
        var c = GameObject.CreatePrimitive(PrimitiveType.Cube);   // BoxCollider 유지: 경로 막힘 검사가 본다
        c.name = "Go1KeptObstacle";
        c.transform.SetParent(root.transform, true);
        c.transform.position = new Vector3(p.x, keptSize.y * 0.5f, p.z);
        c.transform.localScale = keptSize;
        c.GetComponent<Renderer>().material.color = keptColor;
        try { c.tag = "Obstacle"; } catch { Debug.LogWarning("[Go1Guard] Tag 'Obstacle' 없음"); }
        int layer = LayerMask.NameToLayer("Obstacle");
        if (layer >= 0) c.layer = layer;
        var nav = c.AddComponent<UnityEngine.AI.NavMeshObstacle>();
        nav.shape = UnityEngine.AI.NavMeshObstacleShape.Box;
        nav.size = new Vector3(Mathf.Max(0.1f, 1f + 2f * navMeshPadding / keptSize.x), 1f, Mathf.Max(0.1f, 1f + 2f * navMeshPadding / keptSize.z));
        nav.carving = true;
        nav.carveOnlyStationary = false;
        kept.Add(new Kept { go = c, lastSeen = Time.unscaledTime, seen = 1 });
        Debug.Log($"[Go1Guard] 트윈에 장애물 배치: ({p.x:F2}, {p.z:F2})");
    }

    void ExpireKept()
    {
        for (int i = kept.Count - 1; i >= 0; i--)
        {
            if (asObstacle && Time.unscaledTime - kept[i].lastSeen <= keepSec) continue;
            Destroy(kept[i].go);
            kept.RemoveAt(i);
        }
    }

    // 정지 없는 경로 교체 컴포넌트가 로봇에 없으면 붙인다 (이 모드를 켰을 때만)
    void EnsureUpdater()
    {
        if (updaterChecked) return;
        var agent = FindFirstObjectByType<GO1Agent>();
        if (agent == null) return;
        updaterChecked = true;
        if (agent.GetComponent<GO1ProactivePathUpdater>() == null)
        {
            agent.gameObject.AddComponent<GO1ProactivePathUpdater>();
            Debug.Log("[Go1Guard] GO1ProactivePathUpdater 를 '" + agent.name + "' 에 붙였습니다 (정지 없는 경로 교체).");
        }
    }

    UdpClient udp; Thread thread; volatile bool running;
    readonly object gate = new object(); string latest; float lastRecv = -999f;
    Packet cur; Transform robot; float nextRobotSearch;
    readonly List<GameObject> cubes = new List<GameObject>(); readonly List<TextMesh> labels = new List<TextMesh>();
    GameObject root; Font font;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Bootstrap()
    {
        if (FindFirstObjectByType<Go1FrontGuardReceiver>() != null) return;
        var cfg = ReadCfg();
        if (cfg != null && !cfg.go1GuardEnabled) return;
        var go = new GameObject("Go1FrontGuard");
        var r = go.AddComponent<Go1FrontGuardReceiver>();
        if (cfg != null && !string.IsNullOrEmpty(cfg.go1RobotId)) r.robotId = cfg.go1RobotId;
        DontDestroyOnLoad(go);
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
        root = new GameObject("Go1_FrontDetections");
        font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        try
        {
            udp = new UdpClient(new IPEndPoint(IPAddress.Any, listenPort));
            running = true;
            thread = new Thread(Loop) { IsBackground = true };
            thread.Start();
            Debug.Log($"[Go1Guard] UDP {listenPort} 수신 시작. 기준 로봇 {robotId}. Go1 검출 = 하늘색, 360° = 주황");
        }
        catch (Exception e) { Debug.LogWarning($"[Go1Guard] 포트 {listenPort} 열기 실패: {e.Message}"); }
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

    Transform FindRobot()
    {
        foreach (var utm in FindObjectsByType<UnityTeleopAndMirror>(FindObjectsSortMode.None))
        {
            if (utm.robotId != robotId) continue;
            if (utm.driver != null) return utm.driver.transform;
            if (utm.robotRoot != null) return utm.robotRoot;
        }
        return null;
    }

    void Update()
    {
        string s = null;
        lock (gate) { s = latest; latest = null; }
        if (s != null)
        {
            try { cur = JsonUtility.FromJson<Packet>(s); lastRecv = Time.unscaledTime; }
            catch (Exception e) { Debug.LogWarning($"[Go1Guard] 패킷 해석 실패: {e.Message}"); }
        }
        if (robot == null && Time.unscaledTime >= nextRobotSearch)
        {
            robot = FindRobot();
            nextRobotSearch = Time.unscaledTime + 2f;
        }

        if (Time.unscaledTime >= nextCfgRead)                 // 보정 파일의 범위 값을 2초마다 다시 읽는다
        {
            nextCfgRead = Time.unscaledTime + 2f;
            var cfg = ReadCfg();
            if (cfg != null && cfg.rangeGo1M > 0f) detectRangeM = cfg.rangeGo1M;
            if (cfg != null && cfg.navMeshPadding > -90f) navMeshPadding = cfg.navMeshPadding;
            if (cfg != null) { asObstacle = cfg.go1GuardAsObstacle; keepSec = cfg.go1GuardKeepSec; }
            foreach (var cb in cubes)
            {
                var nv = cb.GetComponent<UnityEngine.AI.NavMeshObstacle>();
                if (nv != null) nv.size = new Vector3(Mathf.Max(0.1f, 1f + 2f * navMeshPadding / cubeSize.x), 1f, Mathf.Max(0.1f, 1f + 2f * navMeshPadding / cubeSize.z));
            }
        }
        // 탐지 범위를 로봇 앞 바닥에 초록색 부채꼴로 그린다
        if (robot != null)
        {
            if (rangeZone == null) rangeZone = RangeZone.Make("RangeGo1", rangeZoneColor);
            // 이 Go1 모델의 앞은 transform.forward 가 아니라 -transform.right 다 (GO1Agent 와 같은 규약).
            // forward 를 쓰면 탐지 범위와 큐브가 로봇 오른쪽으로 90도 돌아가 그려진다. 2026-11-24 실주행 녹화에서 확인.
            Vector3 f0 = -robot.right; f0.y = 0f; f0 = f0.sqrMagnitude > 1e-6f ? f0.normalized : Vector3.forward;
            rangeZone.transform.SetPositionAndRotation(new Vector3(robot.position.x, 0.03f, robot.position.z), Quaternion.LookRotation(f0));
            RangeZone.Set(rangeZone, detectRangeM, halfAngleDeg);
        }

        if (asObstacle) EnsureUpdater();
        ExpireKept();
        bool fresh = cur != null && Time.unscaledTime - lastRecv <= staleSec;      // 오래된 것은 최신인 척 두지 않는다
        // 범위(초록색) 안의 검출만 남긴다
        var inRange = new List<Det>();
        if (fresh && robot != null && cur.detections != null)
            foreach (var dd in cur.detections)
                if (dd.dist_m <= detectRangeM && Mathf.Abs(Mathf.Atan2(dd.right_m, dd.forward_m)) * Mathf.Rad2Deg <= halfAngleDeg) inRange.Add(dd);
        int n = inRange.Count;
        while (cubes.Count < n) AddCube();
        for (int i = 0; i < cubes.Count; i++)
        {
            bool on = i < n;
            if (cubes[i].activeSelf != on) cubes[i].SetActive(on);
            if (!on) continue;
            Det d = inRange[i];
            Vector3 flat = -robot.right; flat.y = 0f; flat = flat.sqrMagnitude > 1e-6f ? flat.normalized : Vector3.forward;
            Vector3 right = new Vector3(flat.z, 0f, -flat.x);
            Vector3 p = robot.position + flat * d.forward_m + right * d.right_m;
            p.y = cubeSize.y * 0.5f;
            if (asObstacle) Remember(p);
            // 조금 흔들린 정도면 그대로 둔다(움직일 때마다 NavMesh 를 다시 파므로)
            if ((cubes[i].transform.position - p).sqrMagnitude > 0.1f * 0.1f)
                cubes[i].transform.SetPositionAndRotation(p, Quaternion.LookRotation(flat));
            bool near = d.in_path && cur.warn_m > 0f && d.forward_m <= cur.warn_m;
            cubes[i].GetComponent<Renderer>().material.color = near ? warnColor : cubeColor;
            labels[i].text = $"Go1: {d.name} {d.dist_m:F1}m";
            labels[i].color = near ? warnColor : cubeColor;
            // 사람이면 상자 대신 사람 모형 (글자는 머리 위로 올린다)
            PersonVisual.Sync(cubes[i], d.name, 0f, near ? warnColor : cubeColor);
            bool person = PersonVisual.IsPerson(d.name);
            float labY = person ? (1.95f - cubeSize.y * 0.5f) / cubeSize.y : 0.5f + 0.15f / cubeSize.y;
            if (Mathf.Abs(labels[i].transform.localPosition.y - labY) > 1e-3f) labels[i].transform.localPosition = new Vector3(0f, labY, 0f);
        }
    }

    void AddCube()
    {
        var c = GameObject.CreatePrimitive(PrimitiveType.Cube);
        c.name = "Go1Detection";
        Destroy(c.GetComponent<Collider>());
        if (addNavMeshObstacle)
        {
            var nav = c.AddComponent<UnityEngine.AI.NavMeshObstacle>();
            nav.shape = UnityEngine.AI.NavMeshObstacleShape.Box;
            nav.center = Vector3.zero;
            nav.size = new Vector3(Mathf.Max(0.1f, 1f + 2f * navMeshPadding / cubeSize.x), 1f, Mathf.Max(0.1f, 1f + 2f * navMeshPadding / cubeSize.z));
            nav.carving = true;
            nav.carveOnlyStationary = true;       // 추정 위치가 흔들리는 동안은 파지 않는다
            nav.carvingMoveThreshold = 0.15f;
            nav.carvingTimeToStationary = 0.5f;
        }
        c.transform.SetParent(root.transform, true);
        c.transform.localScale = cubeSize;
        var lab = new GameObject("Label");
        lab.transform.SetParent(c.transform, false);
        lab.transform.localPosition = new Vector3(0f, 0.5f + 0.15f / cubeSize.y, 0f);
        lab.transform.localScale = new Vector3(1f / cubeSize.x, 1f / cubeSize.y, 1f / cubeSize.z);
        var tm = lab.AddComponent<TextMesh>();
        tm.font = font; tm.fontSize = 48; tm.characterSize = 0.03f;
        tm.anchor = TextAnchor.LowerCenter; tm.alignment = TextAlignment.Center;
        lab.GetComponent<MeshRenderer>().sharedMaterial = font.material;
        lab.AddComponent<FaceCameraLabel>().yawOnly = false;
        cubes.Add(c); labels.Add(tm);
    }

    void OnGUI()
    {
        if (!showBanner) return;
        bool fresh = cur != null && Time.unscaledTime - lastRecv <= staleSec;
        string text; Color col;
        if (!fresh) { text = "Go1 정면: 수신 없음"; col = Color.gray; }
        else if (cur.level == "stop") { text = $"Go1 정면: 정지 권고 — {cur.nearest_name} {cur.nearest_forward_m:F1}m"; col = Color.red; }
        else if (cur.level == "warn") { text = $"Go1 정면: 주의 — {cur.nearest_name} {cur.nearest_forward_m:F1}m"; col = new Color(1f, 0.7f, 0f); }
        else if (cur.level == "no_video") { text = "Go1 정면: 영상 없음"; col = Color.gray; }
        else { text = "Go1 정면: 앞 비어 있음"; col = new Color(0.2f, 0.8f, 0.2f); }
        if (robot == null && fresh) text += $"  (가상 로봇 {robotId} 못 찾음 — 큐브 표시 안 함)";
        var style = new GUIStyle(GUI.skin.box) { fontSize = 16, alignment = TextAnchor.MiddleLeft };
        style.normal.textColor = Color.white;
        Color old = GUI.backgroundColor; GUI.backgroundColor = col;
        GUI.Box(new Rect(10, 10, 560, 30), "  " + text + "   |  주황=360°  하늘색=Go1", style);
        GUI.backgroundColor = old;
    }

    void OnDestroy()
    {
        running = false;
        try { udp?.Close(); } catch { }
    }
}
