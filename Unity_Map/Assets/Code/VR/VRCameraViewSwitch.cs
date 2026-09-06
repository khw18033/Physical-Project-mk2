using UnityEngine;
using UnityEngine.InputSystem;

public class VRCameraViewSwitch : MonoBehaviour
{
    [Header("XR Main Camera (HMD)")]
    public Camera xrMainCamera;

    [Header("GO1 Camera")]
    public Camera go1Camera;

    [Header("Help Panel Lock")]
    public GameObject helpPanel;

    [Header("Input - Toggle")]
    public InputActionReference toggleAction;

    private bool isGo1View = false;
    private float lastToggleTime = -999f;
    private float debounce = 0.25f;

    void Start()
    {
        SetGo1View(false);
    }

    void OnEnable()
    {
        if (toggleAction != null && toggleAction.action != null)
        {
            toggleAction.action.performed += OnToggle;
            toggleAction.action.Enable();
        }
    }

    void OnDisable()
    {
        if (toggleAction != null && toggleAction.action != null)
        {
            toggleAction.action.performed -= OnToggle;
            toggleAction.action.Disable();
        }
    }

    private void OnToggle(InputAction.CallbackContext ctx)
    {
        // 도움말 열려 있으면 X 무시
        if (helpPanel != null && helpPanel.activeSelf)
        {
            Debug.Log("Help Panel is open -> X toggle ignored");
            return;
        }

        if (Time.time - lastToggleTime < debounce)
            return;

        lastToggleTime = Time.time;

        SetGo1View(!isGo1View);
    }

    // 외부에서도 호출 가능
    public void SetGo1View(bool enableGo1View)
    {
        isGo1View = enableGo1View;

        if (xrMainCamera != null)
            xrMainCamera.gameObject.SetActive(!isGo1View);

        if (go1Camera != null)
            go1Camera.gameObject.SetActive(isGo1View);

        Debug.Log("GO1 View = " + isGo1View);
    }

    // 도움말 열 때 사람 시점 강제 복귀용
    public void ForceXRView()
    {
        SetGo1View(false);
    }

    public bool IsGo1View()
    {
        return isGo1View;
    }
}