using UnityEngine;
using UnityEngine.AI;
using System.Text;

public class GO1PathExporter : MonoBehaviour
{
    public NavMeshAgent agent;

    [ContextMenu("Print Current Path")]
    public void PrintCurrentPath()
    {
        if (agent == null || agent.path == null)
        {
            Debug.LogWarning("agent 또는 path가 없습니다.");
            return;
        }

        Vector3[] corners = agent.path.corners;

        if (corners == null || corners.Length == 0)
        {
            Debug.LogWarning("경로 점이 없습니다.");
            return;
        }

        StringBuilder sb = new StringBuilder();
        sb.AppendLine("[GO1PathExporter] Current Path");

        for (int i = 0; i < corners.Length; i++)
        {
            Vector3 p = corners[i];
            sb.AppendLine($"[{i}] x={p.x:F3}, y={p.y:F3}, z={p.z:F3}");
        }

        Debug.Log(sb.ToString());
    }
}