// 탐지된 것이 사람이면 상자 대신 사람 모형을 세운다 (2026-11-25).
//  - 상자(큐브)는 그대로 둔다: 충돌체와 NavMesh 파내기는 상자가 맡는다. 상자의 그림만 끄고 그 자리에 사람 모형을 보여 준다.
//  - 사람 모형은 Resources/Person360/Person_M, Person_F 프리팹 (PersonAssetBuilder 가 Kevin Iglesias "Human Basic Motions" 로 만든다).
//    프리팹이 없으면 아무것도 바꾸지 않고 예전처럼 상자를 보여 준다.
//  - 사람이 움직이면 걷는 동작, 서 있으면 서 있는 동작. 바닥에는 누가 찾았는지 색 원판을 깐다 (360° = 주황, Go1 = 하늘색).

using UnityEngine;

public static class PersonVisual
{
    private static readonly string[] Words =
        { "person", "people", "human", "man", "woman", "men", "women", "boy", "girl", "child", "kid", "pedestrian", "사람" };

    /// <summary>탐지 이름이 사람을 뜻하는가. 낱말 단위로 본다 ("mannequin" 은 사람이 아니다).</summary>
    public static bool IsPerson(string label)
    {
        if (string.IsNullOrEmpty(label)) return false;
        string s = label.ToLowerInvariant();
        int i = 0;
        while (i < s.Length)
        {
            while (i < s.Length && !char.IsLetter(s[i])) i++;
            int j = i;
            while (j < s.Length && char.IsLetter(s[j])) j++;
            if (j > i)
            {
                string tok = s.Substring(i, j - i);
                foreach (string w in Words) if (tok == w) return true;
            }
            i = j;
        }
        return false;
    }

    private static GameObject[] prefabs; private static bool loaded; private static int next;
    private static Transform root;

    public static GameObject NextPrefab()
    {
        if (!loaded)
        {
            loaded = true;
            var m = Resources.Load<GameObject>("Person360/Person_M");
            var f = Resources.Load<GameObject>("Person360/Person_F");
            if (m != null && f != null) prefabs = new[] { m, f };
            else if (m != null || f != null) prefabs = new[] { m != null ? m : f };
            else Debug.LogWarning("[PersonVisual] Resources/Person360 에 사람 프리팹이 없어 사람도 상자로 표시한다. 메뉴 Tools/Go1/사람 프리팹 만들기 를 실행하면 된다.");
        }
        if (prefabs == null) return null;
        return prefabs[next++ % prefabs.Length];
    }

    public static Transform Root()
    {
        if (root == null) root = new GameObject("PersonVisuals").transform;
        return root;
    }

    /// <summary>탐지 상자 하나에 대해 매번 불러 준다. 사람이면 모형을 붙이고, 아니게 되면 뗀다.</summary>
    public static void Sync(GameObject cube, string label, float floorY, Color markColor)
    {
        if (cube == null) return;
        bool person = IsPerson(label);
        var link = cube.GetComponent<PersonVisualLink>();
        if (!person)
        {
            if (link != null) link.Detach();
            return;
        }
        if (link == null) link = cube.AddComponent<PersonVisualLink>();
        link.Attach(floorY, markColor);
    }
}

/// <summary>탐지 상자에 붙어서 사람 모형이 상자를 따라다니게 한다.</summary>
public class PersonVisualLink : MonoBehaviour
{
    public float followRate = 8f;         // 클수록 상자 위치를 빨리 따라간다
    public float walkSpeedOn = 0.25f;     // 이 속도(m/s)보다 빠르면 걷는 동작
    public float turnRateDeg = 360f;

    private GameObject visual; private Animator anim; private Renderer cubeRend; private Renderer markRend;
    private float floorY; private Vector3 lastTarget; private float speed; private bool hasLast;
    private static readonly int SpeedId = Animator.StringToHash("Speed");

    public bool HasVisual => visual != null;

    public void Attach(float floor, Color markColor)
    {
        floorY = floor;
        if (visual == null)
        {
            GameObject prefab = PersonVisual.NextPrefab();
            if (prefab == null) return;
            visual = Instantiate(prefab, PersonVisual.Root());
            visual.name = "Person_" + gameObject.name;
            Vector3 p = transform.position;
            visual.transform.SetPositionAndRotation(new Vector3(p.x, floorY, p.z), Quaternion.Euler(0f, Random.Range(0f, 360f), 0f));
            anim = visual.GetComponentInChildren<Animator>();

            // 바닥 표시: 누가 찾았는지 색으로 구분
            GameObject mark = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            mark.name = "mark";
            Destroy(mark.GetComponent<Collider>());
            mark.transform.SetParent(visual.transform, false);
            mark.transform.localPosition = new Vector3(0f, 0.01f, 0f);
            mark.transform.localScale = new Vector3(0.55f, 0.005f, 0.55f);
            markRend = mark.GetComponent<Renderer>();
            hasLast = false;
        }
        if (cubeRend == null) cubeRend = GetComponent<Renderer>();
        if (cubeRend != null && cubeRend.enabled) cubeRend.enabled = false;
        if (markRend != null && markRend.material.color != markColor) markRend.material.color = markColor;
    }

    public void Detach()
    {
        if (visual != null) { Destroy(visual); visual = null; anim = null; markRend = null; }
        if (cubeRend == null) cubeRend = GetComponent<Renderer>();
        if (cubeRend != null && !cubeRend.enabled) cubeRend.enabled = true;
    }

    void LateUpdate()
    {
        if (visual == null) return;
        float dt = Time.deltaTime;
        if (dt <= 0f) return;
        Vector3 target = new Vector3(transform.position.x, floorY, transform.position.z);
        if (!hasLast) { lastTarget = target; hasLast = true; visual.transform.position = target; }

        Vector3 before = visual.transform.position;
        Vector3 now = Vector3.Lerp(before, target, 1f - Mathf.Exp(-followRate * dt));
        visual.transform.position = now;

        Vector3 v = (now - before) / dt; v.y = 0f;
        speed = Mathf.Lerp(speed, v.magnitude, 1f - Mathf.Exp(-6f * dt));
        if (speed > walkSpeedOn && v.sqrMagnitude > 1e-4f)
        {
            Quaternion face = Quaternion.LookRotation(v.normalized, Vector3.up);
            visual.transform.rotation = Quaternion.RotateTowards(visual.transform.rotation, face, turnRateDeg * dt);
        }
        if (anim != null) anim.SetFloat(SpeedId, speed);
        lastTarget = target;
    }

    void OnEnable() { if (visual != null) visual.SetActive(true); }
    void OnDisable() { if (visual != null) visual.SetActive(false); }
    void OnDestroy() { if (visual != null) Destroy(visual); }
}
