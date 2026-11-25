// 가상 맵에서 두 점 사이의 주행 경로(NavMesh)를 계산해 파일로 내보낸다. 로봇을 움직이기 전에 경로를 미리 보는 용도.
//   Unity.exe -batchmode -nographics -quit -projectPath D:\Go1_Unity -executeMethod PlanPathDump.Run -logFile <log>
// 입력: GO1_Proactive_Evaluation/map_audit/plan_request.json  { "fromX":..,"fromZ":..,"toX":..,"toZ":.. }
// 출력: GO1_Proactive_Evaluation/map_audit/plan_path.csv

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.AI;

public static class PlanPathDump
{
    [System.Serializable] private class Req { public float fromX, fromZ, toX, toZ; }

    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/lab.unity", OpenSceneMode.Single);
        string dir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "map_audit");
        Req r = JsonUtility.FromJson<Req>(File.ReadAllText(Path.Combine(dir, "plan_request.json")));
        var ci = CultureInfo.InvariantCulture;
        Vector3 a = new Vector3(r.fromX, 0f, r.fromZ), b = new Vector3(r.toX, 0f, r.toZ);
        bool aOn = NavMesh.SamplePosition(a, out NavMeshHit ha, 1.0f, NavMesh.AllAreas);
        bool bOn = NavMesh.SamplePosition(b, out NavMeshHit hb, 1.0f, NavMesh.AllAreas);
        var path = new NavMeshPath();
        bool ok = aOn && bOn && NavMesh.CalculatePath(ha.position, hb.position, NavMesh.AllAreas, path);
        var sb = new StringBuilder();
        float len = 0f, minEdge = float.MaxValue;
        for (int i = 0; ok && i < path.corners.Length; i++)
        {
            if (i > 0) len += Vector3.Distance(path.corners[i - 1], path.corners[i]);
            sb.Append(path.corners[i].x.ToString("F3", ci)).Append(',').Append(path.corners[i].z.ToString("F3", ci)).Append('\n');
        }
        // 경로를 따라 5 cm 간격으로, 주행 가능 영역 경계까지의 거리(통로 여유)를 본다
        for (int i = 1; ok && i < path.corners.Length; i++)
        {
            float d = Vector3.Distance(path.corners[i - 1], path.corners[i]);
            int n = Mathf.Max(1, Mathf.CeilToInt(d / 0.05f));
            for (int k = 0; k <= n; k++)
                if (NavMesh.FindClosestEdge(Vector3.Lerp(path.corners[i - 1], path.corners[i], (float)k / n), out NavMeshHit e, NavMesh.AllAreas))
                    minEdge = Mathf.Min(minEdge, e.distance);
        }
        string head = "status=" + (ok ? path.status.ToString() : "NoPath") + " length=" + len.ToString("F2", ci) +
                      " corners=" + (ok ? path.corners.Length : 0) +
                      " start_snap=" + (aOn ? Vector3.Distance(ha.position, a).ToString("F2", ci) : "off") +
                      " goal_snap=" + (bOn ? Vector3.Distance(hb.position, b).ToString("F2", ci) : "off");
        File.WriteAllText(Path.Combine(dir, "plan_path.csv"), "# " + head + "\n" + sb, new UTF8Encoding(false));
        Debug.Log("[PlanPath] " + head);
    }
}
