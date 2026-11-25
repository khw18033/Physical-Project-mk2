// ProactiveBatchRunner를 에디터 창 없이 실행한다.
//
//   Unity.exe -batchmode -nographics -projectPath D:\Go1_Unity
//             -executeMethod ProactiveBatchLauncher.Run
//             -logFile D:\Go1_Unity\GO1_Proactive_Evaluation\logs\<name>.log
//
// -quit 은 붙이지 않는다: 실험이 끝나면 러너가 EditorApplication.Exit 를 부른다.
// 설정은 GO1_Proactive_Evaluation/batch_config.json.

using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class ProactiveBatchLauncher
{
    private const string DefaultScene = "Assets/lab.unity";
    [System.Serializable] private class SceneCfg { public string scene = ""; }

    public static void Run()
    {
        string root = Directory.GetParent(Application.dataPath).FullName;
        string cfg = Path.Combine(root, ProactiveBatchRunner.ConfigPath);
        if (!File.Exists(cfg))
        {
            Debug.LogError("[ProactiveBatchLauncher] missing config: " + cfg);
            EditorApplication.Exit(1);
            return;
        }
        Debug.Log("[ProactiveBatchLauncher] config: " + File.ReadAllText(cfg));

        SceneCfg sc = JsonUtility.FromJson<SceneCfg>(File.ReadAllText(cfg));
        string scenePath = sc != null && !string.IsNullOrEmpty(sc.scene) ? sc.scene : DefaultScene;
        Debug.Log("[ProactiveBatchLauncher] scene: " + scenePath);
        EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
        new GameObject("ProactiveBatchRunner").AddComponent<ProactiveBatchRunner>();
        EditorApplication.EnterPlaymode();
    }
}
