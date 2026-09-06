using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// GO1Agent에서 NavMesh 경로 계산 책임을 분리한 컴포넌트입니다.
/// 전역 경로 생성, 경로 유효성 검사, 다음 waypoint 선택,
/// 물리 장애물 검사와 NavMeshAgent 위치 동기화를 담당합니다.
///
/// C2/C3 Unity 평가에서는 기준 경로를 잠글 수 있습니다.
/// - C2: 장애물 생성 후에도 잠긴 기준 경로 유지
/// - C3: 장애물 생성 시 잠금 해제 후 NavMesh 경로 재계산
/// </summary>
[DisallowMultipleComponent]
public class GO1PathPlanner : MonoBehaviour
{
    [Header("NavMesh Settings")]
    [Tooltip("경로 계산에 사용할 NavMesh area mask입니다.")]
    public int areaMask = NavMesh.AllAreas;

    [Tooltip("NavMeshAgent가 있으면 transform과 별도로 위치만 동기화합니다.")]
    public bool synchronizeNavMeshAgent = true;

    [Tooltip("경로 계산 실패 로그를 출력합니다.")]
    public bool debugPathCalculation = false;

    [Header("C2/C3 Fixed Path Evaluation")]
    [Tooltip("기준 경로 잠금 상태를 Scene 뷰와 Console에서 확인할 때 사용합니다.")]
    public bool debugLockedPath = false;

    private NavMeshAgent navAgent;
    private NavMeshPath currentPath;

    private readonly List<Vector3> lockedPath = new List<Vector3>();
    private Vector3[] lockedViewCorners = Array.Empty<Vector3>();
    private bool lockedPathEnabled;

    private static readonly Vector3[] EmptyCorners = Array.Empty<Vector3>();

    public bool IsPathLocked => lockedPathEnabled && lockedPath.Count >= 2;
    public IReadOnlyList<Vector3> LockedPath => lockedPath;

    public Vector3[] CurrentCorners
    {
        get
        {
            EnsureInitialized();

            if (IsPathLocked)
                return lockedViewCorners ?? EmptyCorners;

            return currentPath != null && currentPath.corners != null
                ? currentPath.corners
                : EmptyCorners;
        }
    }

    public int CurrentCornerCount => CurrentCorners.Length;

    public bool IsCurrentPathComplete
    {
        get
        {
            EnsureInitialized();

            if (IsPathLocked)
                return lockedViewCorners != null && lockedViewCorners.Length >= 2;

            return currentPath != null &&
                   currentPath.status == NavMeshPathStatus.PathComplete &&
                   currentPath.corners != null &&
                   currentPath.corners.Length >= 2;
        }
    }

    public bool IsCurrentPathInvalidOrPartial
    {
        get
        {
            EnsureInitialized();

            if (IsPathLocked)
                return lockedViewCorners == null || lockedViewCorners.Length < 2;

            return currentPath == null ||
                   currentPath.status == NavMeshPathStatus.PathInvalid ||
                   currentPath.status == NavMeshPathStatus.PathPartial;
        }
    }

    private void Awake()
    {
        EnsureInitialized();
    }

    public void EnsureInitialized()
    {
        if (currentPath == null)
            currentPath = new NavMeshPath();

        if (navAgent == null)
            navAgent = GetComponent<NavMeshAgent>();

        if (navAgent != null)
        {
            navAgent.updatePosition = false;
            navAgent.updateRotation = false;
        }
    }

    /// <summary>
    /// C2/C3 두 번째 주행에서 사용할 기준 경로를 고정합니다.
    /// </summary>
    public bool SetLockedPath(IReadOnlyList<Vector3> sourcePath)
    {
        lockedPath.Clear();
        lockedViewCorners = EmptyCorners;
        lockedPathEnabled = false;

        if (sourcePath == null || sourcePath.Count < 2)
            return false;

        for (int i = 0; i < sourcePath.Count; i++)
        {
            Vector3 point = sourcePath[i];

            if (lockedPath.Count == 0 ||
                Vector3.Distance(lockedPath[lockedPath.Count - 1], point) > 0.001f)
            {
                lockedPath.Add(point);
            }
        }

        if (lockedPath.Count < 2)
        {
            lockedPath.Clear();
            return false;
        }

        lockedPathEnabled = true;
        BuildLockedView(lockedPath[0], lockedPath[lockedPath.Count - 1]);

        if (debugLockedPath)
        {
            Debug.Log(
                "[GO1PathPlanner] 기준 경로 잠금 | points=" + lockedPath.Count,
                this
            );
        }

        return true;
    }

    public void ClearLockedPath()
    {
        if (debugLockedPath && lockedPathEnabled)
            Debug.Log("[GO1PathPlanner] 기준 경로 잠금 해제", this);

        lockedPathEnabled = false;
        lockedPath.Clear();
        lockedViewCorners = EmptyCorners;
    }

    public bool CalculatePath(Vector3 from, Vector3 to)
    {
        EnsureInitialized();

        if (IsPathLocked)
        {
            BuildLockedView(from, to);
            return lockedViewCorners != null && lockedViewCorners.Length >= 2;
        }

        bool calculated = NavMesh.CalculatePath(from, to, areaMask, currentPath);

        if (!calculated && debugPathCalculation)
        {
            Debug.LogWarning(
                $"[GO1PathPlanner] NavMesh 경로 계산 실패 | from={from}, to={to}",
                this
            );
        }

        return calculated;
    }

    public float GetPathDistance(Vector3 from, Vector3 to)
    {
        if (!CalculatePath(from, to) || IsCurrentPathInvalidOrPartial)
            return Vector3.Distance(from, to);

        float distance = 0f;
        Vector3[] corners = CurrentCorners;

        for (int i = 1; i < corners.Length; i++)
            distance += Vector3.Distance(corners[i - 1], corners[i]);

        return distance;
    }

    public Vector3 GetNextWaypoint(Vector3 currentPosition, Vector3 targetPosition, float switchDistance)
    {
        Vector3[] corners = CurrentCorners;

        if (corners.Length < 2)
            return targetPosition;

        Vector3 next = corners[1];
        float threshold = Mathf.Max(0f, switchDistance);

        if (corners.Length > 2 && Vector3.Distance(currentPosition, next) < threshold)
            next = corners[2];

        return next;
    }

    public Vector3 GetNextWaypointDirection(
        Vector3 currentPosition,
        Vector3 targetPosition,
        float switchDistance,
        Vector3 fallbackDirection)
    {
        if (!CalculatePath(currentPosition, targetPosition) || IsCurrentPathInvalidOrPartial)
            return fallbackDirection.sqrMagnitude > 0.000001f
                ? fallbackDirection.normalized
                : Vector3.forward;

        Vector3 next = GetNextWaypoint(currentPosition, targetPosition, switchDistance);
        Vector3 direction = next - currentPosition;
        direction.y = 0f;

        if (direction.sqrMagnitude < 0.000001f)
        {
            direction = targetPosition - currentPosition;
            direction.y = 0f;
        }

        return direction.sqrMagnitude > 0.000001f
            ? direction.normalized
            : Vector3.forward;
    }

    public bool HasCompletePath(Vector3 from, Vector3 to)
    {
        NavMeshPath checkPath = new NavMeshPath();
        bool calculated = NavMesh.CalculatePath(from, to, areaMask, checkPath);

        return calculated &&
               checkPath.status == NavMeshPathStatus.PathComplete &&
               checkPath.corners != null &&
               checkPath.corners.Length >= 2;
    }

    public bool IsPathBlockedByNavMesh(Vector3 from, Vector3 to)
    {
        return !HasCompletePath(from, to);
    }

    public bool IsPathPhysicallyBlocked(
        Vector3 from,
        Vector3 to,
        LayerMask obstacleLayerMask,
        float pathCheckRadius,
        float pathCheckHeight,
        bool drawDebugLine = true)
    {
        NavMeshPath checkPath = new NavMeshPath();
        bool calculated = NavMesh.CalculatePath(from, to, areaMask, checkPath);

        if (!calculated ||
            checkPath.status != NavMeshPathStatus.PathComplete ||
            checkPath.corners == null ||
            checkPath.corners.Length < 2)
        {
            return true;
        }

        Vector3[] corners = checkPath.corners;
        float radius = Mathf.Max(0.01f, pathCheckRadius);
        float height = Mathf.Max(0.21f, pathCheckHeight);

        for (int i = 0; i < corners.Length - 1; i++)
        {
            Vector3 a = corners[i];
            Vector3 b = corners[i + 1];
            Vector3 direction = b - a;
            direction.y = 0f;

            float distance = direction.magnitude;
            if (distance < 0.01f)
                continue;

            direction.Normalize();

            Vector3 p1 = a + Vector3.up * 0.2f;
            Vector3 p2 = a + Vector3.up * height;

            bool hit = Physics.CapsuleCast(
                p1,
                p2,
                radius,
                direction,
                out RaycastHit hitInfo,
                distance,
                obstacleLayerMask,
                QueryTriggerInteraction.Ignore
            );

            if (drawDebugLine)
            {
                Debug.DrawLine(
                    a + Vector3.up * 0.05f,
                    b + Vector3.up * 0.05f,
                    hit ? Color.red : Color.green,
                    1.0f
                );
            }

            if (!hit)
                continue;

            Debug.LogWarning(
                $"[GO1PathPlanner] 경로 구간 장애물 감지: " +
                $"{hitInfo.collider.name}, segment={i}, dist={hitInfo.distance:F2}",
                this
            );
            return true;
        }

        return false;
    }

    public void SyncAgentPosition(Vector3 position)
    {
        EnsureInitialized();

        if (!synchronizeNavMeshAgent || navAgent == null || !navAgent.enabled)
            return;

        if (navAgent.isOnNavMesh)
            navAgent.nextPosition = position;
    }

    public bool Warp(Vector3 position)
    {
        EnsureInitialized();

        if (!synchronizeNavMeshAgent || navAgent == null || !navAgent.enabled)
            return false;

        if (!navAgent.isOnNavMesh)
            return false;

        return navAgent.Warp(position);
    }

    private void BuildLockedView(Vector3 currentPosition, Vector3 targetPosition)
    {
        if (!IsPathLocked)
        {
            lockedViewCorners = EmptyCorners;
            return;
        }

        int closestSegment = 0;
        float closestDistance = float.MaxValue;
        float closestT = 0f;

        Vector2 p = new Vector2(currentPosition.x, currentPosition.z);

        for (int i = 0; i < lockedPath.Count - 1; i++)
        {
            Vector2 a = new Vector2(lockedPath[i].x, lockedPath[i].z);
            Vector2 b = new Vector2(lockedPath[i + 1].x, lockedPath[i + 1].z);
            Vector2 ab = b - a;

            if (ab.sqrMagnitude < 0.000001f)
                continue;

            float t = Mathf.Clamp01(Vector2.Dot(p - a, ab) / ab.sqrMagnitude);
            Vector2 projected = a + ab * t;
            float distance = Vector2.Distance(p, projected);

            if (distance < closestDistance)
            {
                closestDistance = distance;
                closestSegment = i;
                closestT = t;
            }
        }

        Vector3 segmentStart = lockedPath[closestSegment];
        Vector3 segmentEnd = lockedPath[closestSegment + 1];
        Vector3 projected3D = Vector3.Lerp(segmentStart, segmentEnd, closestT);
        projected3D.y = currentPosition.y;

        List<Vector3> view = new List<Vector3>();
        view.Add(currentPosition);

        // 현재 위치에서 가장 가까운 경로 구간의 끝점부터 남은 경로를 제공합니다.
        // 시작점 자체가 다음 waypoint로 남지 않도록 segmentEnd부터 추가합니다.
        for (int i = closestSegment + 1; i < lockedPath.Count; i++)
        {
            Vector3 point = lockedPath[i];
            if (view.Count == 0 || Vector3.Distance(view[view.Count - 1], point) > 0.001f)
                view.Add(point);
        }

        if (view.Count < 2)
            view.Add(targetPosition);
        else
            view[view.Count - 1] = targetPosition;

        lockedViewCorners = view.ToArray();
    }
}
