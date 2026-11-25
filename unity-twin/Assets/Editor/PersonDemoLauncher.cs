// 사람 탐지 표시 시연을 창 없이 실행한다 (카메라 없이, 가짜 탐지 신호로).
//   Unity.exe -batchmode -projectPath D:\Go1_Unity -executeMethod PersonDemoLauncher.Run -logFile <log>      (-nographics, -quit 없이)
// 씬은 환경변수 PERSON_DEMO_SCENE (기본 Assets/mall.unity). 결과: GO1_Proactive_Evaluation/person_demo/

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class PersonDemoLauncher
{
    public static void Run()
    {
        string scene = System.Environment.GetEnvironmentVariable("PERSON_DEMO_SCENE");
        if (string.IsNullOrEmpty(scene)) scene = "Assets/mall.unity";
        Debug.Log("[PersonDemoLauncher] scene: " + scene);
        EditorSceneManager.OpenScene(scene, OpenSceneMode.Single);
        new GameObject("PersonDemoRunner").AddComponent<PersonDemoRunner>();
        EditorApplication.EnterPlaymode();
    }
}
