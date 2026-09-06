using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

/// <summary>
/// 360° 고정 카메라(서버)가 UDP로 보내는 사각지대 장애물 JSON을 수신하여
/// Anchor360 기준으로 큐브를 스폰한다. 기존 Go1ObstacleJsonReceiver(포트 5009)와 완전히 별개.
///
/// 사용법:
///  1) 빈 GameObject "Anchor360"을 만들고 실제 360 카메라의 가로 위치에 놓는다.
///     - +Z(파란 화살표)를 맵의 GO1 주행 방향에 맞춘다.  높이(y)는 상관없음(바닥으로 강제됨).
///  2) 이 컴포넌트를 Anchor360에 붙인다. (anchorTransform 비우면 자기 자신 사용)
///  3) listenPort=5010, obstaclePrefab(선택) 지정.
///  4) 큐브가 실제 장애물과 어긋나면 Inspector에서 yawOffsetDeg / invertX / distanceScale 조정.
/// </summary>
public class Anchor360ObstacleReceiver : MonoBehaviour
{
    [Header("Network")]
    public int listenPort = 5010;                 // 기존 5009와 다른 포트

    [Header("Anchor")]
    [Tooltip("360 카메라 기준 오브젝트. 비우면 이 컴포넌트가 붙은 오브젝트를 사용.")]
    public Transform anchorTransform;

    [Header("Calibration (실측 보정용 손잡이)")]
    [Tooltip("큐브 전체가 회전돼 보이면 조정 (도).")]
    public float yawOffsetDeg = 0f;
    [Tooltip("좌우가 뒤집혀 보이면 체크.")]
    public bool invertX = false;
    [Tooltip("거리가 멀거나 가깝게 보이면 조정 (가로거리 배율).")]
    public float distanceScale = 1.0f;

    [Header("Floor")]
    [Tooltip("장애물은 바닥에 있으므로 큐브 높이를 이 y로 강제한다(맵 바닥 높이). 보통 0.")]
    public float floorWorldY = 0f;

    [Header("Cube")]
    public GameObject obstaclePrefab;             // 비우면 기본 Cube 생성
    public float minCubeSize = 0.15f;
    public float maxCubeSize = 3.0f;
    public float defaultCubeSize = 0.4f;          // size 없을 때
    [Tooltip("bbox 유래 크기가 커서 여유를 주고 싶으면 배율.")]
    public float sizeMultiplier = 1.0f;

    [Header("Tag / Layer (기존과 동일하게 NavMesh/ML-Agent가 인식하도록)")]
    public bool assignObstacleTagAndLayer = true;
    public string obstacleTagName = "Obstacle";
    public string obstacleLayerName = "Obstacle";

    [Header("Debug")]
    public bool printReceivedJson = false;

    // ---- JSON 구조 (서버 detect_send_3b2.py의 스키마) ----
    [Serializable] public class Pos3D { public float x, y, z; }
    [Serializable] public class Size  { public float w, h, d; }
    [Serializable]
    public class Det360
    {
        public int id;
        public string name;
        public string group;
        public Pos3D pos3d;
        public float dist_m;
        public Size size;
        public int[] bbox_xyxy;
        public bool ground_clipped;
    }
    [Serializable]
    public class Anchor360Packet
    {
        public string timestamp;
        public string camera_id;
        public string frame;
        public Det360[] detections;
    }

    // ---- UDP ----
    private UdpClient udp;
    private Thread rxThread;
    private volatile bool running = false;
    private readonly object lockObj = new object();
    private string latestJson = null;            // 최신 패킷만 유지(스냅샷)

    // ---- 스폰된 큐브 ----
    private readonly List<GameObject> spawned = new List<GameObject>();
    private GameObject root;

    // 폐루프 인과 타임라인용: 탐지 패킷이 트윈에 도달한 순간(obstacle_detected 이벤트)을 기록한다.
    private RealGo1CaseStudyLogger caseStudyLogger;
    private bool caseStudyLoggerSearched = false;
    private string lastLoggedPacketTimestamp = null;

    void Start()
    {
        if (anchorTransform == null) anchorTransform = transform;
        root = new GameObject("Anchor360_Obstacles");
        StartReceiver();
    }

    void StartReceiver()
    {
        try
        {
            udp = new UdpClient(listenPort);
            running = true;
            rxThread = new Thread(ReceiveLoop) { IsBackground = true };
            rxThread.Start();
            Debug.Log($"[Anchor360] UDP {listenPort} 수신 시작");
        }
        catch (Exception e)
        {
            Debug.LogError($"[Anchor360] 포트 {listenPort} 열기 실패: {e.Message}");
        }
    }

    void ReceiveLoop()
    {
        IPEndPoint any = new IPEndPoint(IPAddress.Any, 0);
        while (running)
        {
            try
            {
                byte[] data = udp.Receive(ref any);   // blocking
                string s = Encoding.UTF8.GetString(data);
                lock (lockObj) { latestJson = s; }    // 최신만 보관
            }
            catch (Exception) { /* 소켓 종료 시 무시 */ }
        }
    }

    void Update()
    {
        string json = null;
        lock (lockObj) { if (latestJson != null) { json = latestJson; latestJson = null; } }
        if (json == null) return;

        if (printReceivedJson) Debug.Log("[Anchor360] RX: " + json);

        Anchor360Packet pkt;
        try { pkt = JsonUtility.FromJson<Anchor360Packet>(json); }
        catch (Exception e) { Debug.LogWarning("[Anchor360] JSON 파싱 실패: " + e.Message); return; }
        if (pkt == null || pkt.detections == null) return;

        RebuildObstacles(pkt);   // 스냅샷: 이전 것 제거 후 새로 생성
    }

    void RebuildObstacles(Anchor360Packet pkt)
    {
        // 폐루프 타임라인: 새 탐지 패킷(새 timestamp)이 트윈에 도달한 순간을 기록.
        if (pkt.detections.Length > 0 &&
            !string.IsNullOrEmpty(pkt.timestamp) &&
            pkt.timestamp != lastLoggedPacketTimestamp)
        {
            lastLoggedPacketTimestamp = pkt.timestamp;

            if (!caseStudyLoggerSearched)
            {
                caseStudyLoggerSearched = true;
                caseStudyLogger = FindFirstObjectByType<RealGo1CaseStudyLogger>();
            }

            caseStudyLogger?.LogObstacleDetected(
                Vector3.zero,
                "anchor360:" + (pkt.camera_id ?? "unknown"),
                pkt.timestamp,
                pkt.detections.Length);
        }

        // 이전 360 큐브 전부 제거(스냅샷 방식 → 사라진 장애물 자동 제거)
        foreach (var go in spawned) if (go != null) Destroy(go);
        spawned.Clear();

        Quaternion yawFix = Quaternion.Euler(0f, yawOffsetDeg, 0f);

        foreach (var det in pkt.detections)
        {
            if (det.pos3d == null) continue;

            // anchor 로컬 좌표(가로만 사용). y는 뒤에서 바닥으로 강제.
            float lx = det.pos3d.x * (invertX ? -1f : 1f) * distanceScale;
            float lz = det.pos3d.z * distanceScale;
            Vector3 local = yawFix * new Vector3(lx, 0f, lz);

            Vector3 world = anchorTransform.TransformPoint(local);

            // 크기
            Vector3 scale = ComputeScale(det.size);
            // 바닥에 세우기: 높이는 맵 바닥으로 강제, 큐브 중심은 절반 위로
            Vector3 pos = new Vector3(world.x, floorWorldY + scale.y * 0.5f, world.z);

            GameObject obj = (obstaclePrefab != null)
                ? Instantiate(obstaclePrefab)
                : GameObject.CreatePrimitive(PrimitiveType.Cube);
            obj.name = $"Obs360_{det.name}_{det.id}";
            obj.transform.SetParent(root.transform, true);
            obj.transform.position = pos;
            obj.transform.localScale = scale;
            if (obj.GetComponent<Collider>() == null) obj.AddComponent<BoxCollider>();
            ApplyTagAndLayer(obj);

            spawned.Add(obj);
        }
    }

    Vector3 ComputeScale(Size s)
    {
        float w = defaultCubeSize, h = defaultCubeSize, d = defaultCubeSize;
        if (s != null && s.w > 0f) { w = s.w; h = (s.h > 0f ? s.h : s.w); d = (s.d > 0f ? s.d : s.w); }
        w *= sizeMultiplier; h *= sizeMultiplier; d *= sizeMultiplier;
        w = Mathf.Clamp(w, minCubeSize, maxCubeSize);
        h = Mathf.Clamp(h, minCubeSize, maxCubeSize);
        d = Mathf.Clamp(d, minCubeSize, maxCubeSize);
        return new Vector3(w, h, d);
    }

    void ApplyTagAndLayer(GameObject obj)
    {
        if (!assignObstacleTagAndLayer) return;
        try { if (!string.IsNullOrEmpty(obstacleTagName)) obj.tag = obstacleTagName; }
        catch { Debug.LogWarning($"[Anchor360] Tag '{obstacleTagName}' 없음. Tags & Layers에 추가 필요."); }
        if (!string.IsNullOrEmpty(obstacleLayerName))
        {
            int layer = LayerMask.NameToLayer(obstacleLayerName);
            if (layer >= 0) obj.layer = layer;
            else Debug.LogWarning($"[Anchor360] Layer '{obstacleLayerName}' 없음. Tags & Layers에 추가 필요.");
        }
    }

    void OnDestroy()  { StopReceiver(); }
    void OnApplicationQuit() { StopReceiver(); }
    void StopReceiver()
    {
        running = false;
        try { udp?.Close(); } catch { }
        try { rxThread?.Join(200); } catch { }
    }
}
