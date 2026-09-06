using UnityEngine;
using TMPro;

public class HazardDetector : MonoBehaviour
{
    [Header("필수 연결")]
    public TMP_Text alertText;   // UI 텍스트
    public Camera playerCamera;  // 1인칭 카메라

    [Header("설정")]
    public float proximityRange = 1.0f; // 접근 감지 거리

    // 충돌 상태 통합 관리
    private bool isColliding = false;

    void Start()
    {
        if (alertText != null) alertText.text = "";
        
        if (playerCamera == null)
        {
            playerCamera = GetComponentInChildren<Camera>();
        }
    }

    void Update()
    {
        // 충돌 중이 아닐 때만 '접근 경고'를 띄움
        if (!isColliding)
        {
            CheckInstallationProximity();
        }
    }

    // 1. 접근 감지 (Installation 전용) -> ★ 여기는 시야각(IsInView) 제한 유지!
    void CheckInstallationProximity()
    {
        Collider[] hits = Physics.OverlapSphere(transform.position, proximityRange);
        
        bool foundInstallation = false;

        foreach (var hit in hits)
        {
            // 태그가 Installation이고 + 카메라 시야 안에 있을 때만
            if (hit.CompareTag("Installation") && IsInView(hit.transform.position))
            {
                foundInstallation = true;
                ShowMessage("장애물이 0.5미터 이내에 있습니다. 조심하십시오.");
                break;
            }
        }
        
        // 근처에 없으면 메시지 끄기
        if (!foundInstallation) 
        {
            alertText.text = "";
        }
    }

    // 2. 충돌 감지 (방향 판별 로직 추가됨)
    void OnCollisionEnter(Collision collision)
    {
        // 이전 코드에 있던 'if (!IsInView(...)) return;' 삭제함
        // 이제 등 뒤로 부딪혀도 아래 코드가 실행됩니다.

        string tag = collision.gameObject.tag;
        
        if (tag == "Door" || tag == "Stair" || tag == "Elevator" || tag == "Installation" || tag == "Restroom")
        {
            isColliding = true; // 접근 경고보다 우선순위 높임

            Vector3 contactPoint = collision.contacts[0].point;
            string direction = GetCollisionDirection(contactPoint);

            if (tag == "Door")
            {
                ShowMessage($"문이 로봇의 {direction}에 있습니다. 조심하십시오.");
            }
            else if (tag == "Stair")
            {
                ShowMessage($"로봇의 {direction}에 계단이 있습니다. 추락의 위험이 있습니다.");
            }
            else if (tag == "Elevator")
            {
                ShowMessage($"엘리베이터가 로봇의 {direction}에 있습니다. 조심하십시오.");
            }
            else if (tag == "Installation")
            {
                ShowMessage($"위험! 장애물이 로봇의 {direction}에 충돌하였습니다! 즉시 후퇴하세요!");
            }
            else if (tag == "Restroom")
            {
                ShowMessage($"화장실이 로봇의 {direction}에 있습니다. 조심하십시오.");
            }
        }
    }

    void OnCollisionExit(Collision collision)
    {
        string tag = collision.gameObject.tag;

        if (tag == "Door" || tag == "Stair" || tag == "Elevator" || tag == "Installation"  || tag == "Restroom")
        {
            isColliding = false; // 충돌 상태 해제
            alertText.text = ""; // 메시지 지우기
        }
    }

    // 시야각 판별 함수
    bool IsInView(Vector3 targetPosition)
    {
        if (playerCamera == null) return true;

        Vector3 directionToTarget = targetPosition - playerCamera.transform.position;
        float angle = Vector3.Angle(playerCamera.transform.forward, directionToTarget);

        return angle < (playerCamera.fieldOfView * 0.5f);
    }

    void ShowMessage(string message)
    {
        if (alertText != null) alertText.text = message;
        Debug.Log(message);
    }

    // ★ 새로 추가된 함수: 충돌 방향 판별 (로봇 센서 시뮬레이션)
    string GetCollisionDirection(Vector3 contactPoint)
    {
        // 1. 월드 좌표계의 충돌 지점을 플레이어 기준의 로컬 좌표계로 변환
        Vector3 localPoint = transform.InverseTransformPoint(contactPoint);

        // 2. X(좌우)와 Z(전후) 중 절댓값이 큰 쪽을 주 축으로 판단
        if (Mathf.Abs(localPoint.z) > Mathf.Abs(localPoint.x))
        {
            return localPoint.z > 0 ? "전방" : "후방";
        }
        else
        {
            return localPoint.x > 0 ? "우측" : "좌측";
        }
    }
    
    void OnDrawGizmosSelected()
    {
        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(transform.position, proximityRange);
    }
}