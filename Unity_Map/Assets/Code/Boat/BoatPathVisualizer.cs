using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// GO1Agent/BoatAgent가 생성하거나 재주행하는 경로를
/// LineRenderer로 Scene 뷰와 Game 뷰에 표시합니다.
///
/// - 생성 중 경로: recordedPath
/// - 재주행/재탐색 경로: localReplayPath
/// </summary>
[DisallowMultipleComponent]
public class BoatPathVisualizer : MonoBehaviour
{
    [Header("Reference")]
    [Tooltip("같은 Boat 오브젝트의 BoatAgent를 연결합니다. 비워두면 자동으로 찾습니다.")]
    public BoatAgent boatAgent;

    [Header("Visibility")]
    public bool showRecordedPath = true;
    public bool showReplayPath = true;

    [Tooltip("경로가 비어도 마지막으로 표시한 경로를 유지합니다.")]
    public bool keepLastVisiblePath = true;

    [Header("Line Settings")]
    [Min(0.001f)]
    public float lineWidth = 0.12f;

    [Tooltip("수면과 겹쳐 깜빡이지 않도록 경로를 위로 올리는 값입니다.")]
    public float yOffset = 0.25f;

    public Color recordedPathColor = Color.cyan;
    public Color replayPathColor = Color.yellow;

    [Tooltip("직접 지정하지 않으면 URP Unlit 또는 Sprites/Default 머티리얼을 자동 생성합니다.")]
    public Material lineMaterial;

    [Header("Waypoint Gizmos")]
    public bool showWaypointPoints = true;

    [Min(0.01f)]
    public float waypointRadius = 0.18f;

    private LineRenderer recordedLine;
    private LineRenderer replayLine;

    private Vector3[] lastRecordedPath = System.Array.Empty<Vector3>();
    private Vector3[] lastReplayPath = System.Array.Empty<Vector3>();

    private Material runtimeRecordedMaterial;
    private Material runtimeReplayMaterial;

    private void Awake()
    {
        if (boatAgent == null)
            boatAgent = GetComponent<BoatAgent>();

        recordedLine = CreateLineRenderer(
            "Recorded_ML_Path",
            recordedPathColor,
            out runtimeRecordedMaterial
        );

        replayLine = CreateLineRenderer(
            "Replay_Replanned_Path",
            replayPathColor,
            out runtimeReplayMaterial
        );
    }

    private void LateUpdate()
    {
        if (boatAgent == null)
            return;

        UpdateRecordedPath();
        UpdateReplayPath();
    }

    private void UpdateRecordedPath()
    {
        if (!showRecordedPath)
        {
            recordedLine.enabled = false;
            return;
        }

        List<Vector3> path =
            boatAgent.GetRecordedPathSnapshot(false);

        if (path != null && path.Count >= 2)
        {
            lastRecordedPath = path.ToArray();
            ApplyPath(recordedLine, lastRecordedPath);
            return;
        }

        if (keepLastVisiblePath && lastRecordedPath.Length >= 2)
        {
            ApplyPath(recordedLine, lastRecordedPath);
        }
        else
        {
            recordedLine.enabled = false;
        }
    }

    private void UpdateReplayPath()
    {
        if (!showReplayPath)
        {
            replayLine.enabled = false;
            return;
        }

        Vector3[] path =
            boatAgent.GetLocalReplayPathSnapshot();

        if (path != null && path.Length >= 2)
        {
            lastReplayPath = (Vector3[])path.Clone();
            ApplyPath(replayLine, lastReplayPath);
            return;
        }

        if (keepLastVisiblePath && lastReplayPath.Length >= 2)
        {
            ApplyPath(replayLine, lastReplayPath);
        }
        else
        {
            replayLine.enabled = false;
        }
    }

    private void ApplyPath(
        LineRenderer line,
        Vector3[] path
    )
    {
        if (line == null ||
            path == null ||
            path.Length < 2)
        {
            if (line != null)
                line.enabled = false;

            return;
        }

        line.enabled = true;
        line.startWidth = lineWidth;
        line.endWidth = lineWidth;
        line.positionCount = path.Length;

        for (int i = 0; i < path.Length; i++)
        {
            Vector3 point = path[i];
            point.y += yOffset;
            line.SetPosition(i, point);
        }
    }

    private LineRenderer CreateLineRenderer(
        string childName,
        Color color,
        out Material runtimeMaterial
    )
    {
        Transform existing = transform.Find(childName);
        GameObject lineObject;

        if (existing != null)
        {
            lineObject = existing.gameObject;
        }
        else
        {
            lineObject = new GameObject(childName);
            lineObject.transform.SetParent(transform, false);
        }

        LineRenderer line =
            lineObject.GetComponent<LineRenderer>();

        if (line == null)
            line = lineObject.AddComponent<LineRenderer>();

        line.useWorldSpace = true;
        line.loop = false;
        line.alignment = LineAlignment.View;
        line.textureMode = LineTextureMode.Stretch;
        line.numCapVertices = 4;
        line.numCornerVertices = 4;
        line.shadowCastingMode = ShadowCastingMode.Off;
        line.receiveShadows = false;
        line.startWidth = lineWidth;
        line.endWidth = lineWidth;
        line.startColor = color;
        line.endColor = color;

        if (lineMaterial != null)
        {
            runtimeMaterial = null;
            line.material = lineMaterial;
        }
        else
        {
            Shader shader =
                Shader.Find("Universal Render Pipeline/Unlit");

            if (shader == null)
                shader = Shader.Find("Sprites/Default");

            if (shader == null)
                shader = Shader.Find("Unlit/Color");

            runtimeMaterial =
                shader != null
                    ? new Material(shader)
                    : null;

            if (runtimeMaterial != null)
            {
                runtimeMaterial.name =
                    childName + "_RuntimeMaterial";

                runtimeMaterial.color = color;
                line.material = runtimeMaterial;
            }
        }

        line.enabled = false;
        return line;
    }

    [ContextMenu("Clear Displayed Paths")]
    public void ClearDisplayedPaths()
    {
        lastRecordedPath =
            System.Array.Empty<Vector3>();

        lastReplayPath =
            System.Array.Empty<Vector3>();

        if (recordedLine != null)
        {
            recordedLine.positionCount = 0;
            recordedLine.enabled = false;
        }

        if (replayLine != null)
        {
            replayLine.positionCount = 0;
            replayLine.enabled = false;
        }
    }

    private void OnDestroy()
    {
        if (runtimeRecordedMaterial != null)
            Destroy(runtimeRecordedMaterial);

        if (runtimeReplayMaterial != null)
            Destroy(runtimeReplayMaterial);
    }

    private void OnDrawGizmos()
    {
        if (!showWaypointPoints)
            return;

        if (lastRecordedPath != null &&
            lastRecordedPath.Length >= 2)
        {
            Gizmos.color = recordedPathColor;

            for (int i = 0;
                 i < lastRecordedPath.Length;
                 i++)
            {
                Vector3 point =
                    lastRecordedPath[i];

                point.y += yOffset;
                Gizmos.DrawSphere(
                    point,
                    waypointRadius
                );
            }
        }

        if (lastReplayPath != null &&
            lastReplayPath.Length >= 2)
        {
            Gizmos.color = replayPathColor;

            for (int i = 0;
                 i < lastReplayPath.Length;
                 i++)
            {
                Vector3 point =
                    lastReplayPath[i];

                point.y += yOffset;
                Gizmos.DrawWireSphere(
                    point,
                    waypointRadius * 1.25f
                );
            }
        }
    }
}
