// 캡스톤 발표장 전시대를 사진("각 칸 생김새.jpg")의 생김새대로 만든다.
//   한 칸 = 흰 뒷판(폭 1 m, 높이 2.4 m, 알루미늄 기둥) + 포스터 + 조명 + 안내 데스크(폭 1 m, 깊이 0.5 m, 높이 0.75 m, 흰 몸통에 파란 상판)
//   두 줄이 뒷판을 맞대고 등지고 선다. 배치도의 한 칸(1 m x 1 m) 중 뒷판 쪽 0.5 m 가 데스크이고 앞쪽 0.5 m 는 서는 자리(바닥 색 타일)다.
// 치수는 사진에서 본 조립식 전시 부스의 표준 규격(판 1 m, 안내 데스크 1.0 x 0.5 x 0.75 m)으로 잡았다. 현장 실측값이 아니다.
//
// 에디터에서 capstone_hall 씬이 열려 있고 전시대가 예전(상자 하나) 모양이면 한 번 자동으로 바꾸고 저장한다.
// 메뉴: Tools/Go1/캡스톤 전시대 다시 만들기

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.AI;

[InitializeOnLoad]
public static class CapstoneBooths
{
    public const float PxPerM = 44.67f, OriginPxX = 303f, OriginPxY = 1735f;
    public const float DeskDepth = 0.5f, DeskH = 0.75f, PanelH = 2.4f, PanelT = 0.04f;
    public const string AssetDir = "Assets/capstone_hall", Marker = "detail_v2";
    // 시연 자리: 컴공_A 1번 = 오른쪽 열의 왼쪽 줄, 위에서 11번째 칸
    private const string MyColumn = "R1"; private const int MyIndex = 10;

    private struct Strip { public string col, dept; public float x0, spine, y0, y1; public int n; public Color color; }

    static CapstoneBooths()
    {
        if (Application.isBatchMode) return;
        EditorApplication.delayCall += () =>
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return;
            var scene = EditorSceneManager.GetActiveScene();
            if (scene.name != "capstone_hall") return;
            GameObject map = GameObject.Find("Map");
            if (map == null) return;
            Transform old = map.transform.Find("Booths");
            if (old != null && old.Find(Marker) != null) return;
            Build(map.transform, out _);
            EditorSceneManager.SaveScene(scene);
            AssetDatabase.SaveAssets();
            try { Shots(); } catch (System.Exception e) { Debug.LogWarning("[CapstoneBooths] 그림 실패: " + e.Message); }
        };
    }

    // 창 없이: Unity.exe -batchmode -quit -projectPath D:\Go1_Unity -executeMethod CapstoneBooths.RunBatch -logFile <log>
    // 씬의 다른 부분(로봇·카메라 위치 등 손으로 고친 것)은 건드리지 않고 전시대만 다시 만든다.
    public static void RunBatch()
    {
        var scene = EditorSceneManager.OpenScene("Assets/capstone_hall.unity", OpenSceneMode.Single);
        GameObject map = GameObject.Find("Map");
        Build(map.transform, out _);
        EditorSceneManager.MarkSceneDirty(scene);
        bool ok = EditorSceneManager.SaveScene(scene);
        AssetDatabase.SaveAssets();
        Debug.Log("[CapstoneBooths] 저장 " + (ok ? "OK" : "실패"));
        try { Shots(); } catch (System.Exception e) { Debug.LogWarning("[CapstoneBooths] 그림 실패: " + e.Message); }
    }

    [MenuItem("Tools/Go1/캡스톤 전시대 다시 만들기")]
    private static void Menu()
    {
        GameObject map = GameObject.Find("Map");
        if (map == null) return;
        Build(map.transform, out _);
        EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
        try { Shots(); } catch (System.Exception e) { Debug.LogWarning("[CapstoneBooths] 그림 실패: " + e.Message); }
    }

    public static Material Mat(string name, Color c)
    {
        if (!AssetDatabase.IsValidFolder(AssetDir)) AssetDatabase.CreateFolder("Assets", "capstone_hall");
        string path = AssetDir + "/" + name + ".mat";
        Material m = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (m == null)
        {
            Shader sh = Shader.Find("Universal Render Pipeline/Lit");
            m = new Material(sh != null ? sh : Shader.Find("Standard"));
            AssetDatabase.CreateAsset(m, path);
        }
        m.color = c;
        if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", c);
        EditorUtility.SetDirty(m);
        return m;
    }

    /// <summary>Map 아래에 Booths 를 새로 만든다. myCell = 시연 자리(컴공A 1) 한 칸의 바닥 범위.</summary>
    public static void Build(Transform map, out Bounds myCell)
    {
        var ci = CultureInfo.InvariantCulture;
        Transform old = map.Find("Booths");
        if (old != null) Object.DestroyImmediate(old.gameObject);
        GameObject booths = new GameObject("Booths");
        booths.transform.SetParent(map, false);
        new GameObject(Marker).transform.SetParent(booths.transform, false);

        Color pink = new Color(0.96f, 0.78f, 0.86f), blue = new Color(0.67f, 0.84f, 0.95f), yellow = new Color(0.98f, 0.93f, 0.45f),
              purple = new Color(0.70f, 0.67f, 0.85f), olive = new Color(0.83f, 0.87f, 0.45f), green = new Color(0.56f, 0.79f, 0.52f),
              orange = new Color(0.98f, 0.78f, 0.47f);
        Strip[] strips =
        {
            new Strip { col = "L1", dept = "정보", x0 = 553, spine = 598, y0 = 527, y1 = 1556, n = 23, color = pink },
            new Strip { col = "L2", dept = "정보", x0 = 598, spine = 598, y0 = 527, y1 = 795, n = 6, color = pink },
            new Strip { col = "L2", dept = "전자", x0 = 598, spine = 598, y0 = 840, y1 = 1556, n = 16, color = blue },
            new Strip { col = "M1", dept = "전자", x0 = 843, spine = 888, y0 = 700, y1 = 1235, n = 12, color = blue },
            new Strip { col = "M2", dept = "모바일", x0 = 888, spine = 888, y0 = 700, y1 = 967.5f, n = 6, color = yellow },
            new Strip { col = "M2", dept = "인공지능", x0 = 888, spine = 888, y0 = 967.5f, y1 = 1235, n = 6, color = purple },
            new Strip { col = "R1", dept = "컴공A", x0 = 1134, spine = 1179, y0 = 484, y1 = 975.3f, n = 11, color = olive },
            new Strip { col = "R1", dept = "컴공B", x0 = 1134, spine = 1179, y0 = 975.3f, y1 = 1556, n = 13, color = green },
            new Strip { col = "R2", dept = "컴공A", x0 = 1179, spine = 1179, y0 = 484, y1 = 528.7f, n = 1, color = olive },
            new Strip { col = "R2", dept = "지능", x0 = 1179, spine = 1179, y0 = 528.7f, y1 = 841.3f, n = 7, color = orange },
            new Strip { col = "R2", dept = "전기", x0 = 1179, spine = 1179, y0 = 841.3f, y1 = 1556, n = 16, color = purple },
        };

        Material mPanel = Mat("capstone_panel_white", new Color(0.95f, 0.95f, 0.96f));
        Material mDesk = Mat("capstone_desk_white", new Color(0.90f, 0.90f, 0.91f));
        Material mTop = Mat("capstone_desk_top_blue", new Color(0.13f, 0.28f, 0.72f));
        Material mAlu = Mat("capstone_aluminium", new Color(0.72f, 0.74f, 0.77f));
        Material mPaper = Mat("capstone_poster_paper", new Color(0.99f, 0.99f, 0.97f));
        Material mPosterY = Mat("capstone_poster_yellow", new Color(0.98f, 0.80f, 0.12f));
        Material mPosterP = Mat("capstone_poster_purple", new Color(0.42f, 0.22f, 0.62f));
        Material mLamp = Mat("capstone_lamp", new Color(1.0f, 0.97f, 0.85f));
        Material mMine = Mat("capstone_booth_mine", new Color(0.90f, 0.15f, 0.15f));

        var csv = new StringBuilder("name,dept,cell_min_x,cell_max_x,cell_min_z,cell_max_z,desk_min_x,desk_max_x\n");
        var counter = new System.Collections.Generic.Dictionary<string, int>();
        myCell = new Bounds();
        int count = 0;
        foreach (Strip s in strips)
        {
            Material mTile = Mat("capstone_booth_" + s.dept, s.color);
            float cell = (s.y1 - s.y0) / s.n;
            float spineX = (s.spine - OriginPxX) / PxPerM;
            float side = s.x0 < s.spine ? -1f : 1f;                     // 뒷판에서 통로 쪽 방향
            for (int i = 0; i < s.n; i++)
            {
                counter.TryGetValue(s.col, out int idx);
                counter[s.col] = idx + 1;
                float zb = (OriginPxY - (s.y0 + cell * i)) / PxPerM, za = (OriginPxY - (s.y0 + cell * (i + 1))) / PxPerM;
                float zc = (za + zb) * 0.5f, zw = zb - za;
                bool isMine = s.col == MyColumn && idx == MyIndex;
                string name = isMine ? "booth_컴공A_1_시연자리" : "booth_" + s.col + "_" + idx.ToString("00") + "_" + s.dept;
                var root = new GameObject(name);
                root.transform.SetParent(booths.transform, false);
                root.transform.position = new Vector3(spineX + side * 0.5f, 0f, zc);

                // 바닥 타일(한 칸 1 m x 1 m): 학과 색. 장애물이 아니다.
                float cx0 = Mathf.Min(spineX, spineX + side), cx1 = Mathf.Max(spineX, spineX + side);
                Part(root.transform, "floor_tile", new Vector3(spineX + side * 0.5f, 0.004f, zc), new Vector3(1f - 0.02f, 0.008f, zw - 0.02f), isMine ? mMine : mTile, false);
                // 뒷판
                Part(root.transform, "panel", new Vector3(spineX + side * PanelT * 0.5f, PanelH * 0.5f, zc), new Vector3(PanelT, PanelH, zw - 0.04f), mPanel, true);
                // 알루미늄 기둥(칸 경계)과 윗테
                Part(root.transform, "post", new Vector3(spineX + side * PanelT * 0.5f, (PanelH + 0.05f) * 0.5f, zb), new Vector3(0.05f, PanelH + 0.05f, 0.04f), mAlu, false);
                if (i == s.n - 1) Part(root.transform, "post_end", new Vector3(spineX + side * PanelT * 0.5f, (PanelH + 0.05f) * 0.5f, za), new Vector3(0.05f, PanelH + 0.05f, 0.04f), mAlu, false);
                Part(root.transform, "top_rail", new Vector3(spineX + side * PanelT * 0.5f, PanelH + 0.025f, zc), new Vector3(0.05f, 0.05f, zw), mAlu, false);
                // 안내 데스크: 흰 몸통 + 파란 상판
                float dx = spineX + side * (PanelT + DeskDepth * 0.5f);
                Part(root.transform, "desk", new Vector3(dx, (DeskH - 0.03f) * 0.5f, zc), new Vector3(DeskDepth, DeskH - 0.03f, zw - 0.01f), mDesk, true);
                Part(root.transform, "desk_top", new Vector3(dx, DeskH - 0.015f, zc), new Vector3(DeskDepth + 0.01f, 0.03f, zw), isMine ? mMine : mTop, false);
                // 포스터(족자): 흰 종이 + 노란 머리띠 + 보라 제목띠 + 노란 아랫단
                float px = spineX + side * (PanelT + 0.006f), pw = 0.62f;
                Part(root.transform, "poster", new Vector3(px, 1.52f, zc), new Vector3(0.008f, 0.92f, pw), mPaper, false);
                Part(root.transform, "poster_head", new Vector3(px + side * 0.003f, 1.92f, zc), new Vector3(0.008f, 0.12f, pw), mPosterY, false);
                Part(root.transform, "poster_title", new Vector3(px + side * 0.003f, 1.82f, zc), new Vector3(0.008f, 0.05f, pw * 0.9f), mPosterP, false);
                Part(root.transform, "poster_foot", new Vector3(px + side * 0.003f, 1.10f, zc), new Vector3(0.008f, 0.08f, pw), mPosterY, false);
                // 조명
                GameObject lamp = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                lamp.name = "lamp";
                Object.DestroyImmediate(lamp.GetComponent<Collider>());
                lamp.transform.SetParent(root.transform, true);
                lamp.transform.position = new Vector3(spineX + side * 0.16f, PanelH - 0.12f, zc);
                lamp.transform.localScale = Vector3.one * 0.09f;
                lamp.GetComponent<Renderer>().sharedMaterial = mLamp;

                if (isMine) myCell = new Bounds(new Vector3((cx0 + cx1) * 0.5f, 0.4f, zc), new Vector3(1f, 0.8f, zw));
                float d0 = Mathf.Min(spineX + side * PanelT, spineX + side * (PanelT + DeskDepth)), d1 = Mathf.Max(spineX + side * PanelT, spineX + side * (PanelT + DeskDepth));
                csv.Append(name).Append(',').Append(s.dept).Append(',').Append(cx0.ToString("F2", ci)).Append(',').Append(cx1.ToString("F2", ci)).Append(',')
                   .Append(za.ToString("F2", ci)).Append(',').Append(zb.ToString("F2", ci)).Append(',').Append(d0.ToString("F2", ci)).Append(',').Append(d1.ToString("F2", ci)).Append('\n');
                count++;
            }
        }

        // 시연 자리 이름표: 데스크 앞 바닥 타일 위
        var label = new GameObject("label_컴공A_1");
        label.transform.SetParent(booths.transform, false);
        label.transform.position = new Vector3(myCell.min.x + 0.25f, 0.03f, myCell.center.z);
        label.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
        var tm = label.AddComponent<TextMesh>();
        tm.text = "컴공A 1"; tm.anchor = TextAnchor.MiddleCenter; tm.alignment = TextAlignment.Center;
        tm.fontSize = 60; tm.characterSize = 0.018f; tm.color = Color.white;

        string outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "capstone_map");
        Directory.CreateDirectory(outDir);
        File.WriteAllText(Path.Combine(outDir, "booths.csv"), csv.ToString(), new UTF8Encoding(true));
        Debug.Log("[CapstoneBooths] 전시대 " + count + "칸 (뒷판 " + PanelH + " m, 데스크 1.0 x " + DeskDepth + " x " + DeskH + " m) | 시연 자리 칸 x[" +
                  myCell.min.x.ToString("F2", ci) + "~" + myCell.max.x.ToString("F2", ci) + "] z[" + myCell.min.z.ToString("F2", ci) + "~" + myCell.max.z.ToString("F2", ci) + "]");
    }

    // 상자 부품 하나. obstacle = 충돌체 + 태그 Obstacle + 실행 중 NavMesh 를 파내는 NavMeshObstacle
    private static void Part(Transform parent, string name, Vector3 center, Vector3 size, Material m, bool obstacle)
    {
        GameObject g = GameObject.CreatePrimitive(PrimitiveType.Cube);
        g.name = name;
        g.transform.SetParent(parent, true);
        g.transform.position = center;
        g.transform.localScale = size;
        g.GetComponent<Renderer>().sharedMaterial = m;
        if (obstacle)
        {
            g.tag = "Obstacle";
            var o = g.AddComponent<NavMeshObstacle>();
            o.shape = NavMeshObstacleShape.Box; o.center = Vector3.zero; o.size = Vector3.one; o.carving = true;
        }
        else Object.DestroyImmediate(g.GetComponent<Collider>());
    }

    public static void Shots()
    {
        string outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "capstone_map");
        GameObject mine = GameObject.Find("booth_컴공A_1_시연자리");
        Vector3 c = mine != null ? mine.transform.position : new Vector3(19f, 0f, 17.5f);
        Shot(Path.Combine(outDir, "capstone_hall_top.png"), new Vector3(12.55f, 60f, 19.5f), Quaternion.Euler(90f, 0f, 0f), true, 20f, 1100, 1700);
        Shot(Path.Combine(outDir, "capstone_hall_demo_area.png"), new Vector3(c.x - 1.4f, 60f, c.z - 1.0f), Quaternion.Euler(90f, 0f, 0f), true, 5f, 1400, 1400);
        // 통로에서 시연 자리를 비스듬히 본 모습 (사진과 비슷한 시점)
        Vector3 eye = new Vector3(c.x - 3.2f, 1.7f, c.z - 3.2f);
        Shot(Path.Combine(outDir, "capstone_hall_booth_view.png"), eye, Quaternion.LookRotation(new Vector3(c.x + 0.4f, 1.1f, c.z + 1.0f) - eye), false, 60f, 1600, 1000);
        Vector3 eye2 = new Vector3(c.x - 7f, 9f, c.z - 9f);
        Shot(Path.Combine(outDir, "capstone_hall_bird_view.png"), eye2, Quaternion.LookRotation(new Vector3(c.x - 1f, 0.5f, c.z) - eye2), false, 55f, 1600, 1000);
        Debug.Log("[CapstoneBooths] 그림 저장 → " + outDir);
    }

    public static void Shot(string path, Vector3 pos, Quaternion rot, bool ortho, float sizeOrFov, int w, int h)
    {
        var go = new GameObject("tmp_shot_cam");
        var cam = go.AddComponent<Camera>();
        cam.orthographic = ortho;
        if (ortho) cam.orthographicSize = sizeOrFov; else cam.fieldOfView = sizeOrFov;
        cam.transform.position = pos; cam.transform.rotation = rot;
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
