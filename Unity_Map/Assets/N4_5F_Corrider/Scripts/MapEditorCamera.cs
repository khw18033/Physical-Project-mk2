using UnityEngine;

public class MapEditorCamera : MonoBehaviour
{
    [Header("이동 설정")]
    public float moveSpeed = 20f;       // WASD 이동 속도
    public float zoomSpeed = 10f;       // 휠 줌 속도
    public float smoothTime = 0.2f;     // 따라다닐 때 부드러움 정도

    [Header("배치 시점 설정")]
    // ★ 중요: 물체를 설치할 때 카메라가 물체로부터 얼마나 떨어져 있을지 결정
    // (0, 15, -10) 정도로 설정하면 물체를 위에서 45도 각도로 내려다보는 뷰가 됨
    public Vector3 placementViewingOffset = new Vector3(0, 15, -12); 

    [Header("줌 제한")]
    public float minZoom = 5f;
    public float maxZoom = 50f;

    // 내부 변수
    private Transform followTarget;
    private Vector3 currentVelocity;
    private Vector3 targetPosition;

    void Start()
    {
        targetPosition = transform.position;
    }

    void LateUpdate()
    {
        // 1. 대상을 따라다니는 모드 (설치 중)
        if (followTarget != null)
        {
            // 목표 위치 = 물체 위치 + 설정된 오프셋
            Vector3 desiredPos = followTarget.position + placementViewingOffset;
            
            // 줌(Y축 높이)은 휠로 조절 가능하게 유지하고 싶다면 아래 주석 해제 후 로직 수정 필요
            // 하지만 "화면 중앙 고정"을 원하셨으므로 오프셋을 그대로 따라가는 게 가장 확실합니다.
            
            transform.position = Vector3.SmoothDamp(transform.position, desiredPos, ref currentVelocity, smoothTime);
            
            // 자유 이동 좌표도 현재 위치로 동기화 (설치 끝나면 여기서부터 이동 시작)
            targetPosition = transform.position; 
        }
        // 2. 자유 이동 모드 (일반 상태 - WASD)
        else
        {
            HandleWASDMovement();
        }

        // 3. 줌 (공통)
        HandleZoom();
    }

    void HandleWASDMovement()
    {
        // ★ 마우스 대신 키보드 입력 받기
        float h = Input.GetAxis("Horizontal"); // A, D 또는 좌우 화살표
        float v = Input.GetAxis("Vertical");   // W, S 또는 상하 화살표

        if (h != 0 || v != 0)
        {
            // 월드 기준 앞/뒤/좌/우 이동 (카메라가 보는 방향 무시하고 절대 좌표로 이동)
            // 쿼터뷰에서는 보통 X, Z 축 평행 이동이 직관적입니다.
            Vector3 moveDir = new Vector3(h, 0, v);

            // 혹은 카메라가 보는 방향 기준으로 이동하고 싶다면:
            // Vector3 forward = transform.forward; forward.y = 0;
            // Vector3 right = transform.right; right.y = 0;
            // Vector3 moveDir = (forward.normalized * v + right.normalized * h);

            transform.Translate(moveDir * moveSpeed * Time.deltaTime, Space.World);
        }
    }

    void HandleZoom()
    {
        float scroll = Input.GetAxis("Mouse ScrollWheel");
        if (scroll != 0)
        {
            // 자유 이동 모드일 때만 높이 조절 (설치 중엔 오프셋 따름)
            if (followTarget == null)
            {
                Vector3 pos = transform.position;
                pos.y -= scroll * zoomSpeed * 100f * Time.deltaTime;
                pos.y = Mathf.Clamp(pos.y, minZoom, maxZoom);
                transform.position = pos;
            }
            else 
            {
                // 설치 중에도 줌을 하고 싶다면 오프셋(placementViewingOffset)의 y값을 조절해야 함
                placementViewingOffset.y -= scroll * zoomSpeed * 100f * Time.deltaTime;
                placementViewingOffset.y = Mathf.Clamp(placementViewingOffset.y, minZoom, maxZoom);
            }
        }
    }

    public void SetFollowTarget(Transform target)
    {
        followTarget = target;
        // 타겟이 생기면 속도 초기화 (튀는 현상 방지)
        currentVelocity = Vector3.zero;
    }
}