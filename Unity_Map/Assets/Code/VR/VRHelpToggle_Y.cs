using UnityEngine;
using UnityEngine.InputSystem;

public class VRHelpToggle_Y : MonoBehaviour
{
    [Header("Help Panel (UI)")]
    public GameObject helpPanel;

    [Header("Map Root (hide while help is open)")]
    public GameObject mapRoot;

    [Header("Reality Canvas (optional)")]
    public GameObject cameraCanvas;

    [Header("Camera Switch Ref")]
    public VRCameraViewSwitch cameraSwitch;

    [Header("Input - Y Button")]
    public InputActionReference yToggleAction;

    private bool isOpen = false;
    private bool mapWasActiveBeforeHelp = false;

    private float lastToggleTime = -999f;
    private float debounce = 0.25f;

    void Awake()
    {
        if (helpPanel != null)
            helpPanel.SetActive(false);
    }

    void OnEnable()
    {
        if (yToggleAction != null && yToggleAction.action != null)
        {
            yToggleAction.action.performed += OnToggle;
            yToggleAction.action.Enable();
        }
    }

    void OnDisable()
    {
        if (yToggleAction != null && yToggleAction.action != null)
        {
            yToggleAction.action.performed -= OnToggle;
            yToggleAction.action.Disable();
        }
    }

    private void OnToggle(InputAction.CallbackContext ctx)
    {
        if (Time.time - lastToggleTime < debounce)
            return;

        lastToggleTime = Time.time;

        bool nextOpen = !isOpen;

        if (nextOpen)
        {
            // 도움말을 열기 직전 Map의 기존 상태를 저장한다.
            // Map이 원래 꺼져 있었다면 도움말을 닫아도 계속 꺼진 상태를 유지한다.
            if (mapRoot != null)
            {
                mapWasActiveBeforeHelp = mapRoot.activeSelf;
                mapRoot.SetActive(false);
            }

            // 도움말을 여는 순간 사람 시점으로 강제 복귀
            if (cameraSwitch != null)
                cameraSwitch.ForceXRView();

            if (cameraCanvas != null)
                cameraCanvas.SetActive(false);
        }
        else
        {
            // 도움말을 열기 전 Map 상태로만 복원한다.
            if (mapRoot != null)
                mapRoot.SetActive(mapWasActiveBeforeHelp);
        }

        isOpen = nextOpen;

        if (helpPanel != null)
            helpPanel.SetActive(isOpen);

        Debug.Log(
            $"Y Toggle -> Help: {isOpen}, " +
            $"Map: {(mapRoot != null ? mapRoot.activeSelf : false)}, " +
            $"MapBeforeHelp: {mapWasActiveBeforeHelp}"
        );
    }

    public bool IsHelpOpen()
    {
        return isOpen;
    }
}
