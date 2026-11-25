// RealRunRunner 를 에디터 창 없이 실행한다 (화면을 기록하므로 -nographics 없이).
//   Unity.exe -batchmode -projectPath D:\Go1_Unity -executeMethod RealRunLauncher.Run -logFile <log>
//
// Play 에 들어가기 전에(씬은 저장하지 않는다):
//  - 로봇 쪽 주소를 real_run/config 의 robotHost 로 맞춘다 (씬에 저장된 주소가 지금 로봇 PC 주소와 다를 수 있다)
//  - 이번 주행에 쓰지 않는 수신기를 끈다

using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class RealRunLauncher
{
    [System.Serializable] private class Cfg { public string robotId = "GO1_A"; public string robotHost = "100.72.109.9"; }   // pi7 Tailscale 주소 (2026-11-25, 이전: 랩 공유기 192.168.50.170)

    private static readonly string[] Off =
    {
        // Go1ObstacleJsonReceiver 는 끄지 않는다: 로봇이 "움직이기 시작했다"고 알리는 신호(state_change)를 이것이 받는다.
        "YoloCubeSpawner", "Go1ObstacleWebSocketReceiver", "ArUcoUDPReceiver",
        "MJPEGReceiver", "MJPEGMeshReceiver", "SceneMJPEGStreamer", "WsPlannerClient", "ObstacleCubeLogger",
    };

    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/lab.unity", OpenSceneMode.Single);
        string root = Directory.GetParent(Application.dataPath).FullName;
        string cp = Path.Combine(root, RealRunRunner.Dir, "config.json");
        Cfg cfg = File.Exists(cp) ? JsonUtility.FromJson<Cfg>(File.ReadAllText(cp)) : new Cfg();

        foreach (MonoBehaviour mb in Object.FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            if (mb == null) continue;
            if (mb.enabled && System.Array.IndexOf(Off, mb.GetType().Name) >= 0) mb.enabled = false;
            if (mb is UnityTeleopAndMirror utm)
            {
                if (utm.robotId == cfg.robotId)
                {
                    Debug.Log("[RealRun] " + utm.robotId + " 로봇 쪽 주소 " + utm.sdkPcIp + " → " + cfg.robotHost);
                    utm.sdkPcIp = cfg.robotHost;
                    Transform scope = utm.driver != null ? utm.driver.transform : utm.robotRoot;
                    if (scope != null)
                        foreach (var ps in scope.GetComponentsInChildren<GO1LocalPathUdpSender>(true))
                        {
                            Debug.Log("[RealRun] 경로 전송 주소 " + ps.remoteIp + " → " + cfg.robotHost);
                            ps.remoteIp = cfg.robotHost;
                        }
                }
                else utm.enabled = false;      // 다른 로봇은 쓰지 않는다
            }
        }
        new GameObject("RealRunRunner").AddComponent<RealRunRunner>();
        EditorApplication.EnterPlaymode();
    }
}
