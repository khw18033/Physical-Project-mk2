// 사람 탐지 표시를 카메라 없이 확인하는 시연 (2026-11-25).
// 360° 카메라가 보내는 것과 같은 형식의 탐지 묶음을 이 PC 안에서 UDP 로 보내고, 맵에 사람 모형이 서는지 녹화한다.
//   걷는 사람 1명(복도를 왔다 갔다) + 서 있는 사람 1명 + 상자 1개(360°) + Go1 정면의 사람 1명(Go1 카메라)
// PersonDemoLauncher 가 씬을 열고 이 컴포넌트를 붙여 Play 한다. 결과: GO1_Proactive_Evaluation/person_demo/

using System.Collections;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

public class PersonDemoRunner : MonoBehaviour
{
    public float durationSec = 24f;
    public int fps = 15, width = 1280, height = 720;
    public Vector3 walkA = new Vector3(10.6f, 0f, 7.9f), walkB = new Vector3(16.2f, 0f, 10.2f);
    public Vector3 standPos = new Vector3(12.0f, 0f, 10.3f), boxPos = new Vector3(14.6f, 0f, 7.9f);
    public Vector3 camPos = new Vector3(19.0f, 4.6f, 12.8f), camLook = new Vector3(13.2f, 0.6f, 9.0f);
    public float walkSpeed = 0.9f;

    private static readonly CultureInfo ci = CultureInfo.InvariantCulture;
    private string outDir;

    IEnumerator Start()
    {
        outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "person_demo");
        string frames = Path.Combine(outDir, "frames");
        if (Directory.Exists(frames)) Directory.Delete(frames, true);
        Directory.CreateDirectory(frames);

        Anchor360ObstacleReceiver recv = null;
        foreach (var r in FindObjectsByType<Anchor360ObstacleReceiver>(FindObjectsSortMode.None))
            if (r.isActiveAndEnabled && (recv == null || r.gameObject.name == "Anchor360")) recv = r;
        if (recv == null) { Debug.LogError("[PersonDemo] Anchor360ObstacleReceiver 없음"); Finish(1); yield break; }
        Transform anchor = recv.anchorTransform != null ? recv.anchorTransform : recv.transform;
        Transform robot = null;
        foreach (var utm in FindObjectsByType<UnityTeleopAndMirror>(FindObjectsSortMode.None))
            if (robot == null) robot = utm.driver != null ? utm.driver.transform : utm.robotRoot;

        Time.captureFramerate = fps;
        for (int i = 0; i < fps; i++) yield return null;          // 수신기가 설정 파일을 읽을 시간

        var camGo = new GameObject("PersonDemoCam");
        var cam = camGo.AddComponent<Camera>();
        cam.enabled = false; cam.fieldOfView = 55f; cam.nearClipPlane = 0.1f; cam.farClipPlane = 100f;
        cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.12f, 0.12f, 0.14f);
        cam.transform.position = camPos; cam.transform.rotation = Quaternion.LookRotation(camLook - camPos);
        var rt = new RenderTexture(width, height, 24);
        var tex = new Texture2D(width, height, TextureFormat.RGB24, false);
        cam.targetTexture = rt;

        var udp = new UdpClient();
        float t0 = Time.time, walkLen = Vector3.Distance(walkA, walkB);
        int n = 0; bool stillRobot = false, stillTop = false;
        Debug.Log("[PersonDemo] 시작 | 수신 포트 " + recv.listenPort + " | 카메라(앵커) " + anchor.position.ToString("F2") + " | 범위 " + recv.detectRangeM.ToString("F1", ci) + " m");

        while (Time.time - t0 < durationSec)
        {
            float t = Time.time - t0;
            // 걷는 사람: A ↔ B 왕복. 처음 3초와 끝에서는 잠깐 서 있는다.
            float s = Mathf.PingPong(Mathf.Max(0f, t - 3f) * walkSpeed, walkLen);
            Vector3 walker = Vector3.Lerp(walkA, walkB, s / walkLen);

            var sb = new StringBuilder("{\"schema_version\":\"2.0\",\"source_id\":\"person_demo\",\"detections\":[");
            sb.Append(Det(recv, anchor, 1, "person", walker, 0.5f, 1.7f)).Append(',');
            sb.Append(Det(recv, anchor, 2, "person", standPos, 0.5f, 1.7f)).Append(',');
            sb.Append(Det(recv, anchor, 3, "box", boxPos, 0.4f, 0.4f));
            sb.Append("]}");
            byte[] b = Encoding.UTF8.GetBytes(sb.ToString());
            udp.Send(b, b.Length, "127.0.0.1", recv.listenPort);

            // Go1 정면 1.2 m 에 사람 (Go1 카메라가 보낸 것처럼)
            string g = "{\"type\":\"go1_front_guard\",\"level\":\"warn\",\"nearest_name\":\"person\",\"nearest_forward_m\":1.2,\"video_age_s\":0.1,\"warn_m\":1.0,\"stop_m\":0.6," +
                       "\"detections\":[{\"name\":\"person\",\"conf\":0.9,\"right_m\":0.1,\"forward_m\":1.2,\"dist_m\":1.2,\"in_path\":true}]}";
            byte[] gb = Encoding.UTF8.GetBytes(g);
            udp.Send(gb, gb.Length, "127.0.0.1", 5012);

            Grab(cam, rt, tex, Path.Combine(frames, "f_" + n.ToString("D4") + ".jpg"), true);
            n++;

            if (!stillTop && t > 9f)
            {
                stillTop = true;
                cam.transform.position = new Vector3(13.2f, 9.5f, 9.0f); cam.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
                Grab(cam, rt, tex, Path.Combine(outDir, "person_top.png"), false);
                cam.transform.position = new Vector3(15.2f, 1.7f, 11.6f); cam.transform.rotation = Quaternion.LookRotation(new Vector3(12.4f, 0.9f, 9.6f) - cam.transform.position);
                Grab(cam, rt, tex, Path.Combine(outDir, "person_close.png"), false);
                cam.transform.position = camPos; cam.transform.rotation = Quaternion.LookRotation(camLook - camPos);
            }
            if (!stillRobot && t > 12f && robot != null)
            {
                stillRobot = true;
                Vector3 f = -robot.right; f.y = 0f; f.Normalize();
                Vector3 side = new Vector3(f.z, 0f, -f.x);
                Vector3 look = robot.position + f * 0.7f + Vector3.up * 0.7f;
                cam.transform.position = robot.position + f * 0.6f + side * 3.0f + Vector3.up * 1.7f;
                cam.transform.rotation = Quaternion.LookRotation(look - cam.transform.position);
                Grab(cam, rt, tex, Path.Combine(outDir, "person_go1_front.png"), false);
                cam.transform.position = camPos; cam.transform.rotation = Quaternion.LookRotation(camLook - camPos);
            }
            yield return null;
        }

        // 결과 요약
        var sum = new StringBuilder();
        int persons = 0, hidden = 0;
        foreach (var link in FindObjectsByType<PersonVisualLink>(FindObjectsSortMode.None))
        {
            if (!link.HasVisual) continue;
            persons++;
            var r = link.GetComponent<Renderer>();
            if (r != null && !r.enabled) hidden++;
            var nav = link.GetComponent<NavMeshObstacle>();
            sum.Append(" | ").Append(link.gameObject.name).Append(" (").Append(link.transform.position.x.ToString("F2", ci)).Append(", ")
               .Append(link.transform.position.z.ToString("F2", ci)).Append(") 길 파냄=").Append(nav != null && nav.enabled && nav.carving);
        }
        int boxes = 0;
        GameObject obsRoot = GameObject.Find("Anchor360_Obstacles");
        if (obsRoot != null)
            foreach (Transform c in obsRoot.transform)
                if (c.GetComponent<PersonVisualLink>() == null) { var r = c.GetComponent<Renderer>(); if (r != null && r.enabled) boxes++; }
        // 서 있는 사람 자리가 주행 가능 영역에서 빠졌는지
        bool carved = !(NavMesh.SamplePosition(standPos, out NavMeshHit hit, 0.5f, NavMesh.AllAreas) && (hit.position - standPos).sqrMagnitude < 0.05f * 0.05f);
        var path = new NavMeshPath();
        bool hasPath = NavMesh.CalculatePath(new Vector3(9.0f, 0f, 10.3f), new Vector3(15.5f, 0f, 10.3f), NavMesh.AllAreas, path) && path.status == NavMeshPathStatus.PathComplete;
        float minD = float.MaxValue;
        if (hasPath)
            for (int i = 0; i + 1 < path.corners.Length; i++)
                minD = Mathf.Min(minD, SegDist(standPos, path.corners[i], path.corners[i + 1]));
        string line = "사람 모형 " + persons + "개 (상자 그림 숨김 " + hidden + "), 상자로 남은 것 " + boxes + "개, 서 있는 사람 자리 주행 영역에서 빠짐=" + carved +
                      ", 그 옆을 지나는 경로=" + hasPath + (hasPath ? " (사람 중심에서 최소 " + minD.ToString("F2", ci) + " m)" : "") + ", 프레임 " + n + sum;
        Debug.Log("[PersonDemo] 결과: " + line);
        File.WriteAllText(Path.Combine(outDir, "result.txt"), line + "\n", new UTF8Encoding(false));
        udp.Close();
        Finish(persons >= 3 ? 0 : 2);
    }

    private static float SegDist(Vector3 p, Vector3 a, Vector3 b)
    {
        Vector2 P = new Vector2(p.x, p.z), A = new Vector2(a.x, a.z), B = new Vector2(b.x, b.z);
        Vector2 ab = B - A; float t = ab.sqrMagnitude > 1e-8f ? Mathf.Clamp01(Vector2.Dot(P - A, ab) / ab.sqrMagnitude) : 0f;
        return (P - (A + ab * t)).magnitude;
    }

    // 맵 위치 → 카메라(앵커) 기준 좌표로 되돌려 탐지 한 건을 만든다 (수신기가 하는 변환의 반대)
    private static string Det(Anchor360ObstacleReceiver recv, Transform anchor, int id, string label, Vector3 world, float w, float h)
    {
        Vector3 local = Quaternion.Inverse(Quaternion.Euler(0f, recv.yawOffsetDeg, 0f)) * anchor.InverseTransformPoint(new Vector3(world.x, anchor.position.y, world.z));
        float ds = Mathf.Abs(recv.distanceScale) > 1e-4f ? recv.distanceScale : 1f;
        float x = local.x / ds * (recv.invertX ? -1f : 1f), z = local.z / ds;
        return "{\"id\":" + id + ",\"label\":\"" + label + "\",\"confidence\":0.9,\"pos_src\":\"depth\",\"position\":{\"x\":" + x.ToString("F3", ci) + ",\"y\":0,\"z\":" + z.ToString("F3", ci) +
               "},\"ground_dist_m\":" + Mathf.Sqrt(x * x + z * z).ToString("F3", ci) + ",\"size_m\":{\"w\":" + w.ToString("F2", ci) + ",\"h\":" + h.ToString("F2", ci) + ",\"d\":" + w.ToString("F2", ci) + "}}";
    }

    private static void Grab(Camera cam, RenderTexture rt, Texture2D tex, string path, bool jpg)
    {
        cam.Render();
        RenderTexture.active = rt;
        tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0); tex.Apply();
        RenderTexture.active = null;
        File.WriteAllBytes(path, jpg ? tex.EncodeToJPG(88) : tex.EncodeToPNG());
    }

    private static void Finish(int code)
    {
#if UNITY_EDITOR
        if (Application.isBatchMode) { UnityEditor.EditorApplication.Exit(code); return; }
        UnityEditor.EditorApplication.isPlaying = false;
#else
        Application.Quit(code);
#endif
    }
}
