// 맵 점검(2026-11-24, 360 카메라 영상과 대조) 결과에 따라 lab 씬의 가구 세 곳을 고친다. 한 번만 실행한다.
//   Unity.exe -batchmode -nographics -quit -projectPath D:\Go1_Unity -executeMethod MapFix261124.Run -logFile <log>
//
//  1) 360 카메라가 놓인 나무 탁자 추가        실제 x 2.76~3.64, z 6.35~7.22, 상판 높이 약 0.72 m (맵에 없었음)
//  2) 프린터 수납장 + 프린터를 z +0.56 m      (가상이 실제보다 0.55 m 앞으로 나와 있었음)
//  3) 소파 앞 낮은 탁자를 x -0.55, z +0.28 m
//
// 이 씬은 바닥만 구워 두고 가구의 NavMeshObstacle 이 주행 가능 영역을 파내므로, 다시 굽지 않아도 된다.

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class MapFix261124
{
    private const string TableName = "table_camera_261124";

    public static void Run()
    {
        var scene = EditorSceneManager.OpenScene("Assets/lab.unity", OpenSceneMode.Single);
        GameObject map = GameObject.Find("Map");
        if (map == null) { Debug.LogError("[MapFix] 'Map' 없음"); EditorApplication.Exit(1); return; }
        if (map.transform.Find(TableName) != null) { Debug.Log("[MapFix] 이미 적용됨 — 건너뜀"); return; }

        // 2) 프린터 수납장 + 프린터
        Move(map, "Cube (1)", new Vector3(0f, 0f, 0.56f));
        Move(map, "printer", new Vector3(0f, 0f, 0.56f));
        // 3) 소파 앞 낮은 탁자
        Move(map, "desk15060", new Vector3(-0.55f, 0f, 0.28f));

        // 1) 나무 탁자: 기존 책상을 복제해 크기와 위치를 맞춘다 (충돌체·태그·NavMeshObstacle 구성을 그대로 물려받는다)
        Transform src = map.transform.Find("desk (4)");
        if (src == null) { Debug.LogError("[MapFix] 복제할 'desk (4)' 없음"); EditorApplication.Exit(1); return; }
        GameObject table = Object.Instantiate(src.gameObject, map.transform);
        table.name = TableName;
        // desk (4) 에는 보조 상판 'Top (1)' 이 딸려 있다. 탁자에는 필요 없다.
        Transform extra = table.transform.Find("Top (1)");
        if (extra != null) Object.DestroyImmediate(extra.gameObject);

        Vector3 targetMin = new Vector3(2.76f, 0f, 6.35f), targetMax = new Vector3(3.64f, 0.72f, 7.22f);
        for (int pass = 0; pass < 3; pass++)      // 크기를 맞추고(회전돼 있어도 되도록 반복) 위치를 맞춘다
        {
            Bounds b = WorldBounds(table);
            Vector3 want = targetMax - targetMin;
            Vector3 k = new Vector3(want.x / Mathf.Max(b.size.x, 1e-4f), want.y / Mathf.Max(b.size.y, 1e-4f), want.z / Mathf.Max(b.size.z, 1e-4f));
            // 월드 축 배율을 로컬 축으로 옮긴다 (가구는 90도 단위로만 돌아가 있다)
            Vector3 lx = table.transform.InverseTransformDirection(Vector3.right), lz = table.transform.InverseTransformDirection(Vector3.forward);
            Vector3 s = table.transform.localScale;
            Vector3 mul = new Vector3(
                Mathf.Abs(lx.x) > 0.5f ? k.x : (Mathf.Abs(lz.x) > 0.5f ? k.z : 1f),
                k.y,
                Mathf.Abs(lx.z) > 0.5f ? k.x : (Mathf.Abs(lz.z) > 0.5f ? k.z : 1f));
            table.transform.localScale = Vector3.Scale(s, mul);
            b = WorldBounds(table);
            Vector3 targetCenter = (targetMin + targetMax) * 0.5f;
            table.transform.position += new Vector3(targetCenter.x - b.center.x, targetMin.y - b.min.y, targetCenter.z - b.center.z);
        }
        Bounds fin = WorldBounds(table);
        Debug.Log("[MapFix] 나무 탁자 추가: x[" + fin.min.x.ToString("F2") + "~" + fin.max.x.ToString("F2") + "] z[" +
                  fin.min.z.ToString("F2") + "~" + fin.max.z.ToString("F2") + "] 높이 " + fin.max.y.ToString("F2") +
                  " | NavMeshObstacle " + table.GetComponentsInChildren<UnityEngine.AI.NavMeshObstacle>(true).Length +
                  "개, 충돌체 " + table.GetComponentsInChildren<Collider>(true).Length + "개");

        EditorSceneManager.MarkSceneDirty(scene);
        bool ok = EditorSceneManager.SaveScene(scene);
        Debug.Log("[MapFix] 저장 " + (ok ? "OK" : "실패"));
        if (!ok) EditorApplication.Exit(1);
    }

    private static void Move(GameObject map, string name, Vector3 delta)
    {
        Transform t = map.transform.Find(name);
        if (t == null) { Debug.LogError("[MapFix] '" + name + "' 없음"); return; }
        Bounds before = WorldBounds(t.gameObject);
        t.position += delta;
        Bounds after = WorldBounds(t.gameObject);
        Debug.Log("[MapFix] " + name + " 이동 " + delta.ToString("F2") + " | x[" + before.min.x.ToString("F2") + "~" + before.max.x.ToString("F2") +
                  "] z[" + before.min.z.ToString("F2") + "~" + before.max.z.ToString("F2") + "] → x[" + after.min.x.ToString("F2") + "~" +
                  after.max.x.ToString("F2") + "] z[" + after.min.z.ToString("F2") + "~" + after.max.z.ToString("F2") + "]");
    }

    private static Bounds WorldBounds(GameObject go)
    {
        Renderer[] rs = go.GetComponentsInChildren<Renderer>(true);
        Bounds b = rs.Length > 0 ? rs[0].bounds : new Bounds(go.transform.position, Vector3.zero);
        foreach (Renderer r in rs) b.Encapsulate(r.bounds);
        return b;
    }
}
