// 씬에 저장된 로봇 쪽 주소를 Tailscale 주소로 바꿔 저장한다 (2026-11-25).
//   Unity.exe -batchmode -projectPath D:\Go1_Unity -executeMethod TailscaleAddressApplier.Run -quit -logFile <log>
//
// 바꾸는 것: robotId 가 맞는 UnityTeleopAndMirror.sdkPcIp, 그 로봇 아래 GO1LocalPathUdpSender.remoteIp
// 바꾸지 않는 것: 다른 로봇(GO1_B), GO1AutoPolicyController.commandHost(후진·정지 속도 명령을 로봇에 직접 보내는 주소)
// 결과: GO1_Proactive_Evaluation/real_run/tailscale_apply.txt

using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class TailscaleAddressApplier
{
    private const string RobotId = "GO1_A";
    private const string RobotHost = "100.72.109.9";     // pi7
    private static readonly string[] Scenes = { "Assets/lab.unity", "Assets/mall.unity", "Assets/capstone_hall.unity" };

    [MenuItem("Tools/Go1/로봇 주소를 Tailscale 로 바꾸기")]
    public static void Run()
    {
        var sb = new StringBuilder();
        foreach (string path in Scenes)
        {
            if (!File.Exists(path)) { sb.AppendLine(path + ": 없음"); continue; }
            var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
            int changed = 0;
            foreach (var utm in Object.FindObjectsByType<UnityTeleopAndMirror>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (utm.robotId != RobotId) { sb.AppendLine(path + ": " + utm.robotId + " sdkPcIp " + utm.sdkPcIp + " (그대로 둠)"); continue; }
                sb.AppendLine(path + ": " + utm.robotId + " sdkPcIp " + utm.sdkPcIp + " -> " + RobotHost);
                if (utm.sdkPcIp != RobotHost) { utm.sdkPcIp = RobotHost; Mark(utm); changed++; }
                Transform scope = utm.driver != null ? utm.driver.transform : utm.robotRoot;
                if (scope == null) { sb.AppendLine(path + ":   driver/robotRoot 없음 - 경로 전송 주소를 찾지 못함"); continue; }
                foreach (var ps in scope.GetComponentsInChildren<GO1LocalPathUdpSender>(true))
                {
                    sb.AppendLine(path + ":   " + ps.name + " remoteIp " + ps.remoteIp + " -> " + RobotHost);
                    if (ps.remoteIp != RobotHost) { ps.remoteIp = RobotHost; Mark(ps); changed++; }
                }
                foreach (var ac in scope.GetComponentsInChildren<GO1AutoPolicyController>(true))
                    sb.AppendLine(path + ":   " + ac.name + " commandHost " + ac.commandHost + " sendCommandToCpp=" + ac.sendCommandToCpp + " enabled=" + ac.enabled + " (그대로 둠)");
            }
            if (changed > 0) { EditorSceneManager.MarkSceneDirty(scene); EditorSceneManager.SaveScene(scene); }
            sb.AppendLine(path + ": 바꾼 항목 " + changed + "개" + (changed > 0 ? ", 저장함" : ""));
        }
        string root = Directory.GetParent(Application.dataPath).FullName;
        File.WriteAllText(Path.Combine(root, "GO1_Proactive_Evaluation", "real_run", "tailscale_apply.txt"), sb.ToString(), new UTF8Encoding(false));
        Debug.Log("[Tailscale]\n" + sb);
    }

    private static void Mark(Object o)
    {
        EditorUtility.SetDirty(o);
        if (PrefabUtility.IsPartOfPrefabInstance(o)) PrefabUtility.RecordPrefabInstancePropertyModifications(o);
    }
}
