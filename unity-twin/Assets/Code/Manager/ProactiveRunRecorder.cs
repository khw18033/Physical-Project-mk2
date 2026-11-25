using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 가상 평가 run을 위에서 내려다본 화면으로 찍어 JPG 프레임으로 저장한다 (영상은 밖에서 합친다).
/// 화면에 같이 그리는 것: 현재 따라가는 경로(초록 선), 지나온 자취(파란 선), 로봇 표시(하늘색 원), 시작/목표 표시.
/// 시뮬레이션 시간 기준 일정 간격으로 찍으므로 실행 속도와 상관없이 재생 속도가 실제 시간과 같다.
/// </summary>
public class ProactiveRunRecorder : MonoBehaviour
{
    public string outputDir;
    public int fps = 15;
    public int width = 1280, height = 720;
    public float cameraHeight = 2.4f;
    [Tooltip("켜면 실제 시간 기준으로 찍는다(실제 로봇 주행 기록용). 끄면 시뮬레이션 시간 기준.")]
    public bool realTime = false;
    [Tooltip("켜면 run 마다 시작점·목표점 주변만 보이게 화면을 맞춘다 (넓은 맵에서 로봇이 너무 작게 보일 때).")]
    public bool autoFrame = false;
    public float autoFrameMargin = 3.0f;
    private float Now => realTime ? Time.realtimeSinceStartup : Time.time;

    private GO1Agent agent;
    private Camera cam;
    private RenderTexture rt;
    private Texture2D tex;
    private LineRenderer pathLine, trailLine;
    private Transform robotMark, startMark, goalMark;
    private readonly List<Vector3> trail = new List<Vector3>();
    private Vector3 lastRealPos;
    private bool recording;
    private string runDir;
    private int frame;
    private float nextT, t0;
    private StreamWriter times;

    public void Setup(GO1Agent a)
    {
        agent = a;

        // 지도 범위 = NavMesh 범위
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        Bounds b = new Bounds(tri.vertices[0], Vector3.zero);
        foreach (Vector3 v in tri.vertices) b.Encapsulate(v);

        var go = new GameObject("ProactiveRecorderCamera");
        cam = go.AddComponent<Camera>();
        cam.enabled = false;                       // 직접 Render() 할 때만 그린다
        cam.orthographic = true;
        cam.orthographicSize = b.extents.x + 0.9f; // 화면 세로 = x축, 가로 = z축
        cam.transform.position = new Vector3(b.center.x, cameraHeight, b.center.z);
        cam.transform.rotation = Quaternion.Euler(90f, -90f, 0f);
        cam.nearClipPlane = 0.01f;
        cam.farClipPlane = cameraHeight + 2f;
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.12f, 0.12f, 0.14f);
        rt = new RenderTexture(width, height, 24);
        cam.targetTexture = rt;
        tex = new Texture2D(width, height, TextureFormat.RGB24, false);

        pathLine = MakeLine("RecPath", new Color(0.1f, 0.9f, 0.2f), 0.05f);
        trailLine = MakeLine("RecTrail", new Color(0.2f, 0.5f, 1f), 0.06f);
        robotMark = MakeDisc("RecRobot", new Color(0.2f, 0.9f, 1f), 0.5f);
        startMark = MakeDisc("RecStart", new Color(0.9f, 0.9f, 0.9f), 0.3f);
        goalMark = MakeDisc("RecGoal", new Color(1f, 0.2f, 0.9f), 0.4f);
    }

    public static Material Flat(Color c)
    {
        Shader sh = Shader.Find("Sprites/Default");
        if (sh == null) sh = Shader.Find("Unlit/Color");
        return new Material(sh) { color = c };
    }

    private LineRenderer MakeLine(string name, Color c, float w)
    {
        var lr = new GameObject(name).AddComponent<LineRenderer>();
        lr.material = Flat(c);
        lr.startColor = lr.endColor = c;
        lr.startWidth = lr.endWidth = w;
        lr.useWorldSpace = true;
        lr.positionCount = 0;
        lr.numCornerVertices = 2;
        return lr;
    }

    private Transform MakeDisc(string name, Color c, float diameter)
    {
        GameObject g = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        g.name = name;
        Destroy(g.GetComponent<Collider>());
        g.GetComponent<Renderer>().material = Flat(c);
        g.transform.localScale = new Vector3(diameter, 0.005f, diameter);
        g.SetActive(false);
        return g.transform;
    }

    public void BeginRun(string name, Vector3 start, Vector3 goal)
    {
        if (cam == null || string.IsNullOrEmpty(outputDir)) return;
        runDir = Path.Combine(outputDir, name);
        Directory.CreateDirectory(runDir);
        times = new StreamWriter(Path.Combine(runDir, "frames.csv"));
        times.WriteLine("frame,t");
        frame = 0;
        trail.Clear();
        lastRealPos = agent.transform.position;
        t0 = Now;
        nextT = Now;
        if (autoFrame && cam != null)
        {
            // 화면 세로 = x축, 가로 = z축
            float halfX = Mathf.Abs(start.x - goal.x) * 0.5f + autoFrameMargin, halfZ = Mathf.Abs(start.z - goal.z) * 0.5f + autoFrameMargin;
            float aspect = (float)width / height;
            cam.orthographicSize = Mathf.Max(3.5f, halfX, halfZ / aspect);
            cam.transform.position = new Vector3((start.x + goal.x) * 0.5f, cam.transform.position.y, (start.z + goal.z) * 0.5f);
        }
        startMark.position = new Vector3(start.x, 0.05f, start.z); startMark.gameObject.SetActive(true);
        goalMark.position = new Vector3(goal.x, 0.05f, goal.z); goalMark.gameObject.SetActive(true);
        robotMark.gameObject.SetActive(true);
        recording = true;
    }

    public void EndRun()
    {
        if (!recording) return;
        for (int i = 0; i < fps; i++) Capture();   // 마지막 장면을 1초 더 보여 준다
        recording = false;
        times.Dispose();
        pathLine.positionCount = 0;
        trailLine.positionCount = 0;
        robotMark.gameObject.SetActive(false);
        startMark.gameObject.SetActive(false);
        goalMark.gameObject.SetActive(false);
    }

    private void LateUpdate()
    {
        if (!recording || Now < nextT) return;
        nextT += 1f / fps;
        Capture();
    }

    private void Capture()
    {
        // 정지 후 재탐색 중에는 가상 GO1 모형이 경로 계산용으로 움직인다. 실제 위치(원 표시)와 자취는 멈춘 곳에 둔다.
        // 실제 로봇 주행: 경로 계산(가상 로봇만 빠르게 움직임) 중이 아니면 가상 로봇 위치 = 실제 로봇 추정 위치
        if (agent.ProactiveIsLocalReplayActive || (!agent.virtualOnlyMode && !agent.IsVirtualPathPlanning()))
            lastRealPos = agent.transform.position;
        Vector3 p = lastRealPos;
        robotMark.position = new Vector3(p.x, 0.03f, p.z);

        Vector3 tp = new Vector3(p.x, 0.07f, p.z);
        if (trail.Count == 0 || Vector3.Distance(trail[trail.Count - 1], tp) > 0.02f) trail.Add(tp);
        trailLine.positionCount = trail.Count;
        trailLine.SetPositions(trail.ToArray());

        IReadOnlyList<Vector3> path = agent.ProactiveLocalReplayPath;
        if ((path == null || path.Count == 0) && !agent.virtualOnlyMode) path = agent.ReplanCurrentSentPath;   // 실제 로봇에 보낸 경로
        int n = path != null ? path.Count : 0;
        pathLine.positionCount = n;
        for (int i = 0; i < n; i++) pathLine.SetPosition(i, new Vector3(path[i].x, 0.06f, path[i].z));

        cam.Render();
        RenderTexture prev = RenderTexture.active;
        RenderTexture.active = rt;
        tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
        tex.Apply(false);
        RenderTexture.active = prev;
        File.WriteAllBytes(Path.Combine(runDir, "f_" + frame.ToString("D5") + ".jpg"), tex.EncodeToJPG(88));
        times.WriteLine(frame + "," + (Now - t0).ToString("0.###", System.Globalization.CultureInfo.InvariantCulture));
        frame++;
    }
}
