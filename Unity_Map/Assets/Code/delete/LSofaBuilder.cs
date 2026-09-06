using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
#endif

[ExecuteAlways]
public class LSofaBuilder : MonoBehaviour
{
    [Header("Overall size (meters)")]
    public float width = 3.0f;      // X
    public float depth = 2.0f;      // Z

    [Header("L-shape arms")]
    public float shortArm = 1.10f;  // 짧은 쪽 (Z 방향 메인 좌석 깊이)
    public float longArm  = 2.00f;  // 긴 쪽 (X 방향 사이드 좌석 길이)

    [Header("Height")]
    public float seatHeight = 0.55f;

    [Header("Options")]
    public bool addColliders = true;

    const string ROOT = "SofaParts";
    bool _rebuildQueued;

    void OnEnable()   => ScheduleRebuild();
    void OnValidate() => ScheduleRebuild();

    void ScheduleRebuild()
    {
        if (!isActiveAndEnabled) return;
        if (_rebuildQueued) return;
        _rebuildQueued = true;

#if UNITY_EDITOR
        EditorApplication.delayCall += () =>
        {
            _rebuildQueued = false;
            if (this == null) return;
            if (!isActiveAndEnabled) return;
            Rebuild();
        };
#else
        _rebuildQueued = false;
        Rebuild();
#endif
    }

    [ContextMenu("Rebuild Sofa")]
    void Rebuild()
    {
        _rebuildQueued = false;

        // 최소값 보호 (0 이하로 가면 큐브가 이상해질 수 있어서)
        width      = Mathf.Max(0.05f, width);
        depth      = Mathf.Max(0.05f, depth);
        shortArm   = Mathf.Clamp(shortArm, 0.05f, depth);
        longArm    = Mathf.Clamp(longArm,  0.05f, width);
        seatHeight = Mathf.Max(0.01f, seatHeight);

        // 정리
        var old = transform.Find(ROOT);
        if (old) SafeDestroy(old.gameObject);

        var root = new GameObject(ROOT);
        root.transform.SetParent(transform, false);

        // 1) 메인 좌석: (가로 width, 세로 shortArm)
        // Z 위치: 전체 depth 중 메인좌석이 차지하는 shortArm을 "뒤쪽"에 붙인 느낌으로 배치
        CreateBlock(
            root.transform,
            "MainSeat",
            new Vector3(width, seatHeight, shortArm),
            new Vector3(0f, seatHeight * 0.5f, -(depth - shortArm) * 0.5f)
        );

        // 2) 사이드 좌석: (가로 longArm, 세로 depth - shortArm)
        float sideDepth = Mathf.Max(0.05f, depth - shortArm);

        CreateBlock(
            root.transform,
            "SideSeat",
            new Vector3(longArm, seatHeight, sideDepth),
            new Vector3(
                (width - longArm) * 0.5f,
                seatHeight * 0.5f,
                sideDepth * 0.5f
            )
        );
    }

    void CreateBlock(Transform parent, string name, Vector3 size, Vector3 localPos)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = name;
        go.transform.SetParent(parent, false);
        go.transform.localScale = size;
        go.transform.localPosition = localPos;

        if (!addColliders)
        {
            var col = go.GetComponent<Collider>();
            if (col) SafeDestroy(col);
        }
    }

    void SafeDestroy(Object obj)
    {
        if (!obj) return;

        if (Application.isPlaying)
        {
            Destroy(obj);
            return;
        }

#if UNITY_EDITOR
        Undo.DestroyObjectImmediate(obj);
#else
        Destroy(obj);
#endif
    }
}
