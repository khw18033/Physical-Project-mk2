// 저장해 둔 360 카메라 검출 패킷(JSON)을 실제와 같은 길(UDP 5010)로 넣어 보고,
// 트윈에 어떻게 배치되는지 위에서 본 화면으로 저장한다. 실제 카메라 없이 수신기 설정을 비교할 때 쓴다.
//
// 설정: GO1_Proactive_Evaluation/anchor_snapshot/config.json
//   { "packetPath": "...json", "outDir": "...", "cases": [ { "name": "...", ...수신기 설정... } ] }
// 실행: Unity.exe -batchmode -projectPath ... -executeMethod Anchor360SnapshotLauncher.Run   (-nographics 없이)

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

public class Anchor360SnapshotRunner : MonoBehaviour
{
    public const string ConfigPath = "GO1_Proactive_Evaluation/anchor_snapshot/config.json";

    [Serializable]
    public class Case
    {
        public string name = "case";
        public bool showOverlapping = true;
        public float minConf = 0f;
        public float maxFootprint = 0f;
        public float nearFloor = 0f;
        public bool useBaseline = false;
        public string baselineFromPacket = "";   // 이 패킷을 '원래 있던 물건'으로 기록한 뒤 본 패킷을 넣는다
        public string packetPath = "";           // 비우면 공통 packetPath
        public float addNewX = 0f, addNewZ = 0f; // 0이 아니면 이 맵 좌표에 새 상자 하나를 검출에 더한다(가상으로 만든 검출)
    }

    [Serializable]
    public class Config
    {
        public string packetPath;
        public string outDir = "GO1_Proactive_Evaluation/anchor_snapshot";
        public Case[] cases;
    }

    private Camera cam;
    private RenderTexture rt;
    private Texture2D tex;

    private void Awake()
    {
        Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
        Application.SetStackTraceLogType(LogType.Warning, StackTraceLogType.None);
    }

    private void Start() { StartCoroutine(Run()); }

    private IEnumerator Run()
    {
        string root = Directory.GetParent(Application.dataPath).FullName;
        Config cfg = JsonUtility.FromJson<Config>(File.ReadAllText(Path.Combine(root, ConfigPath)));
        string outDir = Path.IsPathRooted(cfg.outDir) ? cfg.outDir : Path.Combine(root, cfg.outDir);
        Directory.CreateDirectory(outDir);

        yield return new WaitForSecondsRealtime(4f);   // 수신기 Start, 보정 파일 적용

        Anchor360ObstacleReceiver rx = null;
        foreach (var r in FindObjectsByType<Anchor360ObstacleReceiver>(FindObjectsSortMode.None))
            if (r.isActiveAndEnabled && !r.loadFromFile) { rx = r; break; }
        if (rx == null) { Debug.LogError("[Snapshot] FAILED: 활성 Anchor360ObstacleReceiver 없음"); Quit(1); yield break; }
        Debug.Log("[Snapshot] receiver on '" + rx.name + "' port " + rx.listenPort);

        SetupCamera();
        float areaBase = NavArea();
        var report = new StringBuilder("case,detections,cubes,cubes_with_collider,low_conf,baseline,off_floor,elevated,nav_area_m2,nav_area_lost_m2,paths_ok,paths_total\n");
        List<Vector3[]> probes = ProbePairs();

        // 아무것도 넣지 않은 화면
        Capture(Path.Combine(outDir, "0_탐지_넣기_전.png"));
        report.AppendLine($"empty,0,0,0,0,0,0,0,{areaBase:F2},0,{CountPaths(probes)},{probes.Count}");

        var udp = new UdpClient();
        int idx = 1;
        foreach (Case c in cfg.cases)
        {
            // 앞 case의 큐브를 비운다: 빈 패킷을 보내고 유지 시간이 지나길 기다린다
            yield return Send(udp, rx.listenPort, "{\"detections\":[]}", rx.missingGraceSec + 1.5f);

            rx.minPlaceConfidence = c.minConf;
            rx.maxFootprintM = c.maxFootprint;
            rx.nearFloorM = c.nearFloor;
            rx.useBaseline = c.useBaseline;
            SetPrivate(rx, "calibShowOverlapping", c.showOverlapping);

            if (!string.IsNullOrEmpty(c.baselineFromPacket))
            {
                rx.BeginBaselineCapture(2f);
                yield return Send(udp, rx.listenPort, File.ReadAllText(Resolve(root, c.baselineFromPacket)), 3f);
                yield return Send(udp, rx.listenPort, "{\"detections\":[]}", rx.missingGraceSec + 1.5f);
                Debug.Log("[Snapshot] baseline items = " + rx.BaselineCount);
            }

            string packet = File.ReadAllText(Resolve(root, string.IsNullOrEmpty(c.packetPath) ? cfg.packetPath : c.packetPath));
            if (c.addNewX != 0f || c.addNewZ != 0f) packet = AddDetection(rx, packet, c.addNewX, c.addNewZ);
            yield return Send(udp, rx.listenPort, packet, 3f);   // 큐브 생성 + NavMesh 파내기 반영

            int cubes = 0, withCol = 0;
            GameObject cubeRoot = GameObject.Find("Anchor360_Obstacles");
            if (cubeRoot != null)
                foreach (Transform t in cubeRoot.transform)
                {
                    cubes++;
                    var col = t.GetComponent<Collider>();
                    if (col != null && col.enabled) withCol++;
                }
            float area = NavArea();
            string file = idx + "_" + c.name + ".png";
            Capture(Path.Combine(outDir, file));
            report.AppendLine($"{c.name},{rx.statDetections},{cubes},{withCol},{rx.statLowConf},{rx.statBaseline},{rx.statOffFloor},{rx.statElevated},{area:F2},{areaBase - area:F2},{CountPaths(probes)},{probes.Count}");
            Debug.Log($"[Snapshot] {c.name}: detections={rx.statDetections} cubes={cubes} collider={withCol} navArea={area:F2} (base {areaBase:F2}) paths={CountPaths(probes)}/{probes.Count} → {file}");
            idx++;
        }

        File.WriteAllText(Path.Combine(outDir, "report.csv"), report.ToString(), new UTF8Encoding(true));
        Debug.Log("[Snapshot] OK");
        Quit(0);
    }

    // 맵 좌표 → 카메라 기준 좌표로 되돌려 검출 하나를 패킷에 끼워 넣는다 (수신기의 변환을 거꾸로 적용)
    private static string AddDetection(Anchor360ObstacleReceiver rx, string packet, float wx, float wz)
    {
        Transform a = rx.anchorTransform != null ? rx.anchorTransform : rx.transform;
        Vector3 local = a.InverseTransformPoint(new Vector3(wx, a.position.y, wz));
        local = Quaternion.Inverse(Quaternion.Euler(0f, rx.yawOffsetDeg, 0f)) * local;
        float lx = local.x / rx.distanceScale * (rx.invertX ? -1f : 1f), lz = local.z / rx.distanceScale;
        var ci = System.Globalization.CultureInfo.InvariantCulture;
        string det = "{\"name\":\"box\",\"group\":\"HARD_OBSTACLE\",\"pos3d\":{\"x\":" + lx.ToString("F3", ci) +
                     ",\"y\":0.0,\"z\":" + lz.ToString("F3", ci) + "},\"dist_m\":" +
                     Mathf.Sqrt(lx * lx + lz * lz).ToString("F3", ci) +
                     ",\"size\":{\"w\":0.35,\"h\":0.4,\"d\":0.35},\"conf\":0.8,\"id\":99,\"oriented\":false," +
                     "\"pos_src\":\"depth+contact\",\"elevated\":false},";
        int i = packet.IndexOf('[', packet.IndexOf("\"detections\""));
        return packet.Substring(0, i + 1) + det + packet.Substring(i + 1);
    }

    private static string Resolve(string root, string p) => Path.IsPathRooted(p) ? p : Path.Combine(root, p);

    private IEnumerator Send(UdpClient udp, int port, string json, float seconds)
    {
        byte[] data = Encoding.UTF8.GetBytes(json);
        float until = Time.realtimeSinceStartup + seconds;
        while (Time.realtimeSinceStartup < until)
        {
            udp.Send(data, data.Length, "127.0.0.1", port);
            yield return new WaitForSecondsRealtime(0.2f);
        }
    }

    private static void SetPrivate(object o, string field, object value)
    {
        var f = o.GetType().GetField(field, System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        if (f != null) f.SetValue(o, value);
    }

    private void SetupCamera()
    {
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        Bounds b = new Bounds(tri.vertices[0], Vector3.zero);
        foreach (Vector3 v in tri.vertices) b.Encapsulate(v);
        cam = new GameObject("SnapshotCamera").AddComponent<Camera>();
        cam.enabled = false;
        cam.orthographic = true;
        cam.orthographicSize = b.extents.x + 0.9f;
        cam.transform.position = new Vector3(b.center.x, 2.4f, b.center.z);
        cam.transform.rotation = Quaternion.Euler(90f, -90f, 0f);
        cam.nearClipPlane = 0.01f; cam.farClipPlane = 5f;
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.12f, 0.12f, 0.14f);
        rt = new RenderTexture(1600, 900, 24);
        cam.targetTexture = rt;
        tex = new Texture2D(1600, 900, TextureFormat.RGB24, false);
    }

    private void Capture(string path)
    {
        cam.Render();
        RenderTexture prev = RenderTexture.active;
        RenderTexture.active = rt;
        tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0);
        tex.Apply(false);
        RenderTexture.active = prev;
        File.WriteAllBytes(path, tex.EncodeToPNG());
    }

    private static float NavArea()
    {
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        float a = 0f;
        for (int i = 0; i < tri.indices.Length; i += 3)
            a += Vector3.Cross(tri.vertices[tri.indices[i + 1]] - tri.vertices[tri.indices[i]],
                               tri.vertices[tri.indices[i + 2]] - tri.vertices[tri.indices[i]]).magnitude * 0.5f;
        return a;
    }

    // 장애물이 없을 때 서로 이어지는 바닥 위 점 쌍 40개 (고정 seed). 장애물을 넣은 뒤 몇 쌍이 여전히 이어지는지 본다.
    private static List<Vector3[]> ProbePairs()
    {
        var list = new List<Vector3[]>();
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        var rng = new System.Random(4242);
        var path = new NavMeshPath();
        for (int attempt = 0; attempt < 5000 && list.Count < 40; attempt++)
        {
            Vector3 a = RandomPoint(tri, rng), b = RandomPoint(tri, rng);
            if (Vector3.Distance(a, b) < 3f) continue;
            if (!NavMesh.FindClosestEdge(a, out NavMeshHit ea, NavMesh.AllAreas) || ea.distance < 0.3f) continue;
            if (!NavMesh.FindClosestEdge(b, out NavMeshHit eb, NavMesh.AllAreas) || eb.distance < 0.3f) continue;
            if (NavMesh.CalculatePath(a, b, NavMesh.AllAreas, path) && path.status == NavMeshPathStatus.PathComplete)
                list.Add(new[] { a, b });
        }
        return list;
    }

    private static Vector3 RandomPoint(NavMeshTriangulation tri, System.Random rng)
    {
        int t = rng.Next(tri.indices.Length / 3) * 3;
        Vector3 a = tri.vertices[tri.indices[t]], b = tri.vertices[tri.indices[t + 1]], c = tri.vertices[tri.indices[t + 2]];
        float u = (float)rng.NextDouble(), v = (float)rng.NextDouble();
        if (u + v > 1f) { u = 1f - u; v = 1f - v; }
        return a + (b - a) * u + (c - a) * v;
    }

    private static int CountPaths(List<Vector3[]> probes)
    {
        int ok = 0;
        var path = new NavMeshPath();
        foreach (Vector3[] p in probes)
        {
            // 끝점이 파인 자리에 들어갔으면 가까운 바닥으로 옮겨서 본다
            if (!NavMesh.SamplePosition(p[0], out NavMeshHit a, 0.5f, NavMesh.AllAreas)) continue;
            if (!NavMesh.SamplePosition(p[1], out NavMeshHit b, 0.5f, NavMesh.AllAreas)) continue;
            if (NavMesh.CalculatePath(a.position, b.position, NavMesh.AllAreas, path) && path.status == NavMeshPathStatus.PathComplete) ok++;
        }
        return ok;
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
