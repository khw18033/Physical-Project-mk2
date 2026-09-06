using UnityEngine;
using TMPro; // TextMeshPro를 쓰기 위해 필요

public class CameraManager : MonoBehaviour
{
    [Header("Cameras")]
    public GameObject fpsCamera; // 1인칭 카메라
    public GameObject topCamera; // 3인칭 탑뷰 카메라

    [Header("UI")]
    public TMP_Text modeText;    // 화면에 표시할 텍스트

    private bool isFpsMode = true; // 현재 상태 저장 (true면 1인칭)

    void Start()
    {
        // 게임 시작 시 초기화
        UpdateCameraState();
    }

    void Update()
    {
        // K 키 입력 감지
        if (Input.GetKeyDown(KeyCode.K))
        {
            isFpsMode = !isFpsMode; // 상태 반전 (true <-> false)
            UpdateCameraState();    // 상태 적용
        }
    }

    void UpdateCameraState()
    {
        // 1. 카메라 켜고 끄기
        fpsCamera.SetActive(isFpsMode);
        topCamera.SetActive(!isFpsMode);

        // 2. UI 텍스트 변경
        if (isFpsMode)
        {
            modeText.text = "1인칭 모드";
        }
        else
        {
            modeText.text = "3인칭 탑뷰 모드";
        }
    }
}