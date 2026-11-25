// 캡스톤 발표장 씬(capstone_hall)의 360 카메라를 "바닥 삼각대, 렌즈 높이 1.5 m" 로 맞춘다.
//  - Anchor360 의 높이를 1.5 m 로 내린다 (Unity 는 이 높이를 카메라 높이로 쓴다)
//  - 바닥까지 삼각대 기둥과 발 받침을 그린다. 발 받침(0.5 m x 0.5 m)은 로봇이 피해 가도록 장애물로 둔다.
// 에디터에서 capstone_hall 씬이 열려 있고 삼각대가 아직 없으면 스크립트를 읽을 때 한 번 자동으로 적용하고 씬을 저장한다.
// 메뉴: Tools/Go1/캡스톤 360 카메라 삼각대 적용

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.AI;

[InitializeOnLoad]
public static class CapstoneCamera360Setup
{
    public const float LensHeight = 1.5f, BaseSize = 0.5f;
    private const string TripodName = "tripod_360";

    static CapstoneCamera360Setup()
    {
        if (Application.isBatchMode) return;
        EditorApplication.delayCall += () =>
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return;
            var scene = EditorSceneManager.GetActiveScene();
            if (scene.name != "capstone_hall") return;
            GameObject a = FindAnchor(scene);
            if (a == null || a.transform.Find(TripodName) != null) return;
            if (Apply(scene)) EditorSceneManager.SaveScene(scene);
        };
    }

    [MenuItem("Tools/Go1/캡스톤 360 카메라 삼각대 적용")]
    private static void Menu()
    {
        var scene = EditorSceneManager.GetActiveScene();
        if (Apply(scene)) EditorSceneManager.MarkSceneDirty(scene);
    }

    private static GameObject FindAnchor(UnityEngine.SceneManagement.Scene scene)
    {
        foreach (GameObject g in scene.GetRootGameObjects()) if (g.name == "Anchor360") return g;
        return null;
    }

    public static bool Apply(UnityEngine.SceneManagement.Scene scene)
    {
        GameObject anchor = FindAnchor(scene);
        if (anchor == null) { Debug.LogWarning("[Capstone360] Anchor360 없음"); return false; }
        Transform old = anchor.transform.Find(TripodName);
        if (old != null) Object.DestroyImmediate(old.gameObject);

        Vector3 p = anchor.transform.position;
        float before = p.y;
        anchor.transform.position = new Vector3(p.x, LensHeight, p.z);

        var tripod = new GameObject(TripodName);
        tripod.transform.SetParent(anchor.transform, false);
        tripod.transform.position = new Vector3(p.x, 0f, p.z);
        tripod.transform.rotation = Quaternion.identity;

        Material dark = AssetDatabase.LoadAssetAtPath<Material>("Assets/capstone_hall/capstone_tripod.mat");
        if (dark == null)
        {
            Shader sh = Shader.Find("Universal Render Pipeline/Lit");
            dark = new Material(sh != null ? sh : Shader.Find("Standard"));
            if (!AssetDatabase.IsValidFolder("Assets/capstone_hall")) AssetDatabase.CreateFolder("Assets", "capstone_hall");
            AssetDatabase.CreateAsset(dark, "Assets/capstone_hall/capstone_tripod.mat");
        }
        Color c = new Color(0.12f, 0.12f, 0.13f);
        dark.color = c;
        if (dark.HasProperty("_BaseColor")) dark.SetColor("_BaseColor", c);
        EditorUtility.SetDirty(dark);

        // 기둥: 바닥 ~ 카메라 바로 아래
        float poleTop = Mathf.Max(0.2f, LensHeight - 0.10f);
        GameObject pole = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        pole.name = "pole";
        Object.DestroyImmediate(pole.GetComponent<Collider>());
        pole.transform.SetParent(tripod.transform, false);
        pole.transform.localPosition = new Vector3(0f, poleTop * 0.5f, 0f);
        pole.transform.localScale = new Vector3(0.04f, poleTop * 0.5f, 0.04f);
        pole.GetComponent<Renderer>().sharedMaterial = dark;

        // 발 받침: 다리가 벌어지는 범위. 로봇이 피해 가도록 장애물로 둔다.
        GameObject foot = GameObject.CreatePrimitive(PrimitiveType.Cube);
        foot.name = "base_obstacle";
        foot.transform.SetParent(tripod.transform, false);
        foot.transform.localPosition = new Vector3(0f, 0.15f, 0f);
        foot.transform.localScale = new Vector3(BaseSize, 0.30f, BaseSize);
        foot.tag = "Obstacle";
        foot.GetComponent<Renderer>().sharedMaterial = dark;
        var o = foot.AddComponent<NavMeshObstacle>();
        o.shape = NavMeshObstacleShape.Box; o.center = Vector3.zero; o.size = Vector3.one; o.carving = true;

        // 카메라 모형이 앵커보다 위/아래로 떨어져 있으면 그대로 따라 내려온다 (앵커의 자식이라 상대 위치 유지)
        Debug.Log("[Capstone360] 360 카메라 높이 " + before.ToString("F2") + " → " + LensHeight.ToString("F2") + " m, 삼각대 추가 (" +
                  p.x.ToString("F2") + ", " + p.z.ToString("F2") + "), 발 받침 " + BaseSize + " m");
        return true;
    }
}
