using System;
using System.Collections.Generic;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

public class GO1LocalPathUdpSender : MonoBehaviour
{
    [Header("References")]
    public NavMeshAgent agent;

    [Tooltip("GO1 시작 기준 로컬 프레임을 잡을 기준 Transform. 보통 go1 루트")]
    public Transform localFrameRoot;

    [Tooltip("좌표계 변환은 이 컴포넌트 한 곳에서만 관리합니다.")]
    public GO1CoordinateMapper coordinateMapper;

    [Header("UDP Target")]
    public string remoteIp = "127.0.0.1";
    public int remotePort = 15110;

    [Header("Path Meta")]
    public int pathId = 1;
    [Tooltip("전송할 경로의 mode 값 (SDK/로봇 쪽에서 해석하는 모드 필드)")]
    public int pathMode = 0;

    [Tooltip("첫 번째 포인트를 (0,0)으로 강제")]
    public bool forceFirstPointAsOrigin = true;

    [Tooltip("모든 waypoint에 yaw를 계산해서 넣기. useYawOnlyAtFinalPoint가 켜져 있으면 마지막 점에만 적용됩니다.")]
    public bool useYawForAllPoints = true;

    [Tooltip("마지막 점 yaw를 마지막 segment 방향으로 설정")]
    public bool useLastSegmentYawForFinalPoint = true;

    [Header("Tolerance / Speed Meta")]
    public float positionTolerance = 0.10f;
    public float yawToleranceDeg = 8.0f;
    public float defaultSpeed = 0.15f;

    [Header("Yaw Stabilization")]
    [Tooltip("도리도리 방지: 중간 waypoint에서는 yaw를 강제하지 않고, 마지막 점에서만 최종 yaw를 맞춘다.")]
    public bool useYawOnlyAtFinalPoint = true;

    [Tooltip("이보다 짧은 segment에서 계산된 yaw는 노이즈로 보고 무시한다.")]
    public float minYawSegmentLength = 0.15f;

    [Header("Debug")]
    public bool printJson = true;
    public bool printSendLog = true;
    public bool printDebugLocalPoints = true;

    [Header("Sent Path Visualizer")]
    public bool showSentPathLine = true;
    public Color sentPathLineColor = Color.yellow;
    public float sentPathLineWidth = 0.08f;
    public float sentPathLineHeightOffset = 0.08f;

    private UdpClient _udp;
    private LineRenderer _sentPathLine;

    private bool _startPoseCaptured = false;
    private Vector3 _startWorldPos;
    private Quaternion _startWorldRot;

    [Serializable]
    public class StartPose
    {
        public float x;
        public float z;
        public float yaw_deg;
    }

    [Serializable]
    public class PathPoint
    {
        public int index;
        public float x;
        public float z;
        public float yaw_deg;
        public bool use_yaw;
    }

    [Serializable]
    public class PathMessage
    {
        public string type;
        public string frame;
        public int mode;
        public int path_id;
        public StartPose start_pose;
        public int point_count;
        public float position_tolerance;
        public float yaw_tolerance_deg;
        public float default_speed;
        public List<PathPoint> points;
    }

    private GO1CoordinateMapper Mapper
    {
        get
        {
            if (coordinateMapper == null)
                coordinateMapper = GetComponent<GO1CoordinateMapper>();
            if (coordinateMapper == null && localFrameRoot != null)
                coordinateMapper = localFrameRoot.GetComponent<GO1CoordinateMapper>();
            if (coordinateMapper == null)
                coordinateMapper = FindFirstObjectByType<GO1CoordinateMapper>();
            if (coordinateMapper == null)
                coordinateMapper = gameObject.AddComponent<GO1CoordinateMapper>();
            return coordinateMapper;
        }
    }

    private void Awake()
    {
        if (agent == null)
            agent = GetComponent<NavMeshAgent>();

        if (localFrameRoot == null)
            localFrameRoot = transform;

        _ = Mapper;
        _udp = new UdpClient();

        InitSentPathLineRenderer();
    }

    private void OnDestroy()
    {
        try { _udp?.Close(); }
        catch { }
    }

    [ContextMenu("Capture Start Pose From Root")]
    public void CaptureStartPoseFromRoot()
    {
        if (localFrameRoot == null)
        {
            Debug.LogWarning("[GO1LocalPathUdpSender] localFrameRoot가 없습니다.");
            return;
        }

        CaptureStartPose(localFrameRoot.position, localFrameRoot.rotation);
    }

    public void CaptureStartPose(Vector3 worldPos, Quaternion worldRot)
    {
        _startWorldPos = worldPos;
        _startWorldRot = worldRot;
        _startPoseCaptured = true;

        Debug.Log(
            $"[GO1LocalPathUdpSender] Start pose captured | " +
            $"worldPos={_startWorldPos} worldYaw={_startWorldRot.eulerAngles.y:F2}"
        );
    }

    [ContextMenu("Send Current Agent Path")]
    public void SendCurrentAgentPath()
    {
        if (agent == null)
        {
            Debug.LogWarning("[GO1LocalPathUdpSender] agent가 없습니다.");
            return;
        }

        if (agent.path == null || agent.path.corners == null ||
            agent.path.corners.Length == 0)
        {
            Debug.LogWarning("[GO1LocalPathUdpSender] 현재 agent.path.corners가 없습니다.");
            return;
        }

        if (!_startPoseCaptured)
            CaptureStartPoseFromRoot();

        SendPathFromCorners(agent.path.corners);
    }

    public void SendPathFromCorners(Vector3[] worldCorners)
    {
        if (worldCorners == null || worldCorners.Length == 0)
        {
            Debug.LogWarning("[GO1LocalPathUdpSender] 보낼 worldCorners가 없습니다.");
            return;
        }

        if (!_startPoseCaptured)
        {
            Debug.LogWarning("[GO1LocalPathUdpSender] start pose가 캡처되지 않았습니다.");
            return;
        }

        DrawSentPathLine(worldCorners);

        PathMessage msg = BuildMessage(worldCorners);
        string json = JsonUtility.ToJson(msg, true);

        if (printJson)
            Debug.Log("[GO1LocalPathUdpSender] JSON:\n" + json);

        byte[] data = Encoding.UTF8.GetBytes(json);
        const int maxChunk = 3900;

        try
        {
            if (data.Length <= maxChunk)
            {
                _udp.Send(data, data.Length, remoteIp, remotePort);
                if (printSendLog)
                    Debug.Log($"[GO1LocalPathUdpSender] sent {data.Length} bytes to {remoteIp}:{remotePort}");
            }
            else
            {
                int totalChunks = Mathf.CeilToInt((float)data.Length / maxChunk);
                for (int c = 0; c < totalChunks; c++)
                {
                    int offset = c * maxChunk;
                    int size = Mathf.Min(maxChunk, data.Length - offset);
                    string header = $"CHUNK {pathId}/{totalChunks}/{c} ";
                    byte[] headerBytes = Encoding.UTF8.GetBytes(header);
                    byte[] chunk = new byte[headerBytes.Length + size];
                    Array.Copy(headerBytes, 0, chunk, 0, headerBytes.Length);
                    Array.Copy(data, offset, chunk, headerBytes.Length, size);
                    _udp.Send(chunk, chunk.Length, remoteIp, remotePort);
                    if (printSendLog)
                        Debug.Log($"[GO1LocalPathUdpSender] chunk {c + 1}/{totalChunks} sent {chunk.Length} bytes");
                }
            }
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1LocalPathUdpSender] UDP send error: " + e.Message);
        }
    }

    [ContextMenu("Send PATH_CANCEL")]
    public void SendPathCancel()
    {
        if (_udp == null)
            _udp = new UdpClient();

        const string msg = "PATH_CANCEL";
        byte[] data = Encoding.UTF8.GetBytes(msg);

        try
        {
            _udp.Send(data, data.Length, remoteIp, remotePort);
            if (printSendLog)
                Debug.Log($"[GO1LocalPathUdpSender] PATH_CANCEL sent to {remoteIp}:{remotePort}");
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1LocalPathUdpSender] PATH_CANCEL UDP send error: " + e.Message);
        }
    }

    private void InitSentPathLineRenderer()
    {
        if (!showSentPathLine) return;

        GameObject lineObj = new GameObject("GO1_SentPath_YellowLine");
        lineObj.transform.SetParent(transform, false);

        _sentPathLine = lineObj.AddComponent<LineRenderer>();
        _sentPathLine.useWorldSpace = true;
        _sentPathLine.positionCount = 0;
        _sentPathLine.startWidth = sentPathLineWidth;
        _sentPathLine.endWidth = sentPathLineWidth;
        _sentPathLine.startColor = sentPathLineColor;
        _sentPathLine.endColor = sentPathLineColor;
        _sentPathLine.material = new Material(Shader.Find("Sprites/Default"));
    }

    public void ClearSentPathLine()
    {
        if (_sentPathLine != null)
            _sentPathLine.positionCount = 0;
    }

    public void DrawSentPathLine(Vector3[] worldCorners)
    {
        if (!showSentPathLine || worldCorners == null || worldCorners.Length == 0)
            return;

        if (_sentPathLine == null)
            InitSentPathLineRenderer();

        if (_sentPathLine == null)
            return;

        _sentPathLine.positionCount = worldCorners.Length;

        for (int i = 0; i < worldCorners.Length; i++)
        {
            Vector3 p = worldCorners[i];
            p.y += sentPathLineHeightOffset;
            _sentPathLine.SetPosition(i, p);
        }

        Debug.Log($"[GO1LocalPathUdpSender] 노란색 경로 라인 표시: {worldCorners.Length}개 point");
    }

    private PathMessage BuildMessage(Vector3[] worldCorners)
    {
        float startYawDeg = _startWorldRot.eulerAngles.y;

        PathMessage msg = new PathMessage
        {
            type = "go1_path",
            mode = pathMode,
            frame = "go1_local_start",
            path_id = pathId,
            start_pose = new StartPose
            {
                x = 0.0f,
                z = 0.0f,
                yaw_deg = startYawDeg
            },
            point_count = worldCorners.Length,
            position_tolerance = positionTolerance,
            yaw_tolerance_deg = yawToleranceDeg,
            default_speed = defaultSpeed,
            points = new List<PathPoint>()
        };

        List<Vector2> localPts2D = new List<Vector2>();

        for (int i = 0; i < worldCorners.Length; i++)
        {
            Vector2 local2D = Mapper.UnityWorldToPathLocal2D(worldCorners[i], _startWorldPos, _startWorldRot);

            if (forceFirstPointAsOrigin && i == 0)
                local2D = Vector2.zero;

            localPts2D.Add(local2D);

            if (printDebugLocalPoints)
            {
                Debug.Log(
                    $"[GO1LocalPathUdpSender] corner[{i}] world={worldCorners[i]} -> " +
                    $"pathLocal=({local2D.x:F3}, {local2D.y:F3})"
                );
            }
        }

        for (int i = 0; i < localPts2D.Count; i++)
        {
            float yawDeg = 0f;
            bool useYaw = false;

            bool isFinalPoint = (i == localPts2D.Count - 1);
            bool allowYawThisPoint = useYawForAllPoints;

            if (useYawOnlyAtFinalPoint)
                allowYawThisPoint = isFinalPoint && useLastSegmentYawForFinalPoint;

            if (allowYawThisPoint)
            {
                Vector2 dir = Vector2.zero;

                if (!useYawOnlyAtFinalPoint && i < localPts2D.Count - 1)
                    dir = localPts2D[i + 1] - localPts2D[i];
                else if (i > 0)
                    dir = localPts2D[i] - localPts2D[i - 1];

                if (dir.sqrMagnitude >= minYawSegmentLength * minYawSegmentLength)
                {
                    yawDeg = Mapper.PathDirectionToYawDeg(dir);
                    useYaw = true;
                }
            }

            msg.points.Add(new PathPoint
            {
                index = i,
                x = (float)Math.Round(localPts2D[i].x, 4),
                z = (float)Math.Round(localPts2D[i].y, 4),
                yaw_deg = (float)Math.Round(yawDeg, 2),
                use_yaw = useYaw
            });
        }

        return msg;
    }

    [ContextMenu("Print Coordinate Mapping Summary")]
    public void PrintCoordinateMappingSummary()
    {
        Debug.Log(Mapper.BuildSummary());
    }

    [ContextMenu("Send Test Fixed Path")]
    public void SendTestFixedPath()
    {
        PathMessage msg = new PathMessage
        {
            type = "go1_path",
            frame = "go1_local_start",
            path_id = pathId,
            start_pose = new StartPose { x = 0f, z = 0f, yaw_deg = 0f },
            point_count = 4,
            position_tolerance = positionTolerance,
            yaw_tolerance_deg = yawToleranceDeg,
            default_speed = defaultSpeed,
            points = new List<PathPoint>
            {
                new PathPoint { index=0, x=0.0f, z=0.0f, yaw_deg=Mapper.PathRawYawToSendYawDeg(0.0f),  use_yaw=false },
                new PathPoint { index=1, x=0.0f, z=0.5f, yaw_deg=Mapper.PathRawYawToSendYawDeg(0.0f),  use_yaw=false },
                new PathPoint { index=2, x=0.3f, z=0.5f, yaw_deg=Mapper.PathRawYawToSendYawDeg(90.0f), use_yaw=false },
                new PathPoint { index=3, x=0.3f, z=1.0f, yaw_deg=Mapper.PathRawYawToSendYawDeg(0.0f),  use_yaw=true  }
            }
        };

        string json = JsonUtility.ToJson(msg, true);

        if (printJson)
            Debug.Log("[GO1LocalPathUdpSender] TEST JSON:\n" + json);

        byte[] data = Encoding.UTF8.GetBytes(json);

        try
        {
            _udp.Send(data, data.Length, remoteIp, remotePort);
            if (printSendLog)
                Debug.Log($"[GO1LocalPathUdpSender] TEST sent {data.Length} bytes to {remoteIp}:{remotePort}");
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1LocalPathUdpSender] TEST UDP send error: " + e.Message);
        }
    }
}
