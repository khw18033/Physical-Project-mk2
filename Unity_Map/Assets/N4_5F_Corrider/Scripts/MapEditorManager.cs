using UnityEngine;
using UnityEngine.EventSystems;
using System.Collections.Generic;

public class MapEditorManager : MonoBehaviour
{
    [Header("필수 연결")]
    public LayerMask groundLayer;   // 바닥 레이어
    public GameObject controlPanel; // (선택) 조작 설명 UI 패널
    public MapEditorCamera cameraScript; 
    public Material ghostMaterial;  // 반투명 재질

    [Header("프리팹 목록")]
    public GameObject[] buildingPrefabs;

    // 내부 변수
    private GameObject currentGhost;
    private bool isPlacing = false;
    private bool isEditingExisting = false;
    private Vector3 originalPosition;

    // 재질 복구용 저장소
    private Dictionary<Renderer, Material[]> originalMaterials = new Dictionary<Renderer, Material[]>();

    void Start()
    {
        if (cameraScript == null) 
            cameraScript = Camera.main.GetComponent<MapEditorCamera>();
    }

    void Update()
    {
        // 설치/이동 모드일 때
        if (isPlacing && currentGhost != null)
        {
            // 1. 물체 이동 (마우스 따라다니기)
            MoveGhostToMouse();
            
            // 2. 회전 (R키)
            if(Input.GetKeyDown(KeyCode.R))
                currentGhost.transform.Rotate(Vector3.up, 90f);

            // ★ 3. 확인 (Enter)
            if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
            {
                ConfirmPlacement();
            }

            // ★ 4. 취소 (ESC)
            if (Input.GetKeyDown(KeyCode.Escape))
            {
                CancelPlacement();
            }
        }
        // 일반 모드일 때
        else
        {
            // UI 위가 아닐 때만 클릭 감지
            if (!EventSystem.current.IsPointerOverGameObject() && Input.GetMouseButtonDown(0))
            {
                DetectObjectClick();
            }
        }
    }

    void MoveGhostToMouse()
    {
        Ray ray = Camera.main.ScreenPointToRay(Input.mousePosition);
        RaycastHit hit;

        if (Physics.Raycast(ray, out hit, 1000f, groundLayer))
        {
            Vector3 targetPos = hit.point;
            targetPos.x = Mathf.Round(targetPos.x * 2) / 2f; // 0.5 단위 스냅
            targetPos.z = Mathf.Round(targetPos.z * 2) / 2f;
            targetPos.y = 0; 

            currentGhost.transform.position = targetPos;
        }
    }

    void DetectObjectClick()
    {
        Ray ray = Camera.main.ScreenPointToRay(Input.mousePosition);
        RaycastHit hit;

        if (Physics.Raycast(ray, out hit))
        {
            GameObject hitObj = hit.collider.gameObject;

            // 바닥이 아니면 편집 시작
            if (hitObj.layer != GetLayerIndex(groundLayer))
            {
                StartEditing(hitObj);
            }
        }
    }

    int GetLayerIndex(LayerMask mask)
    {
        int layer = 0;
        int layerMask = mask.value;
        while (layerMask > 0)
        {
            layerMask = layerMask >> 1;
            layer++;
        }
        return layer - 1;
    }

    // ---------------------------------------------------------
    // ★ 소환(Create)과 편집(Edit) 로직
    // ---------------------------------------------------------

    // [UI 버튼 연결] 새 물체 생성
    public void OnClickCreateButton(int index)
    {
        // 이미 들고 있는 게 있다면 취소
        if (currentGhost != null) CancelPlacement();

        // 1. 생성
        GameObject newObj = Instantiate(buildingPrefabs[index]);
        newObj.name = buildingPrefabs[index].name; // 이름 깔끔하게

        // 2. 모드 설정 (새로 만들기)
        isEditingExisting = false;

        // 3. 배치 모드 시작 (재질 변경, 카메라 추적 포함)
        StartPlacementMode(newObj);
    }

    // 기존 물체 클릭 시
    void StartEditing(GameObject obj)
    {
        if (obj.transform.parent != null) 
            obj = obj.transform.root.gameObject;

        // 모드 설정 (수정 하기)
        isEditingExisting = true;
        originalPosition = obj.transform.position;

        // 배치 모드 시작
        StartPlacementMode(obj);
    }

    // ★ 공통 배치 로직 (여기로 모든 로직을 몰아넣어 동작 통일)
    void StartPlacementMode(GameObject obj)
    {
        currentGhost = obj;
        isPlacing = true;
        
        // UI 패널 켜기 (안내 문구용 - 이제 버튼 클릭은 안 함)
        if(controlPanel != null) controlPanel.SetActive(true);

        // 1. Collider 끄기 (레이캐스트 방해 금지)
        SetColliders(currentGhost, false);

        // 2. 재질 반투명 변경 (Ghost Material)
        ChangeToGhostMaterial(currentGhost);

        // 3. 카메라 추적 시작
        if (cameraScript != null) cameraScript.SetFollowTarget(currentGhost.transform);
    }

    // ---------------------------------------------------------
    // 확정 및 취소
    // ---------------------------------------------------------

    void ConfirmPlacement()
    {
        if (currentGhost == null) return;
        Debug.Log("설치 확정 (Enter)");

        // 1. Collider 복구
        SetColliders(currentGhost, true);

        // 2. 원래 재질 복구
        RestoreOriginalMaterials();

        // 3. 카메라 추적 해제
        if (cameraScript != null) cameraScript.SetFollowTarget(null);

        // 초기화
        currentGhost = null;
        isPlacing = false;
        if(controlPanel != null) controlPanel.SetActive(false);
    }

    void CancelPlacement()
    {
        if (currentGhost == null) return;
        Debug.Log("설치 취소 (ESC)");

        if (isEditingExisting)
        {
            // 수정 중이었다면 원래 위치, 원래 재질로 복귀
            currentGhost.transform.position = originalPosition;
            SetColliders(currentGhost, true);
            RestoreOriginalMaterials();
        }
        else
        {
            // 새로 만들던 중이었다면 삭제
            Destroy(currentGhost);
            // 삭제했으므로 재질 복구 로직 필요 없음 (Dictionary만 비움)
            originalMaterials.Clear();
        }

        if (cameraScript != null) cameraScript.SetFollowTarget(null);

        currentGhost = null;
        isPlacing = false;
        if(controlPanel != null) controlPanel.SetActive(false);
    }

    // ---------------- 유틸리티 ----------------

    void SetColliders(GameObject obj, bool active)
    {
        Collider[] colliders = obj.GetComponentsInChildren<Collider>();
        foreach (var col in colliders) col.enabled = active;
    }

    void ChangeToGhostMaterial(GameObject obj)
    {
        // 혹시 남아있을지 모를 이전 기록 삭제
        originalMaterials.Clear();
        
        Renderer[] renderers = obj.GetComponentsInChildren<Renderer>();
        foreach (var rend in renderers)
        {
            // 원래 재질 저장
            originalMaterials[rend] = rend.sharedMaterials;

            // Ghost 재질로 교체
            Material[] newMats = new Material[rend.sharedMaterials.Length];
            for (int i = 0; i < newMats.Length; i++)
            {
                newMats[i] = ghostMaterial;
            }
            rend.sharedMaterials = newMats;
        }
    }

    void RestoreOriginalMaterials()
    {
        foreach (var kvp in originalMaterials)
        {
            if (kvp.Key != null)
                kvp.Key.sharedMaterials = kvp.Value;
        }
        originalMaterials.Clear();
    }
}