// 씬의 뼈대(루트 오브젝트, Map 자식, 바닥, NavMeshSurface, 카메라, 로봇)를 글로 내보낸다. 새 맵을 만들 때 참고용.
//   Unity.exe -batchmode -nographics -quit -projectPath D:\Go1_Unity -executeMethod SceneOutlineDump.Run -logFile <log>
// 출력: GO1_Proactive_Evaluation/capstone_map/outline_<씬이름>.txt  (씬은 -sceneOutline <경로> 로 지정, 기본 Assets/lab.unity)

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class SceneOutlineDump
{
    public static void Run()
    {
        string path = "Assets/lab.unity";
        string[] a = System.Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length - 1; i++) if (a[i] == "-sceneOutline") path = a[i + 1];
        var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
        var ci = CultureInfo.InvariantCulture;
        var sb = new StringBuilder();
        foreach (GameObject root in scene.GetRootGameObjects())
        {
            Line(sb, root.transform, 0, ci);
            foreach (Transform c in root.transform)
            {
                Line(sb, c, 1, ci);
                if (root.name == "Map" || c.GetComponent<Camera>() != null) continue;
                if (c.childCount <= 12) foreach (Transform g in c) Line(sb, g, 2, ci);
            }
        }
        string dir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "capstone_map");
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "outline_" + scene.name + ".txt"), sb.ToString(), new UTF8Encoding(true));
        Debug.Log("[SceneOutlineDump] OK");
    }

    private static void Line(StringBuilder sb, Transform t, int depth, CultureInfo ci)
    {
        sb.Append(' ', depth * 2).Append(t.name).Append(t.gameObject.activeSelf ? "" : " (off)")
          .Append(" | pos ").Append(t.position.x.ToString("F2", ci)).Append(',').Append(t.position.y.ToString("F2", ci)).Append(',').Append(t.position.z.ToString("F2", ci))
          .Append(" yaw ").Append(t.eulerAngles.y.ToString("F0", ci))
          .Append(" | layer ").Append(LayerMask.LayerToName(t.gameObject.layer)).Append(" tag ").Append(t.gameObject.tag);
        Renderer[] rs = t.GetComponentsInChildren<Renderer>(true);
        if (rs.Length > 0)
        {
            Bounds b = rs[0].bounds;
            foreach (Renderer r in rs) b.Encapsulate(r.bounds);
            sb.Append(" | x[").Append(b.min.x.ToString("F2", ci)).Append('~').Append(b.max.x.ToString("F2", ci)).Append("] y[")
              .Append(b.min.y.ToString("F2", ci)).Append('~').Append(b.max.y.ToString("F2", ci)).Append("] z[")
              .Append(b.min.z.ToString("F2", ci)).Append('~').Append(b.max.z.ToString("F2", ci)).Append(']');
        }
        sb.Append(" | ");
        foreach (Component c in t.GetComponents<Component>())
            if (c != null && !(c is Transform)) sb.Append(c.GetType().Name).Append(c is Behaviour bh && !bh.enabled ? "(off)" : "").Append(' ');
        sb.Append('\n');
    }
}
