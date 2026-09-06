using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

/// <summary>
/// GO1 관련 스크립트들의 Debug/Log 옵션을 한 곳에서 켜고 끄기 위한 중앙 로그 컨트롤러.
///
/// 사용법:
/// 1. 빈 GameObject 생성: GO1_LogControl
/// 2. 이 스크립트 부착
/// 3. autoFindTargets = true 상태로 두거나, targetScripts에 GO1Agent / Go1ObstacleJsonReceiver / GO1AutoPolicyController 등을 직접 넣기
/// 4. Preset 또는 Custom 옵션을 선택한 뒤 Apply Log Settings Now 실행
///
/// 주의:
/// - 이 스크립트는 각 컴포넌트에 이미 존재하는 bool 로그 필드를 reflection으로 찾아서 바꿉니다.
/// - 필드가 없는 경우는 자동으로 무시합니다.
/// - Debug.Log 자체를 전역 차단하는 방식이 아니라, 각 스크립트의 로그 옵션을 중앙에서 바꾸는 방식입니다.
/// </summary>
public class GO1LogControl : MonoBehaviour
{
    public enum LogPreset
    {
        Silent,      // 거의 모든 로그 끄기
        Essential,   // 경로 전송, state_change, 재탐색 핵심 로그만 켜기
        Debug,       // 디버깅에 필요한 로그 대부분 켜기
        Full,        // raw JSON 포함 최대한 많이 켜기
        Custom       // 아래 Custom Settings 직접 사용
    }

    [Header("Target Search")]
    [Tooltip("씬에 있는 MonoBehaviour를 자동으로 찾아 GO1 관련 로그 필드를 변경합니다.")]
    public bool autoFindTargets = true;

    [Tooltip("비활성 오브젝트에 붙은 스크립트도 찾습니다.")]
    public bool includeInactiveObjects = true;

    [Tooltip("자동 탐색을 쓰지 않거나 특정 대상만 제어하고 싶으면 여기에 직접 넣으세요.")]
    public List<MonoBehaviour> targetScripts = new List<MonoBehaviour>();

    [Header("Preset")]
    public LogPreset preset = LogPreset.Essential;

    [Tooltip("Start 시점에 자동 적용합니다.")]
    public bool applyOnStart = true;

    [Tooltip("OnValidate에서 자동 적용합니다. Inspector 값 바꿀 때 바로 반영하고 싶으면 켜세요.")]
    public bool applyOnValidate = false;

    [Tooltip("Play 중 일정 간격으로 계속 적용합니다. 다른 스크립트가 값을 다시 바꾸는 경우에만 사용하세요.")]
    public bool keepApplyingInPlayMode = false;

    public float applyInterval = 1.0f;

    [Header("Hotkeys")]
    public bool enableHotkeys = true;
    public KeyCode applyKey = KeyCode.F9;
    public KeyCode cyclePresetKey = KeyCode.F10;

    [Header("Custom Settings - Receiver")]
    [Tooltip("수신한 원본 JSON 전체 출력. 로그가 매우 많아질 수 있음.")]
    public bool showRawJson = false;

    [Tooltip("장애물 생성/갱신 상세 로그")]
    public bool showObstacleDetail = false;

    [Tooltip("5009 motion state JSON 로그. state_change 확인용")]
    public bool showMotionState = true;

    [Tooltip("가상 경로 탐색 중 JSON 무시 로그")]
    public bool showVirtualPlanningIgnore = false;

    [Tooltip("카메라 회전 중 JSON 무시 로그")]
    public bool showRotationIgnore = false;

    [Tooltip("재탐색 직후 JSON 잠금 로그")]
    public bool showPostReplanLock = true;

    [Tooltip("소화기 landmark 보정 로그")]
    public bool showFireCorrection = false;

    [Header("Custom Settings - GO1Agent")]
    [Tooltip("state_change=true 대기/timeout/재전송 로그")]
    public bool showRealGo1StartWait = true;

    [Tooltip("런타임 장애물 재탐색 로그")]
    public bool showRuntimeReplan = true;

    [Tooltip("재탐색 전 pose/yaw 동기화 로그")]
    public bool showPoseSync = true;

    [Tooltip("M키 시작 직전 pose/yaw 동기화 로그")]
    public bool showManualStartPoseSync = true;

    [Tooltip("재탐색 경로 재생성/검증 로그")]
    public bool showRuntimeReplanRetry = false;

    [Tooltip("소화기 보정 재탐색 로그")]
    public bool showFireCorrectionReplan = false;

    [Header("Custom Settings - Auto Policy")]
    [Tooltip("GO1AutoPolicyController 로그")]
    public bool showAutoPolicyLog = false;

    [Tooltip("GO1AutoPolicyController 디버그 라인")]
    public bool showAutoPolicyDebugLine = false;

    [Header("Custom Settings - Common")]
    [Tooltip("drawDebugRay, drawDebugLine 등 시각 디버그 라인")]
    public bool showDebugLines = true;

    [Tooltip("적용 결과 요약 로그")]
    public bool printApplySummary = true;

    private float lastApplyTime = -999f;

    private void Start()
    {
        if (applyOnStart)
            ApplyLogSettings();
    }

    private void Update()
    {
        if (enableHotkeys)
        {
            if (Input.GetKeyDown(applyKey))
            {
                ApplyLogSettings();
            }

            if (Input.GetKeyDown(cyclePresetKey))
            {
                CyclePreset();
                ApplyLogSettings();
            }
        }

        if (keepApplyingInPlayMode && Time.time - lastApplyTime >= Mathf.Max(0.1f, applyInterval))
        {
            ApplyLogSettings();
        }
    }

    private void OnValidate()
    {
        ApplyPresetToCustomFields();

        if (applyOnValidate && Application.isPlaying)
            ApplyLogSettings();
    }

    [ContextMenu("Apply Log Settings Now")]
    public void ApplyLogSettings()
    {
        ApplyPresetToCustomFields();

        List<MonoBehaviour> targets = CollectTargets();
        int appliedCount = 0;
        int changedFieldCount = 0;

        foreach (MonoBehaviour target in targets)
        {
            if (target == null)
                continue;

            int changedForTarget = ApplyToTarget(target);
            if (changedForTarget > 0)
            {
                appliedCount++;
                changedFieldCount += changedForTarget;
            }
        }

        lastApplyTime = Time.time;

        if (printApplySummary)
        {
            Debug.Log(
                "[GO1LogControl] 로그 설정 적용 완료 | " +
                "preset=" + preset +
                ", targets=" + appliedCount +
                ", fields=" + changedFieldCount +
                ", rawJson=" + showRawJson +
                ", obstacleDetail=" + showObstacleDetail +
                ", motionState=" + showMotionState +
                ", stateWait=" + showRealGo1StartWait +
                ", runtimeReplan=" + showRuntimeReplan
            );
        }
    }

    [ContextMenu("Set Preset Silent")]
    public void SetSilentPreset()
    {
        preset = LogPreset.Silent;
        ApplyLogSettings();
    }

    [ContextMenu("Set Preset Essential")]
    public void SetEssentialPreset()
    {
        preset = LogPreset.Essential;
        ApplyLogSettings();
    }

    [ContextMenu("Set Preset Debug")]
    public void SetDebugPreset()
    {
        preset = LogPreset.Debug;
        ApplyLogSettings();
    }

    [ContextMenu("Set Preset Full")]
    public void SetFullPreset()
    {
        preset = LogPreset.Full;
        ApplyLogSettings();
    }

    public void CyclePreset()
    {
        if (preset == LogPreset.Silent)
            preset = LogPreset.Essential;
        else if (preset == LogPreset.Essential)
            preset = LogPreset.Debug;
        else if (preset == LogPreset.Debug)
            preset = LogPreset.Full;
        else if (preset == LogPreset.Full)
            preset = LogPreset.Silent;
        else
            preset = LogPreset.Essential;
    }

    private void ApplyPresetToCustomFields()
    {
        if (preset == LogPreset.Custom)
            return;

        if (preset == LogPreset.Silent)
        {
            showRawJson = false;
            showObstacleDetail = false;
            showMotionState = false;
            showVirtualPlanningIgnore = false;
            showRotationIgnore = false;
            showPostReplanLock = false;
            showFireCorrection = false;

            showRealGo1StartWait = false;
            showRuntimeReplan = false;
            showPoseSync = false;
            showManualStartPoseSync = false;
            showRuntimeReplanRetry = false;
            showFireCorrectionReplan = false;

            showAutoPolicyLog = false;
            showAutoPolicyDebugLine = false;
            showDebugLines = false;
            return;
        }

        if (preset == LogPreset.Essential)
        {
            showRawJson = false;
            showObstacleDetail = false;
            showMotionState = true;
            showVirtualPlanningIgnore = false;
            showRotationIgnore = false;
            showPostReplanLock = true;
            showFireCorrection = false;

            showRealGo1StartWait = true;
            showRuntimeReplan = true;
            showPoseSync = true;
            showManualStartPoseSync = true;
            showRuntimeReplanRetry = false;
            showFireCorrectionReplan = false;

            showAutoPolicyLog = false;
            showAutoPolicyDebugLine = false;
            showDebugLines = true;
            return;
        }

        if (preset == LogPreset.Debug)
        {
            showRawJson = false;
            showObstacleDetail = true;
            showMotionState = true;
            showVirtualPlanningIgnore = true;
            showRotationIgnore = true;
            showPostReplanLock = true;
            showFireCorrection = true;

            showRealGo1StartWait = true;
            showRuntimeReplan = true;
            showPoseSync = true;
            showManualStartPoseSync = true;
            showRuntimeReplanRetry = true;
            showFireCorrectionReplan = true;

            showAutoPolicyLog = true;
            showAutoPolicyDebugLine = true;
            showDebugLines = true;
            return;
        }

        if (preset == LogPreset.Full)
        {
            showRawJson = true;
            showObstacleDetail = true;
            showMotionState = true;
            showVirtualPlanningIgnore = true;
            showRotationIgnore = true;
            showPostReplanLock = true;
            showFireCorrection = true;

            showRealGo1StartWait = true;
            showRuntimeReplan = true;
            showPoseSync = true;
            showManualStartPoseSync = true;
            showRuntimeReplanRetry = true;
            showFireCorrectionReplan = true;

            showAutoPolicyLog = true;
            showAutoPolicyDebugLine = true;
            showDebugLines = true;
        }
    }

    private List<MonoBehaviour> CollectTargets()
    {
        HashSet<MonoBehaviour> set = new HashSet<MonoBehaviour>();

        if (targetScripts != null)
        {
            foreach (MonoBehaviour script in targetScripts)
            {
                if (script != null)
                    set.Add(script);
            }
        }

        if (autoFindTargets)
        {
            MonoBehaviour[] all = FindObjectsByType<MonoBehaviour>(
                includeInactiveObjects ? FindObjectsInactive.Include : FindObjectsInactive.Exclude,
                FindObjectsSortMode.None
            );

            foreach (MonoBehaviour script in all)
            {
                if (script == null)
                    continue;

                string typeName = script.GetType().Name;

                if (LooksLikeGo1RelatedScript(typeName))
                    set.Add(script);
            }
        }

        return new List<MonoBehaviour>(set);
    }

    private bool LooksLikeGo1RelatedScript(string typeName)
    {
        if (string.IsNullOrEmpty(typeName))
            return false;

        return typeName.Contains("GO1") ||
               typeName.Contains("Go1") ||
               typeName.Contains("UnityTeleopAndMirror") ||
               typeName.Contains("TrainingManager");
    }

    private int ApplyToTarget(MonoBehaviour target)
    {
        int changed = 0;
        Type type = target.GetType();

        // Go1ObstacleJsonReceiver 계열
        changed += SetBoolIfExists(type, target, showRawJson,
            "printReceivedJson");

        changed += SetBoolIfExists(type, target, showObstacleDetail,
            "printObstacleInfo");

        changed += SetBoolIfExists(type, target, showMotionState,
            "printGo1MotionStateLog",
            "debugGo1MotionState",
            "printMotionStateLog");

        changed += SetBoolIfExists(type, target, showVirtualPlanningIgnore,
            "printVirtualPlanningIgnoreLog");

        changed += SetBoolIfExists(type, target, showRotationIgnore,
            "printRotationIgnoreLog");

        changed += SetBoolIfExists(type, target, showPostReplanLock,
            "printPostReplanLockLog");

        changed += SetBoolIfExists(type, target, showFireCorrection,
            "debugFireExtinguisherCorrection",
            "debugFireLandmarkGlobalMapSync");

        changed += SetBoolIfExists(type, target, showDebugLines,
            "drawDebugRay");

        // GO1Agent 계열
        changed += SetBoolIfExists(type, target, showRealGo1StartWait,
            "debugRealGo1StartWait",
            "debugStateChangeWait",
            "debugRealPathStateGate");

        changed += SetBoolIfExists(type, target, showRuntimeReplan,
            "debugRuntimeReplan");

        changed += SetBoolIfExists(type, target, showPoseSync,
            "debugReplanPoseSync");

        changed += SetBoolIfExists(type, target, showManualStartPoseSync,
            "debugManualStartPoseSync");

        changed += SetBoolIfExists(type, target, showRuntimeReplanRetry,
            "debugRuntimeReplanRetry");

        changed += SetBoolIfExists(type, target, showFireCorrectionReplan,
            "debugFireCorrectionReplan");

        // GO1AutoPolicyController 계열
        changed += SetBoolIfExists(type, target, showAutoPolicyLog,
            "debugLog",
            "debugAutoPolicyLog");

        changed += SetBoolIfExists(type, target, showAutoPolicyDebugLine,
            "drawDebugLine",
            "drawDebugLines");

        // PathSender / UTM / Navigator 등에서 흔히 쓰는 이름 후보
        changed += SetBoolIfExists(type, target, showRuntimeReplan,
            "debugLog",
            "printDebugLog",
            "enableDebugLog");

        changed += SetBoolIfExists(type, target, showDebugLines,
            "drawDebugLine",
            "drawDebugLines",
            "drawPathDebugLine");

        return changed;
    }

    private int SetBoolIfExists(Type type, object target, bool value, params string[] fieldNames)
    {
        int changed = 0;

        foreach (string fieldName in fieldNames)
        {
            FieldInfo field = type.GetField(
                fieldName,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
            );

            if (field == null)
                continue;

            if (field.FieldType != typeof(bool))
                continue;

            bool oldValue = (bool)field.GetValue(target);
            if (oldValue != value)
            {
                field.SetValue(target, value);
                changed++;
            }
        }

        return changed;
    }
}
