using UnityEngine;
using UnityEngine.SceneManagement;

public class PauseManager : MonoBehaviour
{
    [Header("UI 연결")]
    public GameObject pausePanel;

    [Header("제어할 스크립트 연결 (중요)")]
    // MonoBehaviour로 선언하면 어떤 스크립트든 드래그해서 넣을 수 있습니다.
    public MonoBehaviour fpsController; // 플레이어 이동/회전 스크립트
    public CameraManager cameraManager; // 시점 변환(K키) 스크립트

    [Header("설정")]
    public string mainMenuSceneName = "MainMenu";

    private bool isPaused = false;

    void Start()
    {
        if (pausePanel != null)
            pausePanel.SetActive(false);
    }

    void Update()
    {
        if (Input.GetKeyDown(KeyCode.Escape))
        {
            if (isPaused)
            {
                Resume();
            }
            else
            {
                Pause();
            }
        }
    }

    public void Resume()
    {
        pausePanel.SetActive(false);
        Time.timeScale = 1f;
        isPaused = false;

        // ★ 핵심: 조작 스크립트 다시 켜기
        if (fpsController != null) fpsController.enabled = true;
        if (cameraManager != null) cameraManager.enabled = true;

        // 마우스 다시 잠그기
        Cursor.lockState = CursorLockMode.Locked;
        Cursor.visible = false;
    }

    public void Pause()
    {
        pausePanel.SetActive(true);
        Time.timeScale = 0f;
        isPaused = true;

        // ★ 핵심: 조작 스크립트 끄기 (입력 차단)
        if (fpsController != null) fpsController.enabled = false;
        if (cameraManager != null) cameraManager.enabled = false;

        // 마우스 풀기
        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;
    }

    public void RestartGame()
    {
        Time.timeScale = 1f;
        SceneManager.LoadScene(SceneManager.GetActiveScene().name);
    }

    public void GoToMainMenu()
    {
        Time.timeScale = 1f;
        SceneManager.LoadScene(mainMenuSceneName);
    }

    public void QuitGame()
    {
        Application.Quit();
    }
}