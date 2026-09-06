// VERSION: RIGHT_STICK_TRANSLATION_BUTTON_YAW_V3_DYNAMIC_PLAYER_BLOCK
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Serialization;

[DefaultExecutionOrder(-100)]
public class VRGo1TeleopController : MonoBehaviour
{
    [Header("References")]
    public UnityTeleopAndMirror utm;

    [Tooltip("왼쪽 조이스틱으로 캐릭터를 이동시키는 Provider입니다. 항상 활성 상태로 유지합니다.")]
    public Behaviour playerMoveProvider;

    [Tooltip("오른쪽 조이스틱으로 캐릭터가 회전하는 것을 막으려면 연결합니다. 예: Snap Turn Provider, Continuous Turn Provider")]
    public Behaviour playerTurnProvider;

    [Header("Player / Go1 Input Separation")]
    [Tooltip("캐릭터 이동에 사용하는 Move 액션을 연결합니다. 이 액션에서 오른손 컨트롤러 바인딩만 런타임에 차단합니다.")]
    public InputActionReference playerMove2D;

    [Tooltip("캐릭터 Move 액션의 오른손 컨트롤러 바인딩을 차단합니다. 왼손 이동 입력은 유지됩니다.")]
    public bool blockRightHandPlayerMove = true;

    [Tooltip("오른쪽 조이스틱이 캐릭터 회전에도 연결되어 있다면 체크합니다.")]
    public bool disablePlayerTurnProvider = true;

    [Tooltip("오른쪽 Go1 조이스틱이 움직이는 동안 캐릭터 Move Provider 전체를 잠급니다. 이 동안 왼쪽 조이스틱 이동도 잠깁니다.")]
    public bool blockPlayerMoveWhileGo1StickActive = true;

    [Range(0f, 0.95f)]
    [Tooltip("이 값보다 오른쪽 조이스틱 입력이 클 때 캐릭터 이동을 잠급니다.")]
    public float playerMoveBlockThreshold = 0.15f;

    [Header("Go1 Camera Screen Toggle")]
    public VRCameraViewSwitch cameraViewSwitch;
    public GameObject go1CameraScreenRoot;
    public MJPEGReceiver mjpegReceiver;
    public InputActionReference toggleGo1CameraScreenButton;

    public bool onlyShowScreenInGo1View = true;
    public bool hideScreenWhenExitGo1View = true;
    public bool screenStartsVisible = false;

    [Header("Go1 Input - Right Controller")]
    [Tooltip("오른쪽 컨트롤러 조이스틱 Vector2 액션을 연결합니다. 위/아래는 전후, 좌/우는 평행 이동입니다.")]
    [FormerlySerializedAs("move2D")]
    public InputActionReference go1Move2D;

    [Tooltip("오른쪽 컨트롤러 버튼 1입니다. 누르는 동안 Go1이 왼쪽으로 회전합니다.")]
    public InputActionReference turnLeftButton;

    [Tooltip("오른쪽 컨트롤러 버튼 2입니다. 누르는 동안 Go1이 오른쪽으로 회전합니다.")]
    public InputActionReference turnRightButton;

    [Tooltip("비상 정지 버튼입니다. 필요하지 않으면 비워도 됩니다.")]
    public InputActionReference estopHold;

    [Header("Input Direction")]
    [Tooltip("체크하면 오른쪽 조이스틱의 좌우 이동 방향을 반전합니다.")]
    public bool invertStrafe = false;

    // 이전 버전 호환용입니다. 회전 방향 반전은
    // GO1CoordinateMapper의 Command Invert Yaw에서 관리합니다.
    [SerializeField, HideInInspector]
    private bool invertTurn = false;

    [SerializeField, HideInInspector]
    private bool legacyTurnFlagMigrated = false;

    [Header("Input Filtering")]
    [Range(0f, 0.95f)]
    public float deadzone = 0.15f;

    [Header("Debug")]
    public bool debugLog = false;
    public float debugHz = 5f;

    private readonly List<int> blockedPlayerMoveBindingIndices = new List<int>();

    private float _nextDbg;
    private bool go1CameraScreenVisible;
    private bool playerMoveDisabledByGo1Stick;

    void Reset()
    {
        utm = FindFirstObjectByType<UnityTeleopAndMirror>();
        cameraViewSwitch = FindFirstObjectByType<VRCameraViewSwitch>();
        mjpegReceiver = FindFirstObjectByType<MJPEGReceiver>();
    }

    void Start()
    {
        MigrateLegacyTurnFlag();

        // 왼쪽 조이스틱을 사용하는 캐릭터 이동 Provider는 계속 활성화합니다.
        if (playerMoveProvider != null)
            playerMoveProvider.enabled = true;

        // 오른쪽 조이스틱이 캐릭터 회전에도 전달되는 것을 차단합니다.
        if (disablePlayerTurnProvider && playerTurnProvider != null)
            playerTurnProvider.enabled = false;

        SetGo1CameraScreen(screenStartsVisible);
    }

    void OnEnable()
    {
        go1Move2D?.action?.Enable();
        SubscribeGo1MoveBlockEvents();
        turnLeftButton?.action?.Enable();
        turnRightButton?.action?.Enable();
        estopHold?.action?.Enable();
        toggleGo1CameraScreenButton?.action?.Enable();

        BlockRightHandBindingsFromPlayerMove();
    }

    void OnDisable()
    {
        StopRobot();
        UnsubscribeGo1MoveBlockEvents();
        SetPlayerMoveBlockedByGo1Stick(false);
        RestorePlayerMoveBindings();
        SetGo1CameraScreen(false);
    }

    void Update()
    {
        RefreshPlayerMoveBlockFromGo1Stick();
        HandleGo1CameraScreenToggle();

        if (hideScreenWhenExitGo1View && !IsGo1View())
        {
            if (go1CameraScreenVisible)
                SetGo1CameraScreen(false);
        }
    }

    void FixedUpdate()
    {
        if (utm == null)
            return;

        Vector2 stick = go1Move2D != null
            ? go1Move2D.action.ReadValue<Vector2>()
            : Vector2.zero;

        stick = ApplyDeadzone(stick, deadzone);

        // 오른쪽 조이스틱은 Go1의 각도를 바꾸지 않습니다.
        // Y축: 전진/후진, X축: 좌우 평행 이동
        float vx = stick.y;
        float vy = invertStrafe ? stick.x : -stick.x;

        // 회전은 오른쪽 컨트롤러의 버튼 1, 버튼 2로만 수행합니다.
        float wz = 0f;

        if (IsPressed(turnLeftButton))
            wz += 1f;

        if (IsPressed(turnRightButton))
            wz -= 1f;

        int estop = IsPressed(estopHold) ? 1 : 0;

        if (estop == 1)
        {
            vx = 0f;
            vy = 0f;
            wz = 0f;
        }

        utm.SendTeleopCmd(
            vx * utm.maxVx,
            vy * utm.maxVy,
            wz * utm.maxWz,
            estop
        );

        if (debugLog && Time.time >= _nextDbg)
        {
            _nextDbg = Time.time + 1f / Mathf.Max(0.1f, debugHz);

            Debug.Log(
                $"[VRGo1] rightStick={stick} " +
                $"vx={vx:F2} vy={vy:F2} wz={wz:F2} estop={estop}"
            );
        }
    }

    private void SubscribeGo1MoveBlockEvents()
    {
        if (go1Move2D == null || go1Move2D.action == null)
            return;

        go1Move2D.action.performed -= OnGo1MovePerformed;
        go1Move2D.action.canceled -= OnGo1MoveCanceled;
        go1Move2D.action.performed += OnGo1MovePerformed;
        go1Move2D.action.canceled += OnGo1MoveCanceled;
    }

    private void UnsubscribeGo1MoveBlockEvents()
    {
        if (go1Move2D == null || go1Move2D.action == null)
            return;

        go1Move2D.action.performed -= OnGo1MovePerformed;
        go1Move2D.action.canceled -= OnGo1MoveCanceled;
    }

    private void OnGo1MovePerformed(InputAction.CallbackContext context)
    {
        Vector2 value = context.ReadValue<Vector2>();
        bool active = value.sqrMagnitude >= playerMoveBlockThreshold * playerMoveBlockThreshold;
        SetPlayerMoveBlockedByGo1Stick(active);
    }

    private void OnGo1MoveCanceled(InputAction.CallbackContext context)
    {
        SetPlayerMoveBlockedByGo1Stick(false);
    }

    private void RefreshPlayerMoveBlockFromGo1Stick()
    {
        if (!blockPlayerMoveWhileGo1StickActive ||
            go1Move2D == null ||
            go1Move2D.action == null)
        {
            SetPlayerMoveBlockedByGo1Stick(false);
            return;
        }

        Vector2 value = go1Move2D.action.ReadValue<Vector2>();
        bool active = value.sqrMagnitude >= playerMoveBlockThreshold * playerMoveBlockThreshold;
        SetPlayerMoveBlockedByGo1Stick(active);
    }

    private void SetPlayerMoveBlockedByGo1Stick(bool blocked)
    {
        if (!blockPlayerMoveWhileGo1StickActive)
            blocked = false;

        if (playerMoveProvider == null)
            return;

        if (blocked)
        {
            if (!playerMoveDisabledByGo1Stick && playerMoveProvider.enabled)
            {
                playerMoveProvider.enabled = false;
                playerMoveDisabledByGo1Stick = true;

                if (debugLog)
                    Debug.Log("[VRGo1] 오른쪽 Go1 조이스틱 입력 감지: 캐릭터 이동 잠금");
            }
        }
        else if (playerMoveDisabledByGo1Stick)
        {
            playerMoveProvider.enabled = true;
            playerMoveDisabledByGo1Stick = false;

            if (debugLog)
                Debug.Log("[VRGo1] 오른쪽 Go1 조이스틱 중립: 캐릭터 이동 잠금 해제");
        }
    }

    private void BlockRightHandBindingsFromPlayerMove()
    {
        blockedPlayerMoveBindingIndices.Clear();

        if (!blockRightHandPlayerMove || playerMove2D == null)
            return;

        InputAction playerAction = playerMove2D.action;

        if (playerAction == null)
            return;

        // 동일 액션을 캐릭터와 Go1이 공유하면 오른손 바인딩을 끌 때
        // Go1 입력까지 함께 꺼지므로 서로 다른 액션을 사용해야 합니다.
        if (go1Move2D != null && playerAction == go1Move2D.action)
        {
            Debug.LogError(
                "[VRGo1] Player Move 2D와 Go1 Move 2D가 같은 Input Action입니다. " +
                "캐릭터용 액션과 Go1용 오른손 액션을 서로 분리해야 합니다."
            );
            return;
        }

        bool wasEnabled = playerAction.enabled;

        if (wasEnabled)
            playerAction.Disable();

        for (int i = 0; i < playerAction.bindings.Count; i++)
        {
            InputBinding binding = playerAction.bindings[i];
            string path = binding.effectivePath;

            if (string.IsNullOrEmpty(path))
                path = binding.path;

            if (!IsRightHandBinding(path, binding.groups))
                continue;

            playerAction.ApplyBindingOverride(
                i,
                new InputBinding { overridePath = string.Empty }
            );

            blockedPlayerMoveBindingIndices.Add(i);
        }

        if (wasEnabled)
            playerAction.Enable();

        if (debugLog)
        {
            Debug.Log(
                $"[VRGo1] 캐릭터 Move 액션에서 오른손 바인딩 " +
                $"{blockedPlayerMoveBindingIndices.Count}개 차단"
            );
        }
    }

    private void RestorePlayerMoveBindings()
    {
        if (playerMove2D == null || blockedPlayerMoveBindingIndices.Count == 0)
            return;

        InputAction playerAction = playerMove2D.action;

        if (playerAction == null)
            return;

        bool wasEnabled = playerAction.enabled;

        if (wasEnabled)
            playerAction.Disable();

        foreach (int bindingIndex in blockedPlayerMoveBindingIndices)
        {
            if (bindingIndex >= 0 && bindingIndex < playerAction.bindings.Count)
                playerAction.RemoveBindingOverride(bindingIndex);
        }

        blockedPlayerMoveBindingIndices.Clear();

        if (wasEnabled)
            playerAction.Enable();
    }

    private static bool IsRightHandBinding(string path, string groups)
    {
        string normalizedPath = string.IsNullOrEmpty(path)
            ? string.Empty
            : path.ToLowerInvariant();

        string normalizedGroups = string.IsNullOrEmpty(groups)
            ? string.Empty
            : groups.ToLowerInvariant();

        return normalizedPath.Contains("{righthand}") ||
               normalizedPath.Contains("/righthand/") ||
               normalizedPath.Contains("rightcontroller") ||
               normalizedGroups.Contains("righthand");
    }

    private static bool IsPressed(InputActionReference actionReference)
    {
        return actionReference != null &&
               actionReference.action != null &&
               actionReference.action.ReadValue<float>() > 0.5f;
    }

    private void MigrateLegacyTurnFlag()
    {
        if (legacyTurnFlagMigrated || !invertTurn)
        {
            legacyTurnFlagMigrated = true;
            return;
        }

        GO1CoordinateMapper mapper = null;

        if (utm != null)
            mapper = utm.coordinateMapper;

        if (mapper == null)
            mapper = FindFirstObjectByType<GO1CoordinateMapper>();

        if (mapper == null)
            return;

        mapper.commandInvertYaw = !mapper.commandInvertYaw;
        invertTurn = false;
        legacyTurnFlagMigrated = true;
    }

    private void HandleGo1CameraScreenToggle()
    {
        if (toggleGo1CameraScreenButton == null)
            return;

        if (!toggleGo1CameraScreenButton.action.WasPressedThisFrame())
            return;

        if (onlyShowScreenInGo1View && !IsGo1View())
        {
            if (debugLog)
                Debug.Log("[VRGo1] Go1Cam 시점이 아니므로 카메라 화면 토글 무시");

            return;
        }

        SetGo1CameraScreen(!go1CameraScreenVisible);
    }

    public void SetGo1CameraScreen(bool visible)
    {
        if (onlyShowScreenInGo1View && visible && !IsGo1View())
            visible = false;

        go1CameraScreenVisible = visible;

        if (go1CameraScreenRoot != null)
            go1CameraScreenRoot.SetActive(visible);

        if (visible && mjpegReceiver != null)
            mjpegReceiver.StartStream();

        if (debugLog)
            Debug.Log("[VRGo1] Go1 Camera Screen = " + visible);
    }

    private bool IsGo1View()
    {
        if (cameraViewSwitch == null)
            return true;

        return cameraViewSwitch.IsGo1View();
    }

    private void StopRobot()
    {
        if (utm != null)
            utm.SendTeleopCmd(0f, 0f, 0f, 0);
    }

    private static Vector2 ApplyDeadzone(Vector2 value, float deadzoneValue)
    {
        float magnitude = value.magnitude;

        if (magnitude < deadzoneValue)
            return Vector2.zero;

        float normalizedMagnitude = Mathf.InverseLerp(
            deadzoneValue,
            1f,
            Mathf.Clamp01(magnitude)
        );

        return value.normalized * normalizedMagnitude;
    }
}