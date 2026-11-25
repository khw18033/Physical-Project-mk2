// 360 카메라 마커로 읽은 로봇 자세를 편집 화면(Play 아님)의 가상 Go1 에 적용한다.
//
// anchor360_marker_live.py --pose-out 이 GO1_Proactive_Evaluation/marker_align/apply_pose.json 을 쓰면,
// 에디터가 그 파일이 바뀐 것을 보고 가상 로봇(UnityTeleopAndMirror.robotId 가 일치하는 것)을 그 위치·방향으로 옮긴다.
// 씬은 저장하지 않는다(변경 표시만). Ctrl+Z 로 되돌릴 수 있다.

using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

[InitializeOnLoad]
public static class MarkerPoseApplier
{
    [Serializable] private class Pose { public float x, z, yaw_deg; public int samples; public string robot_id = "GO1_A"; public string time; }

    private static readonly string PosePath =
        Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "marker_align", "apply_pose.json");
    private static DateTime lastStamp = DateTime.MinValue;
    private static double nextCheck;

    static MarkerPoseApplier()
    {
        if (Application.isBatchMode) return;
        try { if (File.Exists(PosePath)) lastStamp = File.GetLastWriteTimeUtc(PosePath); } catch { }   // 예전 파일은 적용하지 않는다
        EditorApplication.update += Tick;
    }

    private static void Tick()
    {
        if (EditorApplication.timeSinceStartup < nextCheck) return;
        nextCheck = EditorApplication.timeSinceStartup + 1.0;
        if (EditorApplication.isPlayingOrWillChangePlaymode) return;
        try
        {
            if (!File.Exists(PosePath)) return;
            DateTime stamp = File.GetLastWriteTimeUtc(PosePath);
            if (stamp == lastStamp) return;
            lastStamp = stamp;
            Apply(JsonUtility.FromJson<Pose>(File.ReadAllText(PosePath)));
        }
        catch (Exception e) { Debug.LogWarning("[MarkerPose] 적용 실패: " + e.Message); }
    }

    [MenuItem("Tools/Go1/마커 자세 다시 적용")]
    private static void ApplyAgain()
    {
        if (File.Exists(PosePath)) Apply(JsonUtility.FromJson<Pose>(File.ReadAllText(PosePath)));
        else Debug.LogWarning("[MarkerPose] 파일 없음: " + PosePath);
    }

    private static void Apply(Pose p)
    {
        if (p == null) return;
        Transform robot = null;
        foreach (var u in UnityEngine.Object.FindObjectsByType<UnityTeleopAndMirror>(FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            if (u.robotId != p.robot_id) continue;
            robot = u.driver != null ? u.driver.transform : u.robotRoot;
            break;
        }
        if (robot == null) { Debug.LogWarning("[MarkerPose] 가상 로봇 '" + p.robot_id + "' 를 찾지 못함"); return; }

        Vector3 before = robot.position; float beforeYaw = Yaw(robot);
        Undo.RecordObject(robot, "마커 자세 적용");
        robot.SetPositionAndRotation(new Vector3(p.x, before.y, p.z), Quaternion.Euler(0f, p.yaw_deg + 90f, 0f));   // 전진축이 -X
        EditorSceneManager.MarkSceneDirty(robot.gameObject.scene);

        Vector3 d = robot.position - before; d.y = 0f;
        Debug.Log("[MarkerPose] '" + robot.name + "' 을 마커 자세로 옮김 | (" + before.x.ToString("F3") + ", " + before.z.ToString("F3") + ") " +
                  beforeYaw.ToString("F1") + "도 → (" + p.x.ToString("F3") + ", " + p.z.ToString("F3") + ") " + p.yaw_deg.ToString("F1") +
                  "도 | 옮긴 거리 " + (d.magnitude * 100f).ToString("F1") + " cm, 돌린 각 " + Mathf.DeltaAngle(beforeYaw, p.yaw_deg).ToString("F1") +
                  "도 (" + p.samples + "장 평균, " + p.time + ")");
        Selection.activeGameObject = robot.gameObject;
        if (SceneView.lastActiveSceneView != null) SceneView.lastActiveSceneView.FrameSelected();
    }

    private static float Yaw(Transform t)
    {
        Vector3 f = -t.right; f.y = 0f;
        return Mathf.Repeat(Mathf.Atan2(f.x, f.z) * Mathf.Rad2Deg, 360f);
    }
}
