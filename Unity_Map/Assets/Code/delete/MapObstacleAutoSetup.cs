using UnityEngine;
using UnityEngine.AI;

public class MapObstacleAutoSetup : MonoBehaviour
{
    [Header("Target Root")]
    public Transform mapRoot;

    [Header("Name Filters")]
    [Tooltip("이 이름이 포함된 오브젝트만 처리. 비워두면 이름 상관없이 전부 검사")]
    public string[] includeKeywords = new string[]
    {
        "wall", "desk", "chair", "Sofa", "box", "door", "bookshelf", "cube", "object", "leg", "Seat", "Top"
    };

    [Tooltip("이 이름이 포함된 오브젝트는 제외")]
    public string[] excludeKeywords = new string[]
    {
        "light", "camera"
    };

    [Header("Tag Settings")]
    [Tooltip("includeKeywords에 해당하는 오브젝트 전부 Obstacle 태그 설정")]
    public bool autoSetTags = true;

    [Header("Collider Strategy")]
    public bool removeBoxCollider = false;
    public bool removeMeshCollider = true;
    public bool addBoxColliderIfMissing = true;
    public bool addMeshColliderIfMissing = false;
    public bool meshColliderIsTrigger = false;
    public bool boxColliderIsTrigger = false;

    [Header("Rigidbody Handling")]
    public bool forceKinematicIfRigidbodyExists = true;
    public bool forceConvexIfRigidbodyExists = true;

    [Header("Obstacle Settings")]
    public bool addNavMeshObstacle = true;
    public bool carve = true;
    public bool updateExistingObstacle = true;

    [Header("Run")]
    public bool runOnStart = true;

    void Start()
    {
        if (runOnStart)
            ApplyToChildren();
    }

    [ContextMenu("Apply To Children")]
    public void ApplyToChildren()
    {
        EnsureTagExists("Obstacle");

        Transform root = mapRoot != null ? mapRoot : transform;

        int processed = 0;
        int skipped = 0;
        int meshAdded = 0;
        int meshRemoved = 0;
        int boxAdded = 0;
        int boxRemoved = 0;
        int obstacleAdded = 0;
        int rigidbodyKinematicSet = 0;
        int tagSet = 0;

        foreach (Transform t in root.GetComponentsInChildren<Transform>(true))
        {
            if (t == root) continue;

            string objName = t.name.ToLower();

            if (!ShouldInclude(objName))
            {
                skipped++;
                continue;
            }

            if (t.GetComponent<Camera>() != null || t.GetComponent<Light>() != null)
            {
                skipped++;
                continue;
            }

            MeshFilter mf = t.GetComponent<MeshFilter>();
            SkinnedMeshRenderer smr = t.GetComponent<SkinnedMeshRenderer>();

            if (mf == null && smr == null)
            {
                skipped++;
                continue;
            }

            // includeKeywords에 해당하면 전부 Obstacle 태그
            if (autoSetTags)
            {
                try
                {
                    t.gameObject.tag = "Obstacle";
                    tagSet++;
                }
                catch
                {
                    Debug.LogWarning($"[MapObstacleAutoSetup] Obstacle 태그 설정 실패: {t.name}");
                }
            }

            Rigidbody rb = t.GetComponent<Rigidbody>();
            if (rb != null && forceKinematicIfRigidbodyExists && !rb.isKinematic)
            {
                rb.isKinematic = true;
                rigidbodyKinematicSet++;
            }

            if (removeBoxCollider)
            {
                BoxCollider[] boxes = t.GetComponents<BoxCollider>();
                foreach (BoxCollider bc in boxes)
                {
                    DestroyImmediateOrRuntime(bc);
                    boxRemoved++;
                }
            }

            if (removeMeshCollider)
            {
                MeshCollider[] meshCols = t.GetComponents<MeshCollider>();
                foreach (MeshCollider mc in meshCols)
                {
                    DestroyImmediateOrRuntime(mc);
                    meshRemoved++;
                }
            }

            if (addBoxColliderIfMissing)
            {
                BoxCollider box = t.GetComponent<BoxCollider>();
                if (box == null)
                {
                    box = t.gameObject.AddComponent<BoxCollider>();
                    box.isTrigger = boxColliderIsTrigger;
                    boxAdded++;
                }
                else
                {
                    box.isTrigger = boxColliderIsTrigger;
                }
            }

            if (addMeshColliderIfMissing)
            {
                MeshCollider meshCol = t.GetComponent<MeshCollider>();
                if (meshCol == null)
                {
                    meshCol = t.gameObject.AddComponent<MeshCollider>();
                    meshAdded++;
                }

                bool shouldConvex = rb != null && forceConvexIfRigidbodyExists;
                meshCol.convex = shouldConvex;
                meshCol.isTrigger = meshColliderIsTrigger;

                if (mf != null && mf.sharedMesh != null)
                    meshCol.sharedMesh = mf.sharedMesh;
                else if (smr != null && smr.sharedMesh != null)
                    meshCol.sharedMesh = smr.sharedMesh;
            }

            if (addNavMeshObstacle)
            {
                NavMeshObstacle obstacle = t.GetComponent<NavMeshObstacle>();
                if (obstacle == null)
                {
                    obstacle = t.gameObject.AddComponent<NavMeshObstacle>();
                    obstacle.carving = carve;
                    obstacleAdded++;
                }
                else if (updateExistingObstacle)
                {
                    obstacle.carving = carve;
                }
            }

            processed++;
        }

        Debug.Log(
            $"[MapObstacleAutoSetup] 완료 | processed={processed}, skipped={skipped}, " +
            $"tagSet={tagSet}, " +
            $"meshAdded={meshAdded}, meshRemoved={meshRemoved}, " +
            $"boxAdded={boxAdded}, boxRemoved={boxRemoved}, " +
            $"obstacleAdded={obstacleAdded}, rigidbodyKinematicSet={rigidbodyKinematicSet}"
        );
    }

    private void EnsureTagExists(string tagName)
    {
#if UNITY_EDITOR
        UnityEditorInternal.InternalEditorUtility.AddTag(tagName);
#endif
    }

    [ContextMenu("Remove Added NavMeshObstacles")]
    public void RemoveNavMeshObstacles()
    {
        Transform root = mapRoot != null ? mapRoot : transform;
        int removed = 0;

        foreach (Transform t in root.GetComponentsInChildren<Transform>(true))
        {
            NavMeshObstacle obstacle = t.GetComponent<NavMeshObstacle>();
            if (obstacle != null)
            {
                DestroyImmediateOrRuntime(obstacle);
                removed++;
            }
        }

        Debug.Log($"[MapObstacleAutoSetup] NavMeshObstacle 제거 완료: {removed}");
    }

    [ContextMenu("Remove MeshColliders")]
    public void RemoveMeshColliders()
    {
        Transform root = mapRoot != null ? mapRoot : transform;
        int removed = 0;

        foreach (Transform t in root.GetComponentsInChildren<Transform>(true))
        {
            MeshCollider[] meshCols = t.GetComponents<MeshCollider>();
            foreach (MeshCollider meshCol in meshCols)
            {
                DestroyImmediateOrRuntime(meshCol);
                removed++;
            }
        }

        Debug.Log($"[MapObstacleAutoSetup] MeshCollider 제거 완료: {removed}");
    }

    [ContextMenu("Remove BoxColliders")]
    public void RemoveBoxColliders()
    {
        Transform root = mapRoot != null ? mapRoot : transform;
        int removed = 0;

        foreach (Transform t in root.GetComponentsInChildren<Transform>(true))
        {
            BoxCollider[] boxes = t.GetComponents<BoxCollider>();
            foreach (BoxCollider box in boxes)
            {
                DestroyImmediateOrRuntime(box);
                removed++;
            }
        }

        Debug.Log($"[MapObstacleAutoSetup] BoxCollider 제거 완료: {removed}");
    }

    private bool ShouldInclude(string objName)
    {
        foreach (string ex in excludeKeywords)
        {
            if (!string.IsNullOrWhiteSpace(ex) && objName.Contains(ex.ToLower()))
                return false;
        }

        if (includeKeywords == null || includeKeywords.Length == 0)
            return true;

        foreach (string inc in includeKeywords)
        {
            if (!string.IsNullOrWhiteSpace(inc) && objName.Contains(inc.ToLower()))
                return true;
        }

        return false;
    }

    private void DestroyImmediateOrRuntime(Object obj)
    {
#if UNITY_EDITOR
        if (!Application.isPlaying)
            DestroyImmediate(obj);
        else
            Destroy(obj);
#else
        Destroy(obj);
#endif
    }
}