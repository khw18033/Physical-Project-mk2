// 360 카메라 마커로 가상 Go1 을 실제 위치에 맞추는 것을 에디터 창 없이 확인한다.
// 실행 중 anchor360_marker_live.py 가 UDP 5013 으로 마커를 보내고 있어야 한다.
// 맞추기 전/후를 위에서 본 화면으로 저장하고 결과를 report.txt 에 적는다.
//   Unity.exe -batchmode -projectPath ... -executeMethod MarkerAlignSnapshotLauncher.Run   (-nographics 없이)

using System.Collections;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

public class MarkerAlignSnapshotRunner : MonoBehaviour
{
    public const string OutDir = "GO1_Proactive_Evaluation/marker_align";
    public float waitSeconds = 150f;

    private Camera cam; private RenderTexture rt; private Texture2D tex;

    private void Awake()
    {
        Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
        Application.SetStackTraceLogType(LogType.Warning, StackTraceLogType.None);
    }

    private void Start() { StartCoroutine(Run()); }

    private IEnumerator Run()
    {
        string outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, OutDir);
        Directory.CreateDirectory(outDir);
        yield return new WaitForSecondsRealtime(4f);

        var rx = FindFirstObjectByType<Robot360MarkerReceiver>();
        if (rx == null) rx = new GameObject("Robot360Marker").AddComponent<Robot360MarkerReceiver>();
        rx.followGain = 0f;   // 이 확인에서는 초기 정합만 본다
        yield return new WaitForSecondsRealtime(1f);

        SetupCamera();
        Transform robot = null;
        foreach (var u in FindObjectsByType<UnityTeleopAndMirror>(FindObjectsSortMode.None))
            if (u.robotId == rx.robotId) robot = u.driver != null ? u.driver.transform : u.robotRoot;
        Mark(robot, new Color(1f, 0.3f, 0.2f, 0.9f), "MarkBefore");
        Capture(Path.Combine(outDir, "1_정합_전.png"));
        Debug.Log("[MarkerAlign] ready, waiting for marker packets on UDP " + rx.listenPort);

        float until = Time.realtimeSinceStartup + waitSeconds;
        while (!rx.Aligned && Time.realtimeSinceStartup < until) yield return null;
        yield return new WaitForSecondsRealtime(0.5f);

        var sb = new StringBuilder();
        if (!rx.Aligned)
        {
            sb.AppendLine("정합 실패: " + waitSeconds + "초 동안 마커를 " + rx.Fixes + "번 받음 (필요 " + rx.initialSamples + ")");
        }
        else
        {
            Mark(robot, new Color(0.1f, 0.9f, 0.3f, 0.9f), "MarkAfter");
            Capture(Path.Combine(outDir, "2_정합_후.png"));

            // 표시를 지우고 가상 화면 그대로: 위에서 본 전체 / 로봇 주변 확대 / 실제 360 카메라 자리에서 본 모습
            foreach (string n in new[] { "MarkBefore", "MarkBeforeDir", "MarkAfter", "MarkAfterDir" })
            { var g = GameObject.Find(n); if (g != null) g.SetActive(false); }
            foreach (var t in FindObjectsByType<Transform>(FindObjectsSortMode.None))
                if (t.name.StartsWith("Range")) t.gameObject.SetActive(false);   // 탐지 범위 표시(보라/초록)는 가린다
            yield return null;
            Capture(Path.Combine(outDir, "3_가상화면_위에서.png"));

            float fullSize = cam.orthographicSize; Vector3 fullPos = cam.transform.position;
            cam.orthographicSize = 1.6f;
            cam.transform.position = new Vector3(robot.position.x, fullPos.y, robot.position.z);
            Capture(Path.Combine(outDir, "4_가상화면_로봇_확대.png"));
            cam.orthographicSize = fullSize; cam.transform.position = fullPos;

            var a360 = FindFirstObjectByType<Anchor360ObstacleReceiver>();
            if (a360 != null)
            {
                Transform anchor = a360.anchorTransform != null ? a360.anchorTransform : a360.transform;
                cam.orthographic = false;
                cam.fieldOfView = 55f;
                cam.farClipPlane = 30f;
                cam.transform.position = new Vector3(anchor.position.x, 2.0f, anchor.position.z);
                cam.transform.LookAt(robot.position + Vector3.up * 0.15f);
                Capture(Path.Combine(outDir, "5_가상화면_360카메라_자리에서.png"));
            }
            Vector3 d = robot.position - rx.PoseBeforeAlign; d.y = 0f;
            Vector3 f = -robot.right; f.y = 0f;
            float yawNow = Mathf.Repeat(Mathf.Atan2(f.x, f.z) * Mathf.Rad2Deg, 360f);
            sb.AppendLine("정합 전 가상 로봇: (" + rx.PoseBeforeAlign.x.ToString("F3") + ", " + rx.PoseBeforeAlign.z.ToString("F3") + ") 방향 " + rx.YawBeforeAlign.ToString("F1") + "도");
            sb.AppendLine("마커가 알려준 위치: (" + rx.LastWorldPos.x.ToString("F3") + ", " + rx.LastWorldPos.z.ToString("F3") + ") 방향 " + rx.LastWorldYawDeg.ToString("F1") + "도");
            sb.AppendLine("정합 후 가상 로봇: (" + robot.position.x.ToString("F3") + ", " + robot.position.z.ToString("F3") + ") 방향 " + yawNow.ToString("F1") + "도");
            sb.AppendLine("옮긴 거리 " + (d.magnitude * 100f).ToString("F1") + " cm, 돌린 각 " + Mathf.DeltaAngle(rx.YawBeforeAlign, yawNow).ToString("F1") + "도");
            bool onMesh = NavMesh.SamplePosition(robot.position, out NavMeshHit h, 0.5f, NavMesh.AllAreas);
            sb.AppendLine("정합 후 위치가 주행 가능 바닥 위인가: " + (onMesh ? "예 (가장 가까운 바닥까지 " + (Vector3.Distance(h.position, robot.position) * 100f).ToString("F0") + " cm)" : "아니오"));
        }
        File.WriteAllText(Path.Combine(outDir, "report.txt"), sb.ToString(), new UTF8Encoding(true));
        Debug.Log("[MarkerAlign] " + sb.ToString().Replace("\n", " | "));
        Debug.Log("[MarkerAlign] OK");
#if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(0);
#endif
    }

    // 위에서 잘 보이도록 로봇 자리에 원판과 진행 방향 막대를 놓는다
    private void Mark(Transform robot, Color c, string name)
    {
        if (robot == null) return;
        Vector3 f = -robot.right; f.y = 0f; f.Normalize();
        var disc = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        disc.name = name; Destroy(disc.GetComponent<Collider>());
        disc.transform.position = new Vector3(robot.position.x, 0.9f, robot.position.z);
        disc.transform.localScale = new Vector3(0.5f, 0.005f, 0.5f);
        disc.GetComponent<Renderer>().material = ProactiveRunRecorder.Flat(c);
        var bar = GameObject.CreatePrimitive(PrimitiveType.Cube);
        bar.name = name + "Dir"; Destroy(bar.GetComponent<Collider>());
        bar.transform.position = new Vector3(robot.position.x, 0.92f, robot.position.z) + f * 0.35f;
        bar.transform.rotation = Quaternion.LookRotation(f);
        bar.transform.localScale = new Vector3(0.08f, 0.01f, 0.7f);
        bar.GetComponent<Renderer>().material = ProactiveRunRecorder.Flat(c);
    }

    private void SetupCamera()
    {
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        Bounds b = new Bounds(tri.vertices[0], Vector3.zero);
        foreach (Vector3 v in tri.vertices) b.Encapsulate(v);
        cam = new GameObject("SnapshotCamera").AddComponent<Camera>();
        cam.enabled = false; cam.orthographic = true;
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
}
