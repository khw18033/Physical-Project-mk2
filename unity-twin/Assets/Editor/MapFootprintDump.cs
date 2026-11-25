// 가상 맵의 물체 바닥 영역과 주행 가능 영역(NavMesh)을 파일로 내보낸다 (실제 영상과 대조하는 맵 점검용).
//   Unity.exe -batchmode -nographics -quit -projectPath D:\Go1_Unity -executeMethod MapFootprintDump.Run -logFile <log>
// 출력: GO1_Proactive_Evaluation/map_audit/footprints.csv, navmesh.csv

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.AI;

public static class MapFootprintDump
{
    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/lab.unity", OpenSceneMode.Single);
        string dir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "map_audit");
        Directory.CreateDirectory(dir);
        var ci = CultureInfo.InvariantCulture;

        var sb = new StringBuilder("path,layer,tag,min_x,max_x,min_y,max_y,min_z,max_z,has_collider\n");
        foreach (Renderer r in Object.FindObjectsByType<Renderer>(FindObjectsSortMode.None))
        {
            if (r is LineRenderer || r is ParticleSystemRenderer || r is TrailRenderer) continue;
            Bounds b = r.bounds;
            string path = r.name;
            for (Transform t = r.transform.parent; t != null; t = t.parent) path = t.name + "/" + path;
            sb.Append('"').Append(path.Replace("\"", "'")).Append("\",")
              .Append(LayerMask.LayerToName(r.gameObject.layer)).Append(',').Append(r.gameObject.tag).Append(',')
              .Append(b.min.x.ToString("F3", ci)).Append(',').Append(b.max.x.ToString("F3", ci)).Append(',')
              .Append(b.min.y.ToString("F3", ci)).Append(',').Append(b.max.y.ToString("F3", ci)).Append(',')
              .Append(b.min.z.ToString("F3", ci)).Append(',').Append(b.max.z.ToString("F3", ci)).Append(',')
              .Append(r.GetComponent<Collider>() != null ? 1 : 0).Append('\n');
        }
        File.WriteAllText(Path.Combine(dir, "footprints.csv"), sb.ToString(), new UTF8Encoding(true));

        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        var nb = new StringBuilder("x1,z1,x2,z2,x3,z3\n");
        for (int i = 0; i < tri.indices.Length; i += 3)
        {
            Vector3 a = tri.vertices[tri.indices[i]], b = tri.vertices[tri.indices[i + 1]], c = tri.vertices[tri.indices[i + 2]];
            nb.Append(a.x.ToString("F3", ci)).Append(',').Append(a.z.ToString("F3", ci)).Append(',')
              .Append(b.x.ToString("F3", ci)).Append(',').Append(b.z.ToString("F3", ci)).Append(',')
              .Append(c.x.ToString("F3", ci)).Append(',').Append(c.z.ToString("F3", ci)).Append('\n');
        }
        File.WriteAllText(Path.Combine(dir, "navmesh.csv"), nb.ToString(), new UTF8Encoding(true));

        // 카메라 보정에 쓰는 앵커의 실제 위치·회전 (보정 파일 적용 전의 씬 값)
        var anchors = new StringBuilder("name,x,y,z,yaw,yawOffsetDeg,distanceScale,invertX,enabled\n");
        foreach (var a in Object.FindObjectsByType<Anchor360ObstacleReceiver>(FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            Transform t = a.anchorTransform != null ? a.anchorTransform : a.transform;
            anchors.Append(a.name).Append(',').Append(t.position.x.ToString("F3", ci)).Append(',').Append(t.position.y.ToString("F3", ci)).Append(',')
                   .Append(t.position.z.ToString("F3", ci)).Append(',').Append(t.eulerAngles.y.ToString("F2", ci)).Append(',')
                   .Append(a.yawOffsetDeg.ToString("F2", ci)).Append(',').Append(a.distanceScale.ToString("F3", ci)).Append(',')
                   .Append(a.invertX ? 1 : 0).Append(',').Append(a.isActiveAndEnabled ? 1 : 0).Append('\n');
        }
        File.WriteAllText(Path.Combine(dir, "anchors.csv"), anchors.ToString(), new UTF8Encoding(true));
        Debug.Log("[MapFootprintDump] OK → " + dir);
    }
}
