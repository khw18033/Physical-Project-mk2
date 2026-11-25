// 사람 탐지 표시용 프리팹을 만든다 (PersonVisual 이 Resources 에서 읽는다).
//   Assets/Resources/Person360/Person_M.prefab, Person_F.prefab   Kevin Iglesias "Human Basic Motions FREE" 의 사람 모형
//   Assets/Resources/Person360/PersonIdleWalk_M/F.controller        Speed 값으로 서기 ↔ 걷기를 바꾸는 애니메이터
// 메뉴: Tools/Go1/사람 프리팹 만들기
//   Unity.exe -batchmode -projectPath D:\Go1_Unity -executeMethod PersonAssetBuilder.RunBatch -logFile <log>

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class PersonAssetBuilder
{
    private const string Src = "Assets/Kevin Iglesias/Human Animations", Dst = "Assets/Resources/Person360";

    public static void RunBatch()
    {
        bool ok = Build();
        DumpKit();
        AssetDatabase.SaveAssets();
        EditorApplication.Exit(ok ? 0 : 1);
    }

    [MenuItem("Tools/Go1/사람 프리팹 만들기")]
    public static void Menu() { Build(); AssetDatabase.SaveAssets(); }

    public static bool Build()
    {
        if (!AssetDatabase.IsValidFolder("Assets/Resources")) AssetDatabase.CreateFolder("Assets", "Resources");
        if (!AssetDatabase.IsValidFolder(Dst)) AssetDatabase.CreateFolder("Assets/Resources", "Person360");
        bool a = One("M", "Male", new Color(0.20f, 0.42f, 0.78f));
        bool b = One("F", "Female", new Color(0.80f, 0.30f, 0.42f));
        return a && b;
    }

    private static bool One(string s, string folder, Color tint)
    {
        var ci = CultureInfo.InvariantCulture;
        string prefabSrc = Src + "/Unity Demo Scenes/Human Basic Motions/Prefabs/Human_BasicMotionsDummy_" + s + ".prefab";
        GameObject src = AssetDatabase.LoadAssetAtPath<GameObject>(prefabSrc);
        if (src == null) src = AssetDatabase.LoadAssetAtPath<GameObject>(Src + "/Models/Human" + s + "_Model.fbx");
        if (src == null) { Debug.LogError("[Person] 모형 없음: " + prefabSrc); return false; }

        AnimationClip idle = Clip(Src + "/Animations/" + folder + "/Idles/Human" + s + "@Idle01.fbx");
        AnimationClip walk = Clip(Src + "/Animations/" + folder + "/Movement/Walk/Human" + s + "@Walk01_Forward.fbx");
        if (walk == null) walk = FindClip(Src + "/Animations/" + folder, "Human" + s + "@Walk01_Forward.fbx");
        if (idle == null) idle = FindClip(Src + "/Animations/" + folder, "Human" + s + "@Idle01.fbx");
        if (idle == null || walk == null) { Debug.LogError("[Person] 동작 없음 idle=" + idle + " walk=" + walk); return false; }

        string ctrlPath = Dst + "/PersonIdleWalk_" + s + ".controller";
        AssetDatabase.DeleteAsset(ctrlPath);
        AnimatorController ctrl = AnimatorController.CreateAnimatorControllerAtPath(ctrlPath);
        ctrl.AddParameter("Speed", AnimatorControllerParameterType.Float);
        AnimatorStateMachine sm = ctrl.layers[0].stateMachine;
        AnimatorState stIdle = sm.AddState("Idle"); stIdle.motion = idle;
        AnimatorState stWalk = sm.AddState("Walk"); stWalk.motion = walk;
        sm.defaultState = stIdle;
        var t1 = stIdle.AddTransition(stWalk); t1.hasExitTime = false; t1.duration = 0.2f; t1.AddCondition(AnimatorConditionMode.Greater, 0.25f, "Speed");
        var t2 = stWalk.AddTransition(stIdle); t2.hasExitTime = false; t2.duration = 0.25f; t2.AddCondition(AnimatorConditionMode.Less, 0.15f, "Speed");

        GameObject inst = (GameObject)PrefabUtility.InstantiatePrefab(src);
        PrefabUtility.UnpackPrefabInstance(inst, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        inst.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        foreach (Collider c in inst.GetComponentsInChildren<Collider>(true)) Object.DestroyImmediate(c);
        foreach (Rigidbody r in inst.GetComponentsInChildren<Rigidbody>(true)) Object.DestroyImmediate(r);
        Animator an = inst.GetComponentInChildren<Animator>();
        if (an == null) an = inst.AddComponent<Animator>();
        an.runtimeAnimatorController = ctrl;
        an.applyRootMotion = false;
        an.cullingMode = AnimatorCullingMode.AlwaysAnimate;

        // URP 재질로 바꾼다 (원래 재질의 색·그림은 물려받는다)
        Shader lit = Shader.Find("Universal Render Pipeline/Lit");
        int nMat = 0;
        foreach (Renderer r in inst.GetComponentsInChildren<Renderer>(true))
        {
            Material[] ms = r.sharedMaterials;
            for (int i = 0; i < ms.Length; i++)
            {
                Material o = ms[i];
                string mp = Dst + "/Person_" + s + "_mat" + i + ".mat";
                Material m = AssetDatabase.LoadAssetAtPath<Material>(mp);
                if (m == null) { m = new Material(lit); AssetDatabase.CreateAsset(m, mp); }
                Texture tex = o != null && o.HasProperty("_MainTex") ? o.GetTexture("_MainTex") : null;
                if (tex == null && o != null && o.HasProperty("_BaseMap")) tex = o.GetTexture("_BaseMap");
                // 회색 인형이라 매장의 마네킹과 헷갈린다 → 남자는 파랑, 여자는 분홍 기운을 입힌다
                Color c = tex != null ? Color.Lerp(Color.white, tint, 0.6f) : tint;
                m.SetColor("_BaseColor", c); m.color = c;
                if (tex != null) m.SetTexture("_BaseMap", tex);
                m.SetFloat("_Smoothness", 0.25f);
                EditorUtility.SetDirty(m);
                ms[i] = m; nMat++;
            }
            r.sharedMaterials = ms;
        }

        Bounds b = new Bounds(); bool first = true;
        foreach (Renderer r in inst.GetComponentsInChildren<Renderer>(true)) { if (first) { b = r.bounds; first = false; } else b.Encapsulate(r.bounds); }

        string outPath = Dst + "/Person_" + s + ".prefab";
        PrefabUtility.SaveAsPrefabAsset(inst, outPath, out bool ok);
        Object.DestroyImmediate(inst);
        Debug.Log("[Person] " + outPath + " " + (ok ? "OK" : "실패") + " | 키 " + b.size.y.ToString("F2", ci) + " m, 폭 " + b.size.x.ToString("F2", ci) +
                  " x " + b.size.z.ToString("F2", ci) + " | 바닥 y " + b.min.y.ToString("F2", ci) + " | 재질 " + nMat + " | idle " + idle.name + " (loop " + idle.isLooping + ") walk " + walk.name + " (loop " + walk.isLooping + ")");
        return ok;
    }

    private static AnimationClip Clip(string fbx)
    {
        foreach (Object o in AssetDatabase.LoadAllAssetsAtPath(fbx))
            if (o is AnimationClip c && !c.name.StartsWith("__preview__")) return c;
        return null;
    }

    private static AnimationClip FindClip(string dir, string file)
    {
        foreach (string p in Directory.GetFiles(dir, file, SearchOption.AllDirectories)) return Clip(p.Replace('\\', '/'));
        return null;
    }

    // 매장 에셋(KenneyMiniMarket)의 모형별 크기를 적어 둔다: 맵을 만들 때 실제 크기로 맞추기 위해
    public static void DumpKit()
    {
        var ci = CultureInfo.InvariantCulture;
        string dir = "Assets/KenneyMiniMarket";
        if (!AssetDatabase.IsValidFolder(dir)) return;
        var sb = new StringBuilder("name,sizeX,sizeY,sizeZ,minX,minY,minZ,maxX,maxY,maxZ,renderers,shader\n");
        foreach (string f in Directory.GetFiles(dir, "*.fbx"))
        {
            string p = f.Replace('\\', '/');
            GameObject g = AssetDatabase.LoadAssetAtPath<GameObject>(p);
            if (g == null) continue;
            GameObject inst = Object.Instantiate(g);
            Bounds b = new Bounds(); bool first = true; int n = 0; string sh = "";
            foreach (Renderer r in inst.GetComponentsInChildren<Renderer>(true))
            {
                if (first) { b = r.bounds; first = false; } else b.Encapsulate(r.bounds);
                n++;
                if (r.sharedMaterial != null && r.sharedMaterial.shader != null) sh = r.sharedMaterial.shader.name + (r.sharedMaterial.mainTexture != null ? "+tex" : "");
            }
            sb.AppendLine(Path.GetFileNameWithoutExtension(p) + "," + b.size.x.ToString("F3", ci) + "," + b.size.y.ToString("F3", ci) + "," + b.size.z.ToString("F3", ci) + "," +
                          b.min.x.ToString("F3", ci) + "," + b.min.y.ToString("F3", ci) + "," + b.min.z.ToString("F3", ci) + "," +
                          b.max.x.ToString("F3", ci) + "," + b.max.y.ToString("F3", ci) + "," + b.max.z.ToString("F3", ci) + "," + n + "," + sh);
            Object.DestroyImmediate(inst);
        }
        string outDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "GO1_Proactive_Evaluation", "mall_map");
        Directory.CreateDirectory(outDir);
        File.WriteAllText(Path.Combine(outDir, "kit_sizes.csv"), sb.ToString());
        Debug.Log("[Person] kit sizes → " + outDir);
    }
}
