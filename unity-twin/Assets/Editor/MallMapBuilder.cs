// 쇼핑몰 디지털 트윈 맵을 새 씬으로 만든다. 기존 lab.unity, capstone_hall.unity 는 건드리지 않는다.
//   Unity.exe -batchmode -projectPath D:\Go1_Unity -executeMethod MallMapBuilder.Run -logFile <log>     (-nographics 없이: 확인용 그림을 그린다)
//
// 만드는 것
//   Assets/mall.unity                            lab.unity 를 복사한 뒤 가구·벽을 지우고 쇼핑몰로 바꾼 씬 (로봇·통신·탐지 구성은 그대로)
//   Assets/mall/NavMesh-Mall.asset               새 바닥으로 구운 NavMesh (진열대는 lab 과 같이 실행 중에 파낸다)
//   Assets/StreamingAssets/anchor360_calib_mall.json   이 씬 전용 360 카메라 설정 (천장 2.5 m)
//   GO1_Proactive_Evaluation/mall_map/mall_top.png 등
//
// 모형: Assets/KenneyMiniMarket (Kenney "Mini Market" 2.1, CC0). 작은 모형이라 2.2배로 키워 실제 크기에 맞춘다
//       (직원 모형 키 0.72 → 1.59 m, 진열대 높이 0.89 → 1.96 m).
// 실제 건물을 잰 것이 아니라 가상의 배치다. 좌표: 왼쪽 아래 모서리가 원점, +X = 동쪽, +Z = 북쪽, 단위 m.
//   북쪽(z 11~18)  마트: 진열대 4줄(통로 폭 약 1.85 m) + 신선 코너 + 계산대
//   가운데(z 7~11) 복도: 폭 4 m, 가운데 판매대 2개
//   남쪽(z 0~7)    매장 3칸: 옷 가게 / 잡화점 / 빵집 (입구 폭 3 m)

using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Unity.AI.Navigation;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.AI;

public static class MallMapBuilder
{
    private const string SrcScene = "Assets/lab.unity", DstScene = "Assets/mall.unity", AssetDir = "Assets/mall", KitDir = "Assets/KenneyMiniMarket";
    private const string CalibName = "anchor360_calib_mall.json";
    public const float W = 26f, L = 18f, WallH = 3.5f, WallT = 0.2f, S = 2.2f, CamH = 2.5f;
    private static readonly List<string> rows = new List<string>();
    private static readonly CultureInfo ci = CultureInfo.InvariantCulture;

    public static void Run()
    {
        rows.Clear();
        if (File.Exists(DstScene)) AssetDatabase.DeleteAsset(DstScene);
        if (!AssetDatabase.CopyAsset(SrcScene, DstScene)) { Debug.LogError("[Mall] 씬 복사 실패"); EditorApplication.Exit(1); return; }
        if (!AssetDatabase.IsValidFolder(AssetDir)) AssetDatabase.CreateFolder("Assets", "mall");
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
        plane.transform.localScale = new Vector3(ps.x * W / pb0.size.x, ps.y, ps.z * L / pb0.size.z);
        Bounds pb1 = plane.GetComponent<Renderer>().bounds;
        plane.transform.position += new Vector3(W * 0.5f - pb1.center.x, 0f, L * 0.5f - pb1.center.z);
        var surface = plane.GetComponent<NavMeshSurface>();
        surface.navMeshData = null;
        surface.BuildNavMesh();
        string navPath = AssetDir + "/NavMesh-Mall.asset";
        AssetDatabase.DeleteAsset(navPath);
        AssetDatabase.CreateAsset(surface.navMeshData, navPath);

        Transform mall = new GameObject("Mall").transform;
        mall.SetParent(map.transform, false);

        // ---------- 3) 벽과 칸막이
        Material wallMat = Mat("mall_wall", new Color(0.86f, 0.85f, 0.82f));
        Material frontMat = Mat("mall_shopfront", new Color(0.30f, 0.33f, 0.40f));
        Box(mall, "mall_wall_south", -WallT, W + WallT, -WallT, 0f, WallH, wallMat);
        Box(mall, "mall_wall_north", -WallT, W + WallT, L, L + WallT, WallH, wallMat);
        Box(mall, "mall_wall_west", -WallT, 0f, 0f, L, WallH, wallMat);
        Box(mall, "mall_wall_east", W, W + WallT, 0f, L, WallH, wallMat);
        // 매장 사이 칸막이
        Box(mall, "shop_partition_AB", 8.4f, 8.6f, 0f, 7.0f, WallH, wallMat);
        Box(mall, "shop_partition_BC", 17.4f, 17.6f, 0f, 7.0f, WallH, wallMat);
        // 매장 앞면 (입구 3 m 를 비운다)
        float[] fronts = { 0f, 2.75f, 5.75f, 11.5f, 14.5f, 20.25f, 23.25f, 26f };
        for (int i = 0; i < fronts.Length; i += 2)
            Box(mall, "shop_front_" + (i / 2), fronts[i], fronts[i + 1], 6.9f, 7.1f, WallH, frontMat);

        // ---------- 4) 바닥 색 (구역 구분용, 장애물 아님)
        Tile(mall, "floor_tile_mart", 0f, W, 11f, L, Mat("mall_floor_mart", new Color(0.80f, 0.86f, 0.90f)));
        Tile(mall, "floor_tile_shopA", 0f, 8.4f, 0f, 6.9f, Mat("mall_floor_A", new Color(0.86f, 0.78f, 0.66f)));
        Tile(mall, "floor_tile_shopB", 8.6f, 17.4f, 0f, 6.9f, Mat("mall_floor_B", new Color(0.90f, 0.86f, 0.62f)));
        Tile(mall, "floor_tile_shopC", 17.6f, W, 0f, 6.9f, Mat("mall_floor_C", new Color(0.72f, 0.84f, 0.70f)));

        // ---------- 5) 마트 (북쪽)
        float[] rowX = { 2.6f, 6.0f, 9.4f, 12.8f };
        for (int r = 0; r < rowX.Length; r++)
        {
            Prop(mall, r % 2 == 0 ? "shelf-bags" : "shelf-boxes", rowX[r], 13.60f, 90f);
            Prop(mall, r % 2 == 0 ? "shelf-boxes" : "shelf-bags", rowX[r], 15.36f, 90f);
        }
        // 신선 코너: 판매대 3개 + 뒷벽 냉장 진열장 4개
        Prop(mall, "display-fruit", 17.0f, 14.7f, 0f);
        Prop(mall, "display-cans", 20.3f, 14.7f, 0f);
        Prop(mall, "display-flowers", 23.6f, 14.7f, 0f);
        for (int i = 0; i < 4; i++) Prop(mall, "freezers-standing", 16.9f + 2.2f * i, 17.45f, 180f);
        // 계산대
        Prop(mall, "cash-register", 16.5f, 12.0f, 0f);
        Prop(mall, "cash-register", 20.5f, 12.0f, 0f);
        Prop(mall, "cash-register-self", 24.2f, 11.8f, 0f);
        Prop(mall, "character-employee", 15.0f, 12.0f, 90f, false);      // 계산대 뒤 직원 (통로 밖, 장식)

        // ---------- 6) 복도 (가운데)
        Prop(mall, "display-fruit", 9.5f, 9.0f, 0f);
        Prop(mall, "display-flowers", 18.0f, 9.0f, 0f);
        for (int i = 0; i < 3; i++) Prop(mall, "shopping-cart", 0.9f + 0.9f * i, 10.35f, 0f);
        Prop(mall, "bottle-return", 25.45f, 8.4f, 270f);
        Prop(mall, "bottle-return", 25.45f, 9.6f, 270f);
        // 기둥 (매장 앞면 벽에 붙은 것)
        foreach (float cx in new[] { 8.5f, 17.5f })
            Prop(mall, "column", cx, 7.35f, 0f, true, new Vector3(0.4f, WallH / (1.0f * S), 0.4f));

        // ---------- 7) 매장 A: 옷 가게
        Prop(mall, "clothing-rack", 2.0f, 1.2f, 0f);
        Prop(mall, "clothing-rack", 5.0f, 1.2f, 0f);
        Prop(mall, "clothing-rack", 7.2f, 3.5f, 90f);
        Prop(mall, "clothing-table", 4.2f, 3.9f, 0f);
        Prop(mall, "mannequin", 1.0f, 6.1f, 0f);
        Prop(mall, "mannequin", 7.5f, 6.1f, 0f);

        // ---------- 8) 매장 B: 잡화점
        for (int i = 0; i < 3; i++) Prop(mall, "gacha-machine", 10.0f + 1.1f * i, 0.6f, 0f);
        Prop(mall, "shelf-boxes", 13.0f, 3.4f, 0f);
        Prop(mall, "display-small", 9.2f, 3.0f, 90f);
        Prop(mall, "display-small", 9.2f, 4.2f, 90f);
        Prop(mall, "cash-register-self", 16.2f, 1.5f, 90f);
        Prop(mall, "freezer", 15.8f, 5.0f, 90f);

        // ---------- 9) 매장 C: 빵집
        Prop(mall, "display-bread", 19.5f, 3.6f, 0f);
        Prop(mall, "display-bread", 22.5f, 3.6f, 0f);
        Prop(mall, "shelf-bags", 24.5f, 1.2f, 0f);
        Prop(mall, "cash-register", 19.2f, 1.2f, 180f);
        Prop(mall, "hand-truck", 25.2f, 5.6f, 0f);
        Prop(mall, "shopping-basket", 18.2f, 6.2f, 0f);

        // ---------- 10) 로봇·목표·카메라
        Vector3 start = new Vector3(3.0f, 0f, 9.0f);
        GameObject go1 = FindRoot(scene, "go1");
        Vector3 d = new Vector3(start.x - go1.transform.position.x, 0f, start.z - go1.transform.position.z);
        foreach (string n in new[] { "go1", "Player", "GoalPoint", "StartPoint", "CubeLogger", "CubeVizLoader", "Camera" })
        {
            GameObject g = FindRoot(scene, n);
            if (g != null) g.transform.position += d;
        }
        Place(scene, "GoalPoint", new Vector3(13.5f, float.NaN, 9.9f));
        Place(scene, "go1 (1)", new Vector3(2.0f, 0f, 7.8f));
        Place(scene, "Quadcopter_Drone", new Vector3(5.0f, float.NaN, 8.0f));

        // 360 카메라: 복도 가운데 천장에 매단다 (바닥에 아무것도 두지 않는다)
        Vector3 cam360 = new Vector3(13.0f, CamH, 9.0f);
        GameObject anchor = FindRoot(scene, "Anchor360");
        anchor.transform.position = cam360;
        var recv = anchor.GetComponent<Anchor360ObstacleReceiver>();
        recv.calibrationFileName = CalibName;
        recv.yawOffsetDeg = 0f;
        EditorUtility.SetDirty(recv);
        // lab 에서 딸려 온 바닥 삼각대 모형은 끈다 (여기서는 천장에 매단다)
        foreach (Transform t in anchor.GetComponentsInChildren<Transform>(true))
            if (t.name == "Tripod") t.gameObject.SetActive(false);
        GameObject rod = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        rod.name = "ceiling_rod_360";
        Object.DestroyImmediate(rod.GetComponent<Collider>());
        rod.transform.SetParent(anchor.transform, true);
        float rodLen = WallH - CamH - 0.08f;
        rod.transform.position = new Vector3(cam360.x, CamH + 0.08f + rodLen * 0.5f, cam360.z);
        rod.transform.rotation = Quaternion.identity;
        SetWorldScale(rod.transform, new Vector3(0.04f, rodLen * 0.5f, 0.04f));
        rod.GetComponent<Renderer>().sharedMaterial = Mat("mall_rod", new Color(0.12f, 0.12f, 0.13f));
        GameObject anchor2 = FindRoot(scene, "Anchor360 (1)");
        if (anchor2 != null)
        {
            anchor2.transform.position = new Vector3(21.0f, anchor2.transform.position.y, 9.0f);
            var r2 = anchor2.GetComponent<Anchor360ObstacleReceiver>();
            if (r2 != null) { r2.calibrationFileName = ""; EditorUtility.SetDirty(r2); }
        }

        // 이 씬 전용 설정 파일: lab 파일의 값은 물려받고 카메라 위치·높이·범위만 바꾼다
        string sa = Path.Combine(Application.dataPath, "StreamingAssets");
        string src = File.ReadAllText(Path.Combine(sa, "anchor360_calib.json"), Encoding.UTF8);
        src = ReplaceNumber(src, "anchorX", cam360.x.ToString("F3", ci));
        src = ReplaceNumber(src, "anchorZ", cam360.z.ToString("F3", ci));
        src = ReplaceNumber(src, "yawOffsetDeg", "0.0");
        src = ReplaceNumber(src, "camH", CamH.ToString("F2", ci));
        src = ReplaceNumber(src, "range360M", "6.0");
        int brace = src.LastIndexOf('}');
        src = src.Substring(0, brace).TrimEnd() + ",\n  \"note_mall\": \"쇼핑몰 맵(mall.unity) 전용. 가상의 배치라 실제 카메라와 맞춘 값이 아니다. 카메라는 복도 가운데 천장 2.5 m, 탐지 범위 6 m 로 두었다. 위의 note 들은 lab 에서 물려받은 설명이다.\"\n}\n";
        File.WriteAllText(Path.Combine(sa, CalibName), src, new UTF8Encoding(false));

        EditorSceneManager.MarkSceneDirty(scene);
        bool ok = EditorSceneManager.SaveScene(scene);
        AssetDatabase.SaveAssets();

        // ---------- 11) 확인용 출력
        string outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "mall_map");
        Directory.CreateDirectory(outDir);
        File.WriteAllText(Path.Combine(outDir, "props.csv"), "name,minX,maxX,minZ,maxZ,height,obstacle\n" + string.Join("\n", rows) + "\n", new UTF8Encoding(false));
        Vector3 goal = FindRoot(scene, "GoalPoint").transform.position;
        Debug.Log("[Mall] 저장 " + (ok ? "OK" : "실패") + " | 바닥 " + W + " x " + L + " m | 모형 " + rows.Count + "개 | 로봇 시작 (" + start.x.ToString("F2", ci) + ", " + start.z.ToString("F2", ci) +
                  ") yaw " + go1.transform.eulerAngles.y.ToString("F0", ci) + " | 목표 (" + goal.x.ToString("F2", ci) + ", " + goal.z.ToString("F2", ci) +
                  ") | 360 카메라 (" + cam360.x.ToString("F2", ci) + ", " + cam360.z.ToString("F2", ci) + ") 높이 " + anchor.transform.position.y.ToString("F2", ci));
        try { Shots(outDir); }
        catch (System.Exception e) { Debug.LogWarning("[Mall] 확인용 그림 실패: " + e.Message); }
        if (!ok) EditorApplication.Exit(1);
    }

    // 저장된 씬으로 확인용 그림만 다시 그린다
    public static void ShotsOnly()
    {
        EditorSceneManager.OpenScene(DstScene, OpenSceneMode.Single);
        string outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "mall_map");
        Directory.CreateDirectory(outDir);
        Shots(outDir);
    }

    public static void Shots(string outDir)
    {
        Shot(Path.Combine(outDir, "mall_top.png"), new Vector3(W * 0.5f, 60f, L * 0.5f), Quaternion.Euler(90f, 0f, 0f), true, L * 0.5f + 0.5f, 1900, 1360);
        Shot(Path.Combine(outDir, "mall_bird.png"), new Vector3(-6f, 16f, -9f), Quaternion.LookRotation(new Vector3(13f, 0f, 9f) - new Vector3(-6f, 16f, -9f)), false, 50f, 1900, 1200);
        Shot(Path.Combine(outDir, "mall_corridor.png"), new Vector3(0.6f, 1.6f, 9.0f), Quaternion.LookRotation(new Vector3(1f, -0.12f, 0f)), false, 70f, 1900, 1100);
        Shot(Path.Combine(outDir, "mall_mart.png"), new Vector3(15.0f, 5.5f, 9.5f), Quaternion.LookRotation(new Vector3(8f, 0.5f, 15f) - new Vector3(15.0f, 5.5f, 9.5f)), false, 65f, 1900, 1100);
        Shot(Path.Combine(outDir, "mall_shops.png"), new Vector3(13f, 7.5f, 13.5f), Quaternion.LookRotation(new Vector3(13f, 0.5f, 3.5f) - new Vector3(13f, 7.5f, 13.5f)), false, 75f, 1900, 1100);
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

    private static void SetWorldScale(Transform t, Vector3 world)
    {
        Vector3 p = t.parent != null ? t.parent.lossyScale : Vector3.one;
        t.localScale = new Vector3(world.x / p.x, world.y / p.y, world.z / p.z);
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

    private static void Tile(Transform parent, string name, float x0, float x1, float z0, float z1, Material m)
    {
        GameObject g = GameObject.CreatePrimitive(PrimitiveType.Cube);
        g.name = name;
        Object.DestroyImmediate(g.GetComponent<Collider>());
        g.transform.SetParent(parent, false);
        g.transform.position = new Vector3((x0 + x1) * 0.5f, 0.003f, (z0 + z1) * 0.5f);
        g.transform.localScale = new Vector3(Mathf.Abs(x1 - x0), 0.006f, Mathf.Abs(z1 - z0));
        g.GetComponent<Renderer>().sharedMaterial = m;
    }

    // 매장 모형 하나를 바닥에 놓는다. (x, z) = 모형이 차지하는 자리의 가운데. 장애물이면 자리 크기만 한 충돌 상자와 NavMesh 파내기를 단다.
    private static GameObject Prop(Transform parent, string model, float x, float z, float yaw, bool obstacle = true, Vector3? scaleMul = null)
    {
        GameObject src = AssetDatabase.LoadAssetAtPath<GameObject>(KitDir + "/" + model + ".fbx");
        if (src == null) { Debug.LogError("[Mall] 모형 없음: " + model); return null; }
        GameObject g = (GameObject)PrefabUtility.InstantiatePrefab(src);
        g.name = "mall_" + model;
        g.transform.SetParent(parent, false);
        Vector3 mul = scaleMul ?? Vector3.one;
        g.transform.localScale = Vector3.Scale(g.transform.localScale, new Vector3(S * mul.x, S * mul.y, S * mul.z));
        g.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);

        // 가져온 모형에 색 그림이 연결되지 않아 흰색으로 나온다 → 색 그림(colormap)을 쓴 재질 하나를 모든 모형에 입힌다
        Material kit = KitMat();
        foreach (Renderer r in g.GetComponentsInChildren<Renderer>(true))
        {
            Material[] ms = r.sharedMaterials;
            for (int i = 0; i < ms.Length; i++) ms[i] = kit;
            r.sharedMaterials = ms;
        }

        // 회전하기 전(축에 나란할 때)의 크기로 충돌 상자를 잡는다
        Bounds b0 = RBounds(g);
        if (obstacle)
        {
            var bc = g.AddComponent<BoxCollider>();
            Vector3 ls = g.transform.lossyScale;
            bc.center = new Vector3(b0.center.x / ls.x, b0.center.y / ls.y, b0.center.z / ls.z);
            bc.size = new Vector3(b0.size.x / ls.x, b0.size.y / ls.y, b0.size.z / ls.z);
            g.tag = "Obstacle";
            var o = g.AddComponent<NavMeshObstacle>();
            o.shape = NavMeshObstacleShape.Box; o.center = bc.center; o.size = bc.size; o.carving = true;
        }
        g.transform.rotation = Quaternion.Euler(0f, yaw, 0f);
        Bounds b1 = RBounds(g);
        g.transform.position = new Vector3(x - b1.center.x, -b1.min.y, z - b1.center.z);
        Bounds b = RBounds(g);
        rows.Add(g.name + "," + b.min.x.ToString("F2", ci) + "," + b.max.x.ToString("F2", ci) + "," + b.min.z.ToString("F2", ci) + "," + b.max.z.ToString("F2", ci) + "," +
                 b.size.y.ToString("F2", ci) + "," + (obstacle ? 1 : 0));
        return g;
    }

    private static Material kitMat;
    private static Material KitMat()
    {
        if (kitMat != null) return kitMat;
        kitMat = Mat("mall_kit_colormap", Color.white);
        Texture2D tex = AssetDatabase.LoadAssetAtPath<Texture2D>(KitDir + "/Textures/colormap.png");
        if (tex == null) Debug.LogWarning("[Mall] colormap.png 없음 → 모형이 흰색으로 나온다");
        else { kitMat.SetTexture("_BaseMap", tex); kitMat.mainTexture = tex; }
        kitMat.SetFloat("_Smoothness", 0.15f);
        EditorUtility.SetDirty(kitMat);
        return kitMat;
    }

    private static Bounds RBounds(GameObject g)
    {
        Bounds b = new Bounds(g.transform.position, Vector3.zero); bool first = true;
        foreach (Renderer r in g.GetComponentsInChildren<Renderer>(true)) { if (first) { b = r.bounds; first = false; } else b.Encapsulate(r.bounds); }
        return b;
    }

    private static string ReplaceNumber(string json, string key, string value)
    {
        return System.Text.RegularExpressions.Regex.Replace(json, "(\"" + key + "\"\\s*:\\s*)[-0-9.eE]+", "${1}" + value);
    }

    private static void Shot(string path, Vector3 pos, Quaternion rot, bool ortho, float sizeOrFov, int w, int h)
    {
        var go = new GameObject("tmp_shot_cam");
        var cam = go.AddComponent<Camera>();
        cam.orthographic = ortho;
        if (ortho) cam.orthographicSize = sizeOrFov; else cam.fieldOfView = sizeOrFov;
        cam.transform.SetPositionAndRotation(pos, rot);
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
