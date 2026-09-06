using UnityEngine;
using UnityEditor;

public class DistanceMeasureTool : EditorWindow
{
    private Vector3 pointA;
    private Vector3 pointB;
    private bool hasA = false;
    private bool hasB = false;
    private bool picking = false;
    private int pickTarget = 0; // 0=A, 1=B

    [MenuItem("Tools/Distance Measure")]
    static void Open() => GetWindow<DistanceMeasureTool>("Distance Measure");

    void OnEnable() => SceneView.duringSceneGui += OnScene;
    void OnDisable() => SceneView.duringSceneGui -= OnScene;

    void OnGUI()
    {
        EditorGUILayout.HelpBox(
            "버튼을 누른 뒤 씬 뷰에서 표면을 클릭하면 그 점이 찍힙니다.\n" +
            "A, B 두 점을 찍으면 거리를 표시합니다.", MessageType.Info);

        if (GUILayout.Button(picking && pickTarget == 0 ? "A 찍는 중... (씬 클릭)" : "A 점 찍기"))
        { picking = true; pickTarget = 0; }

        if (GUILayout.Button(picking && pickTarget == 1 ? "B 찍는 중... (씬 클릭)" : "B 점 찍기"))
        { picking = true; pickTarget = 1; }

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("A", hasA ? pointA.ToString("F3") : "-");
        EditorGUILayout.LabelField("B", hasB ? pointB.ToString("F3") : "-");

        if (hasA && hasB)
        {
            float d = Vector3.Distance(pointA, pointB);
            float dXZ = Vector3.Distance(
                new Vector3(pointA.x, 0, pointA.z),
                new Vector3(pointB.x, 0, pointB.z));
            EditorGUILayout.Space();
            EditorGUILayout.LabelField("3D 거리", d.ToString("F3") + " m");
            EditorGUILayout.LabelField("수평(XZ) 거리", dXZ.ToString("F3") + " m");
        }

        if (GUILayout.Button("초기화")) { hasA = hasB = false; picking = false; }
    }

    void OnScene(SceneView sv)
    {
        if (picking)
        {
            HandleUtility.AddDefaultControl(GUIUtility.GetControlID(FocusType.Passive));
            Event e = Event.current;
            if (e.type == EventType.MouseDown && e.button == 0)
            {
                Ray ray = HandleUtility.GUIPointToWorldRay(e.mousePosition);
                if (Physics.Raycast(ray, out RaycastHit hit, 1000f))
                {
                    if (pickTarget == 0) { pointA = hit.point; hasA = true; }
                    else { pointB = hit.point; hasB = true; }
                    picking = false;
                    Repaint();
                    e.Use();
                }
            }
        }

        if (hasA) Handles.SphereHandleCap(0, pointA, Quaternion.identity, 0.05f, EventType.Repaint);
        if (hasB) Handles.SphereHandleCap(0, pointB, Quaternion.identity, 0.05f, EventType.Repaint);
        if (hasA && hasB)
        {
            Handles.color = Color.yellow;
            Handles.DrawLine(pointA, pointB);
            Vector3 mid = (pointA + pointB) * 0.5f;
            Handles.Label(mid, Vector3.Distance(pointA, pointB).ToString("F3") + " m");
        }
    }
}