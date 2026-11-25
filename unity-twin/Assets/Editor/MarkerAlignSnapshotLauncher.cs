// MarkerAlignSnapshotRunner 를 에디터 창 없이 실행한다 (화면을 그려야 하므로 -nographics 없이).
//   Unity.exe -batchmode -projectPath D:\Go1_Unity -executeMethod MarkerAlignSnapshotLauncher.Run -logFile <log>
//
// 다른 Unity(배치 실험)가 같은 PC에서 돌고 있으면 로봇 통신 포트가 겹친다. 이 확인에는 로봇 통신이 필요 없으므로
// Play 에 들어가기 전에 그 컴포넌트들을 꺼 둔다 (씬 파일은 저장하지 않는다).

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class MarkerAlignSnapshotLauncher
{
    private static readonly string[] Off =
    {
        "UnityTeleopAndMirror", "YoloCubeSpawner", "Go1ObstacleJsonReceiver", "Go1ObstacleWebSocketReceiver",
        "ArUcoUDPReceiver", "MJPEGReceiver", "MJPEGMeshReceiver", "SceneMJPEGStreamer", "WsPlannerClient",
        "ObstacleCubeLogger", "GO1LocalPathUdpSender",
    };

    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/lab.unity", OpenSceneMode.Single);
        int n = 0;
        foreach (MonoBehaviour mb in Object.FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            if (mb == null || !mb.enabled || System.Array.IndexOf(Off, mb.GetType().Name) < 0) continue;
            mb.enabled = false;
            n++;
        }
        Debug.Log("[MarkerAlign] disabled " + n + " link components for this check");
        new GameObject("MarkerAlignSnapshotRunner").AddComponent<MarkerAlignSnapshotRunner>();
        EditorApplication.EnterPlaymode();
    }
}
