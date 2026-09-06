using UnityEngine;

public class SimpleFPSController : MonoBehaviour
{
    public float moveSpeed = 5f;      // 이동 속도
    public float mouseSensitivity = 2f; // 마우스 감도

    private float verticalRotation = 0f;
    private Transform cameraTransform;

    void Start()
    {
        // 마우스 커서를 화면 중앙에 고정하고 숨김
        Cursor.lockState = CursorLockMode.Locked;
        
        // 플레이어 자식으로 있는 카메라 찾기
        cameraTransform = GetComponentInChildren<Camera>().transform;
    }

    void Update()
    {
        // 1. 마우스 회전 처리
        float mouseX = Input.GetAxis("Mouse X") * mouseSensitivity;
        float mouseY = Input.GetAxis("Mouse Y") * mouseSensitivity;

        // 좌우 회전 (플레이어 몸통 전체를 돌림)
        transform.Rotate(0, mouseX, 0);

        // 상하 회전 (카메라만 위아래로 끄덕임)
        verticalRotation -= mouseY;
        verticalRotation = Mathf.Clamp(verticalRotation, -90f, 90f); // 고개가 꺾이지 않게 제한
        cameraTransform.localRotation = Quaternion.Euler(verticalRotation, 0, 0);

        // 2. 키보드 이동 처리
        float moveX = Input.GetAxis("Horizontal"); // A, D 키
        float moveZ = Input.GetAxis("Vertical");   // W, S 키

        Vector3 move = transform.right * moveX + transform.forward * moveZ;
        
        // 실제 이동 적용 (초당 moveSpeed 만큼)
        transform.Translate(move * moveSpeed * Time.deltaTime, Space.World);
    }
}