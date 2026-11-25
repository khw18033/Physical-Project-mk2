// 캡스톤 발표장(배치도 "캡스톤 발표 배치도.jpg") 디지털 트윈 맵을 새 씬으로 만든다. 기존 lab.unity 는 건드리지 않는다.
//   Unity.exe -batchmode -projectPath D:\Go1_Unity -executeMethod CapstoneMapBuilder.Run -logFile <log>     (-nographics 없이: 확인용 그림을 그린다)
//
// 만드는 것
//   Assets/capstone_hall.unity                         lab.unity 를 복사한 뒤 가구·벽을 지우고 발표장으로 바꾼 씬 (로봇·통신·탐지 구성은 그대로)
//   Assets/capstone_hall/NavMesh-CapstoneHall.asset    새 바닥으로 구운 NavMesh (전시대는 lab 과 같이 실행 중에 파낸다)
//   Assets/StreamingAssets/anchor360_calib_capstone.json   이 씬 전용 360 카메라 보정 파일 (현장에서 다시 맞춰야 한다)
//   GO1_Proactive_Evaluation/capstone_map/capstone_hall_top.png, booths.csv
//
// 좌표: 배치도 왼쪽 아래(출입구 쪽 벽 안쪽 모서리)가 원점, +X = 배치도 오른쪽, +Z = 배치도 위쪽. 단위 m.
// 축척: 배치도의 치수 표기(5 m = 약 223 px)에서 1 m = 44.67 px, 전시대 한 칸 = 1 m x 1 m 로 읽었다.
// 배치도 위쪽이 잘려 있어 바닥은 출입구 벽에서 39 m 까지만 만든다 (표기된 전체 길이는 45 m).

using System.Globalization;
using System.IO;
using System.Text;
using Unity.AI.Navigation;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.AI;

public static class CapstoneMapBuilder
{
    private const string SrcScene = "Assets/lab.unity", DstScene = "Assets/capstone_hall.unity", AssetDir = "Assets/capstone_hall";
    private const string CalibName = "anchor360_calib_capstone.json";
    private const float PxPerM = 44.67f, OriginPxX = 303f, OriginPxY = 1735f;
    private const float HallW = 25.1f, HallL = 39.0f, BoothH = 0.75f, WallH = 3.0f, WallT = 0.2f;

    // 시연 자리: 컴공_A 1번 = 오른쪽 열의 왼쪽 줄, 위에서 11번째 칸
    private const string MyColumn = "R1"; private const int MyIndex = 10;

    private struct Strip { public string col, dept; public float x0, y0, y1; public int n; public Color color; }

    public static void Run()
    {
        var ci = CultureInfo.InvariantCulture;
        if (File.Exists(DstScene)) AssetDatabase.DeleteAsset(DstScene);
        if (!AssetDatabase.CopyAsset(SrcScene, DstScene)) { Debug.LogError("[Capstone] 씬 복사 실패"); EditorApplication.Exit(1); return; }
        if (!AssetDatabase.IsValidFolder(AssetDir)) AssetDatabase.CreateFolder("Assets", "capstone_hall");
        var scene = EditorSceneManager.OpenScene(DstScene, OpenSceneMode.Single);

        // ---------- 1) lab 의 가구와 벽을 지운다
        GameObject map = GameObject.Find("Map");
        for (int i = map.transform.childCount - 1; i >= 0; i--)
        {
            Transform c = map.transform.GetChild(i);
            if (c.name == "Directional Light" || c.name == "0,0,0") continue;
            Object.DestroyImmediate(c.gameObject);
        }
        foreach (string w in new[] { "wall1(B)", "wall1(F)", "wall2(L)", "wall2(R)" })
        {
            GameObject g = GameObject.Find(w);
            if (g != null) Object.DestroyImmediate(g);
        }

        // ---------- 2) 바닥과 NavMesh
        GameObject plane = GameObject.Find("Plane");
        Bounds pb0 = plane.GetComponent<Renderer>().bounds;
        Vector3 ps = plane.transform.localScale;
        plane.transform.localScale = new Vector3(ps.x * HallW / pb0.size.x, ps.y, ps.z * HallL / pb0.size.z);
        Bounds pb1 = plane.GetComponent<Renderer>().bounds;
        plane.transform.position += new Vector3(HallW * 0.5f - pb1.center.x, 0f, HallL * 0.5f - pb1.center.z);
        var surface = plane.GetComponent<NavMeshSurface>();
        surface.navMeshData = null;
        surface.BuildNavMesh();
        string navPath = AssetDir + "/NavMesh-CapstoneHall.asset";
        AssetDatabase.DeleteAsset(navPath);
        AssetDatabase.CreateAsset(surface.navMeshData, navPath);

        // ---------- 3) 벽
        Material wallMat = Mat("capstone_wall", new Color(0.55f, 0.55f, 0.58f));
        Box(map.transform, "hall_wall_south", -WallT, HallW + WallT, -WallT, 0f, WallH, wallMat);
        Box(map.transform, "hall_wall_north_잘린경계", -WallT, HallW + WallT, HallL, HallL + WallT, WallH, wallMat);
        Box(map.transform, "hall_wall_west", -WallT, 0f, 0f, HallL, WallH, wallMat);
        Box(map.transform, "hall_wall_east", HallW, HallW + WallT, 0f, HallL, WallH, wallMat);

        // ---------- 4) 전시대 (사진의 생김새대로: 뒷판 + 포스터 + 안내 데스크). CapstoneBooths 가 만든다.
        CapstoneBooths.Build(map.transform, out Bounds myBooth);
        if (myBooth.size.x < 0.1f) { Debug.LogError("[Capstone] 시연 자리를 못 찾음"); EditorApplication.Exit(1); return; }

        // ---------- 5) 로봇·목표·카메라를 시연 자리 앞 통로로 옮긴다
        // 통로: 가운데 열(동쪽 끝 x 14.10)과 오른쪽 열(서쪽 끝 = 시연 자리 앞면) 사이, 폭 약 4.5 m
        float aisleX = myBooth.min.x - 0.90f;                       // 전시대 앞면에서 0.9 m
        Vector3 start = new Vector3(aisleX, 0f, myBooth.center.z);
        GameObject go1 = FindRoot(scene, "go1");
        Vector3 d = new Vector3(start.x - go1.transform.position.x, 0f, start.z - go1.transform.position.z);
        foreach (string n in new[] { "go1", "Player", "GoalPoint", "StartPoint", "CubeLogger", "CubeVizLoader", "Camera" })
        {
            GameObject g = FindRoot(scene, n);
            if (g != null) g.transform.position += d;
        }
        Place(scene, "go1 (1)", new Vector3(aisleX - 1.2f, 0f, myBooth.center.z - 4.0f));
        Place(scene, "Quadcopter_Drone", new Vector3(aisleX - 1.5f, float.NaN, myBooth.center.z + 2.5f));

        // 360 카메라: 시연 자리 전시대의 통로 쪽 모서리 바로 앞 (삼각대). 실제로 세운 자리에 맞춰 옮기면 된다.
        Vector3 cam360 = new Vector3(myBooth.min.x - 0.20f, 0f, myBooth.center.z);
        GameObject anchor = FindRoot(scene, "Anchor360");
        anchor.transform.position = new Vector3(cam360.x, anchor.transform.position.y, cam360.z);
        var recv = anchor.GetComponent<Anchor360ObstacleReceiver>();
        recv.calibrationFileName = CalibName;
        recv.yawOffsetDeg = 0f;
        EditorUtility.SetDirty(recv);
        GameObject anchor2 = FindRoot(scene, "Anchor360 (1)");
        if (anchor2 != null)
        {
            anchor2.transform.position = new Vector3(cam360.x, anchor2.transform.position.y, cam360.z - 6f);
            var r2 = anchor2.GetComponent<Anchor360ObstacleReceiver>();
            if (r2 != null) { r2.calibrationFileName = ""; EditorUtility.SetDirty(r2); }
        }

        // 이 씬 전용 보정 파일: lab 파일의 설정값은 물려받고 카메라 위치·방위만 바꾼다
        string sa = Path.Combine(Application.dataPath, "StreamingAssets");
        string src = File.ReadAllText(Path.Combine(sa, "anchor360_calib.json"), Encoding.UTF8);
        src = ReplaceNumber(src, "anchorX", cam360.x.ToString("F3", ci));
        src = ReplaceNumber(src, "anchorZ", cam360.z.ToString("F3", ci));
        src = ReplaceNumber(src, "yawOffsetDeg", "0.0");
        int brace = src.LastIndexOf('}');
        src = src.Substring(0, brace).TrimEnd() + ",\n  \"note_capstone\": \"캡스톤 발표장(capstone_hall.unity) 전용. 카메라 위치는 배치도에서 잡은 예정 자리이고 yawOffsetDeg 는 0 으로 둔 임시값이다. 현장에 설치한 뒤 위치와 방위를 다시 맞춰야 한다. 위의 note/note_1124 는 lab 에서 물려받은 설명이다.\"\n}\n";
        File.WriteAllText(Path.Combine(sa, CalibName), src, new UTF8Encoding(false));

        src = ReplaceNumber(src, "camH", CapstoneCamera360Setup.LensHeight.ToString("F2", ci));
        File.WriteAllText(Path.Combine(sa, CalibName), src, new UTF8Encoding(false));
        // 바닥 삼각대(렌즈 높이 1.5 m)로 내리고 삼각대를 그린다
        CapstoneCamera360Setup.Apply(scene);

        EditorSceneManager.MarkSceneDirty(scene);
        bool ok = EditorSceneManager.SaveScene(scene);
        AssetDatabase.SaveAssets();

        // ---------- 6) 확인용 출력
        string outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "capstone_map");
        Directory.CreateDirectory(outDir);
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        Bounds nb = new Bounds();
        for (int i = 0; i < tri.vertices.Length; i++) { if (i == 0) nb = new Bounds(tri.vertices[0], Vector3.zero); else nb.Encapsulate(tri.vertices[i]); }
        Vector3 goal = FindRoot(scene, "GoalPoint").transform.position;
        Debug.Log("[Capstone] 저장 " + (ok ? "OK" : "실패") + " | 바닥 " + HallW + " x " + HallL + " m | NavMesh 꼭짓점 " + tri.vertices.Length +
                  " x[" + nb.min.x.ToString("F2", ci) + "~" + nb.max.x.ToString("F2", ci) + "] z[" + nb.min.z.ToString("F2", ci) + "~" + nb.max.z.ToString("F2", ci) + "]" +
                  " | 시연 자리 x[" + myBooth.min.x.ToString("F2", ci) + "~" + myBooth.max.x.ToString("F2", ci) + "] z[" + myBooth.min.z.ToString("F2", ci) + "~" + myBooth.max.z.ToString("F2", ci) + "]" +
                  " | 로봇 시작 (" + start.x.ToString("F2", ci) + ", " + start.z.ToString("F2", ci) + ") yaw " + go1.transform.eulerAngles.y.ToString("F0", ci) +
                  " | 목표 (" + goal.x.ToString("F2", ci) + ", " + goal.z.ToString("F2", ci) + ")" +
                  " | 360 카메라 (" + cam360.x.ToString("F2", ci) + ", " + cam360.z.ToString("F2", ci) + ") 높이 " + anchor.transform.position.y.ToString("F2", ci));
        try
        {
            Shot(Path.Combine(outDir, "capstone_hall_top.png"), new Vector3(HallW * 0.5f, 60f, HallL * 0.5f), HallL * 0.5f + 0.5f, 1100, 1700);
            Shot(Path.Combine(outDir, "capstone_hall_demo_area.png"), new Vector3(start.x - 0.6f, 60f, start.z - 1.0f), 5.0f, 1400, 1400);
        }
        catch (System.Exception e) { Debug.LogWarning("[Capstone] 확인용 그림 실패: " + e.Message); }
        if (!ok) EditorApplication.Exit(1);
    }

    private static GameObject FindRoot(UnityEngine.SceneManagement.Scene scene, string name)
    {
        foreach (GameObject g in scene.GetRootGameObjects()) if (g.name == name) return g;
        return null;
    }

    private static void Place(UnityEngine.SceneManagement.Scene scene, string name, Vector3 p)
    {
        GameObject g = FindRoot(scene, name);
        if (g == null) return;
        g.transform.position = new Vector3(p.x, float.IsNaN(p.y) ? g.transform.position.y : p.y, p.z);
    }

    private static Material Mat(string name, Color c)
    {
        string path = AssetDir + "/" + name + ".mat";
        Material m = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (m == null)
        {
            Shader sh = Shader.Find("Universal Render Pipeline/Lit");
            if (sh == null) sh = Shader.Find("Standard");
            m = new Material(sh);
            AssetDatabase.CreateAsset(m, path);
        }
        m.color = c;
        if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", c);
        EditorUtility.SetDirty(m);
        return m;
    }

    // 바닥에 선 상자 하나: 충돌체 + 태그 Obstacle + 실행 중 NavMesh 를 파내는 NavMeshObstacle (lab 의 벽·가구와 같은 구성)
    private static GameObject Box(Transform parent, string name, float x0, float x1, float z0, float z1, float h, Material m)
    {
        GameObject g = GameObject.CreatePrimitive(PrimitiveType.Cube);
        g.name = name;
        g.transform.SetParent(parent, false);
        g.transform.position = new Vector3((x0 + x1) * 0.5f, h * 0.5f, (z0 + z1) * 0.5f);
        g.transform.localScale = new Vector3(Mathf.Abs(x1 - x0), h, Mathf.Abs(z1 - z0));
        g.tag = "Obstacle";
        g.GetComponent<Renderer>().sharedMaterial = m;
        var o = g.AddComponent<NavMeshObstacle>();
        o.shape = NavMeshObstacleShape.Box; o.center = Vector3.zero; o.size = Vector3.one; o.carving = true;
        return g;
    }

    private static string ReplaceNumber(string json, string key, string value)
    {
        return System.Text.RegularExpressions.Regex.Replace(json, "(\"" + key + "\"\\s*:\\s*)[-0-9.eE]+", "${1}" + value);
    }

    private static void Shot(string path, Vector3 pos, float orthoHalfHeight, int w, int h)
    {
        var go = new GameObject("tmp_shot_cam");
        var cam = go.AddComponent<Camera>();
        cam.orthographic = true; cam.orthographicSize = orthoHalfHeight;
        cam.transform.position = pos; cam.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
        cam.nearClipPlane = 0.1f; cam.farClipPlane = 200f; cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.12f, 0.12f, 0.14f);
        var rt = new RenderTexture(w, h, 24);
        cam.targetTexture = rt; cam.Render();
        RenderTexture.active = rt;
        var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, w, h), 0, 0); tex.Apply();
        File.WriteAllBytes(path, tex.EncodeToPNG());
        RenderTexture.active = null; cam.targetTexture = null;
        Object.DestroyImmediate(go); Object.DestroyImmediate(rt); Object.DestroyImmediate(tex);
    }
}
