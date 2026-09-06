using UnityEngine;
using TMPro;
using System.Collections;
using UnityEngine.SceneManagement;

/*
===============================================================================
UIManager.cs
-------------------------------------------------------------------------------
타이틀/메인 메뉴 UI 전체를 제어하는 중앙 UI 매니저
- 패널(설정/로봇선택/맵선택) 열기/닫기 + 오버레이(딤) 관리
- 설정 패널 내부 페이지 전환(Sound/UI/Program/Copyright/Translation)
- 로봇/맵/UI모드 선택 상태 저장 + 선택 결과 토스트 표시
- 선택된 맵에 따라 씬 로드(StartGame)
- LocalizationManager와 연동하여 토스트/문구를 언어별로 표시

-------------------------------------------------------------------------------
[구성 요약]

1) Overlay / Panels
- dimOverlay : 공통 딤(어두운 배경) 오버레이(선택)
- settingsPanel / robotSelectionPanel / mapPanel : 주요 UI 패널
- settingsDimOverlay / robotDimOverlay / mapDimOverlay : 패널별 딤 오버레이(선택)
  ※ 공통 dimOverlay만 쓰거나, 패널별 overlay를 따로 써도 됨

2) Settings Pages (설정 패널 내부 컨텐츠)
- buttonSettingsGroup : 설정 메뉴 버튼 그룹(메인 메뉴)
- pageSound / pageUI / pageProgram / pageCopyright / pageTranslation : 각 페이지
- descriptionPanel : 프로그램 설명 패널(Program 페이지에서 사용)
- descriptionMain1~4 : Program 설명의 여러 페이지/섹션(원하는 방식으로 분할 표시)

3) 선택 상태(런타임)
- selectedRobot : 선택된 로봇 (EP01 / Go1 / Add)
- selectedMap   : 선택된 맵 (Corridor / Plain / Add)
- selectedUIMode : UI 모드 (Default / Senior)

4) 토스트(Toast)
- toastRoot / toastText / toastBG
- Fade In → Hold → Fade Out 코루틴으로 메시지 표시

5) 씬 로드
- StartGame(): selectedMap에 따라 씬 이름을 결정 후 SceneManager.LoadScene 호출
- GetSceneNameBySelectedMap(): 맵 타입 → 씬 이름 매핑

-------------------------------------------------------------------------------
[동작 흐름]

Start()
- 시작 시 모든 패널 닫기(설정/로봇선택/맵)
- 설정 내부 페이지는 모두 숨기고(buttonSettingsGroup만 보이게)
- 토스트 초기 숨김/알파 0
- (옵션) titleRoot / mainMenuRoot 활성화

패널 열기(OpenSettings / OpenRobotSelection / OpenMap)
- CloseOtherPanelsExcept()로 다른 패널/딤을 정리
- 해당 패널 ON + overlay ON
- Settings는 기본적으로 ShowSettingsMain()로 메뉴 그룹 표시

패널 닫기(CloseSettings / CloseRobotSelection / CloseMap)
- 패널 OFF + overlay OFF

GoToMain()
- 모든 패널/페이지 정리 후 메인 화면(타이틀/메뉴)로 복귀하는 “정리 함수”
- 로봇/맵/UI 선택 후 호출되어 UI가 깔끔히 돌아오게 함

-------------------------------------------------------------------------------
[선택 API]

로봇 선택:
- ConfirmRobotSelection(robot)
  1) selectedRobot 저장
  2) GoToMain()으로 복귀
  3) LocalizationManager의 "TOAST_ROBOT_SELECTED" 템플릿에 로봇 이름 삽입하여 토스트 출력

맵 선택:
- ConfirmMapSelection(type)
  1) selectedMap 저장
  2) GoToMain()
  3) "TOAST_MAP_SELECTED" 템플릿에 맵 이름 삽입하여 토스트 출력

UI 모드 선택:
- ConfirmUISelection(mode)
  1) selectedUIMode 저장
  2) GoToMain()
  3) "TOAST_UI_DEFAULT" 또는 "TOAST_UI_SENIOR" 토스트 출력

-------------------------------------------------------------------------------
[Localization 연동 포인트]

- 토스트 메시지는 LocalizationManager.Instance.Get(key)로 가져옴
  - "TOAST_ROBOT_SELECTED" : "{0} IS SELECTED" / "{0}이(가) 선택되었습니다"
  - "TOAST_MAP_SELECTED"   : "{0} MAP IS SELECTED" / "{0} 맵이 선택되었습니다"
  - UI 모드 토스트 키도 언어에 따라 자동 변경

※ 주의:
  LocalizationManager.Instance가 씬에 없거나 초기화 전이면 NullReference 가능.
  (현재 코드는 Instance가 있다고 가정하고 사용)

-------------------------------------------------------------------------------
[토스트(Toast) 동작]

ShowToast(message)
- 이전 코루틴이 있으면 중지 후 새 코루틴 시작
- CoToast:
  - toastRoot 활성화
  - 알파 0 → Fade In(1초) → Hold(2초) → Fade Out(2초)
  - 마지막에 toastRoot 비활성화
- WaitForSecondsRealtime / unscaledDeltaTime 사용
  → Time.timeScale=0 상태(일시정지)에서도 토스트가 정상 재생됨

-------------------------------------------------------------------------------
[주의사항 / 팁]

- Overlay를 공통(dimOverlay) + 패널별(settingsDimOverlay 등)로 동시에 쓰면
  겹쳐서 너무 어두워질 수 있음 → 하나만 써도 충분한 경우가 많음
- panel 오브젝트와 page 오브젝트가 Inspector에 제대로 연결되지 않으면
  SetActive가 동작하지 않아 UI가 안 보이는 문제가 발생함
- 씬 이름(GetSceneNameBySelectedMap)은 Build Settings에 등록되어 있어야 LoadScene 가능
- “Add” 타입(MapType.Add / RobotType.Add)은 현재 미구현이면 null 처리 및 토스트로 안내

-------------------------------------------------------------------------------
[확장 아이디어]

- 선택 상태를 PlayerPrefs로 저장(재실행 시 마지막 선택 유지)
- UI 모드(Default/Senior)에 따라 실제 UI 프리팹/폰트 크기/레이아웃 전환
- 패널 열 때 사운드(UI 클릭음) 연동(SoundManager)
- 토스트를 큐잉(연속 호출 시 순서대로 표시)하는 기능

===============================================================================
*/

public class UIManager : MonoBehaviour
{
    /* =======================
     * Overlay / Panels
     * ======================= */

    [Header("Common Overlay (shared)")]
    public GameObject dimOverlay; 

    [Header("Panels")]
    public GameObject settingsPanel;
    public GameObject robotSelectionPanel;
    public GameObject mapPanel;

    [Header("Optional Overlays (if you want separate overlays)")]
    public GameObject settingsDimOverlay;
    public GameObject robotDimOverlay;
    public GameObject mapDimOverlay;

    /* =======================
     * Settings Pages
     * ======================= */

    [Header("Main Group (Settings menu buttons)")]
    public GameObject buttonSettingsGroup;

    [Header("Pages (ContentArea)")]
    public GameObject pageSound;
    public GameObject pageUI;
    public GameObject pageProgram;
    public GameObject pageCopyright;
    public GameObject pageTranslation;

    [Header("Program Panel")]
    public GameObject descriptionPanel;

    /* =======================
     * Robot Selection State
     * ======================= */

    public enum RobotType { EP01, Go1, Add }
    public enum MapType { Corridor, Plain, Add }
    public enum UIMode { Default, Senior }

    [Header("Selected UI Mode (runtime)")]
    public UIMode selectedUIMode = UIMode.Default;

    [Header("Selected Robot (runtime)")]
    public RobotType selectedRobot = RobotType.EP01; 

    [Header("Selected Map (runtime)")]
    public MapType selectedMap = MapType.Corridor;

    /* =======================
     * Optional: Title / Main Roots
     * (없으면 비워도 됨)
     * ======================= */

    [Header("Main/Title Roots (optional)")]
    public GameObject titleRoot;     // 타이틀 화면 루트(있으면)
    public GameObject mainMenuRoot;  // 메인 메뉴 루트(있으면)

    /* =======================
     * Toast UI (BG + Text Only)
     * ======================= */

    [Header("Toast UI (BG + Text)")]
    public GameObject toastRoot;     // ToastRoot (SetActive false 추천)
    public TMP_Text toastText;       // RobotSelectText (TMP)
    public GameObject toastBG;       // ToastBG (Image 오브젝트)

    [Header("Toast Timing")]
    public float fadeInTime = 1f;    // 1초
    public float holdTime = 2f;      // 2초
    public float fadeOutTime = 2f;   // 2초

    [Header("Program Description Mains")]
    public GameObject descriptionMain1;
    public GameObject descriptionMain2;
    public GameObject descriptionMain3;
    public GameObject descriptionMain4;


    Coroutine toastCo;

    /* =======================
     * Unity
     * ======================= */

    void Start()
    {
        // 시작 시 패널 닫기
        CloseSettings();
        CloseRobotSelection();
        CloseMap();

        // Settings 내부 페이지 끄기(메뉴버튼만 보이게)
        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(true);

        // 토스트 초기 숨김
        InitToastHidden();

        // (선택) 시작 화면 상태
        if (titleRoot) titleRoot.SetActive(true);
        if (mainMenuRoot) mainMenuRoot.SetActive(true);
    }



    public void StartGame()
    {
        // 혹시 멈춰있을 수 있으니(옵션)
        Time.timeScale = 1f;

        string sceneName = GetSceneNameBySelectedMap();

        if (string.IsNullOrEmpty(sceneName))
        {
            ShowToast("MAP IS NOT READY");
            return;
        }

        Debug.Log($"[UI] StartGame -> LoadScene: {sceneName}");
        SceneManager.LoadScene(sceneName);
    }

    string GetSceneNameBySelectedMap()
    {
        switch (selectedMap)
        {
            case MapType.Corridor: return "N4_5F_Corridor";
            case MapType.Plain:    return "Map_Editor_Plain";
            case MapType.Add:      return null; // 아직 미구현이면 null 처리
            default:               return null;
        }
    }

    void InitToastHidden()
    {
        if (toastRoot) toastRoot.SetActive(false);

        // 알파 0으로 초기화 (BG + Text)
        SetToastAlpha(0f);
    }

    /* =======================
     * Helpers
     * ======================= */

    void HideAllPages()
    {
        if (pageSound) pageSound.SetActive(false);
        if (pageUI) pageUI.SetActive(false);
        if (pageProgram) pageProgram.SetActive(false);
        if (pageCopyright) pageCopyright.SetActive(false);
        if (pageTranslation) pageTranslation.SetActive(false);
    }

    void EnableOverlay(GameObject specificOverlay)
    {
        if (dimOverlay) dimOverlay.SetActive(true);
        if (specificOverlay) specificOverlay.SetActive(true);
    }

    void DisableOverlay(GameObject specificOverlay)
    {
        if (dimOverlay) dimOverlay.SetActive(false);
        if (specificOverlay) specificOverlay.SetActive(false);
    }

    public void ShowTranslation()
    {
        if (settingsPanel && !settingsPanel.activeSelf) OpenSettings();

        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(false);
        if (pageTranslation) pageTranslation.SetActive(true);
    }


    void HideAllProgramMains()
    {
        if (descriptionMain1) descriptionMain1.SetActive(false);
        if (descriptionMain2) descriptionMain2.SetActive(false);
        if (descriptionMain3) descriptionMain3.SetActive(false);
        if (descriptionMain4) descriptionMain4.SetActive(false);
    }

    void ShowProgramMain(int index)
    {
        HideAllProgramMains();

        switch (index)
        {
            case 1: if (descriptionMain1) descriptionMain1.SetActive(true); break;
            case 2: if (descriptionMain2) descriptionMain2.SetActive(true); break;
            case 3: if (descriptionMain3) descriptionMain3.SetActive(true); break;
            case 4: if (descriptionMain4) descriptionMain4.SetActive(true); break;
            default: if (descriptionMain1) descriptionMain1.SetActive(true); break;
        }
    }


    void CloseOtherPanelsExcept(GameObject keepPanel)
    {
        if (settingsPanel && settingsPanel != keepPanel) settingsPanel.SetActive(false);
        if (robotSelectionPanel && robotSelectionPanel != keepPanel) robotSelectionPanel.SetActive(false);
        if (mapPanel && mapPanel != keepPanel) mapPanel.SetActive(false);

        if (settingsDimOverlay) settingsDimOverlay.SetActive(false);
        if (robotDimOverlay) robotDimOverlay.SetActive(false);
        if (mapDimOverlay) mapDimOverlay.SetActive(false);

        if (dimOverlay) dimOverlay.SetActive(false);
    }

    // 네 구조: 특정 패널들 다 끄면 메인으로 보이는 구조면,
    // GoToMain은 "정리만" 하면 됨.
    public void GoToMain()
    {
        CloseSettings();
        CloseRobotSelection();
        CloseMap();

        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(true);

        if (titleRoot) titleRoot.SetActive(true);
        if (mainMenuRoot) mainMenuRoot.SetActive(true);
    }

    /* =======================
     * Settings Panel
     * ======================= */

    public void OpenSettings()
    {
        CloseOtherPanelsExcept(settingsPanel);

        if (settingsPanel) settingsPanel.SetActive(true);
        EnableOverlay(settingsDimOverlay);

        ShowSettingsMain();
    }

    public void CloseSettings()
    {
        if (settingsPanel) settingsPanel.SetActive(false);
        DisableOverlay(settingsDimOverlay);
    }

    public void ShowSettingsMain()
    {
        if (settingsPanel && !settingsPanel.activeSelf) OpenSettings();

        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(true);
    }

    public void ShowSound()
    {
        if (settingsPanel && !settingsPanel.activeSelf) OpenSettings();

        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(false);
        if (pageSound) pageSound.SetActive(true);
    }

    public void ShowUI()
    {
        if (settingsPanel && !settingsPanel.activeSelf) OpenSettings();

        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(false);
        if (pageUI) pageUI.SetActive(true);
    }

    public void ShowProgram()
    {
        if (settingsPanel && !settingsPanel.activeSelf)
            OpenSettings();

        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(false);

        if (pageProgram) pageProgram.SetActive(true);

        if (descriptionPanel) descriptionPanel.SetActive(true);

        ShowProgramMain(1);
    }


    public void ShowCopyright()
    {
        if (settingsPanel && !settingsPanel.activeSelf) OpenSettings();

        HideAllPages();
        if (buttonSettingsGroup) buttonSettingsGroup.SetActive(false);
        if (pageCopyright) pageCopyright.SetActive(true);
    }

    /* =======================
     * Robot Selection Panel
     * ======================= */

    public void OpenRobotSelection()
    {
        CloseOtherPanelsExcept(robotSelectionPanel);

        if (robotSelectionPanel) robotSelectionPanel.SetActive(true);
        EnableOverlay(robotDimOverlay);
    }

    public void CloseRobotSelection()
    {
        if (robotSelectionPanel) robotSelectionPanel.SetActive(false);
        DisableOverlay(robotDimOverlay);
    }

    /* =======================
     * Map Panel
     * ======================= */

    public void OpenMap()
    {
        CloseOtherPanelsExcept(mapPanel);

        if (mapPanel) mapPanel.SetActive(true);
        EnableOverlay(mapDimOverlay);
    }

    public void CloseMap()
    {
        if (mapPanel) mapPanel.SetActive(false);
        DisableOverlay(mapDimOverlay);
    }

    /* =======================
     * Robot Selection API
     * ======================= */

    public void SetSelectedRobot(RobotType robot)
    {
        selectedRobot = robot;
    }

    public string GetSelectedRobotDisplayName()
    {
        switch (selectedRobot)
        {
            case RobotType.EP01: return "RoboMaster EP01";
            case RobotType.Go1:  return "Unitree Go1";
            case RobotType.Add:  return "Add Robot";
            default: return "Unknown";
        }
    }

    public void SelectRobotEP01() => ConfirmRobotSelection(RobotType.EP01);
    public void SelectRobotGo1()  => ConfirmRobotSelection(RobotType.Go1);
    public void SelectRobotAdd()  => ConfirmRobotSelection(RobotType.Add);

    public void ConfirmRobotSelection(RobotType robot)
    {
        selectedRobot = robot;
        GoToMain();

        string robotName = GetSelectedRobotDisplayName();
        string template = LocalizationManager.Instance.Get("TOAST_ROBOT_SELECTED");
        ShowToast(string.Format(template, robotName));
    }

    /* =======================
     * Toast (BG+Text Fade)
     * ======================= */

    public void ShowToast(string message)
    {
        if (!toastRoot || !toastText || !toastBG) return;

        if (toastCo != null) StopCoroutine(toastCo);
        toastCo = StartCoroutine(CoToast(message));
    }

    IEnumerator CoToast(string message)
    {
        toastRoot.SetActive(true);

        toastText.text = message;

        // 시작 알파 0
        SetToastAlpha(0f);

        // Fade In
        yield return FadeToast(0f, 1f, fadeInTime);

        // Hold
        yield return new WaitForSecondsRealtime(holdTime);

        // Fade Out
        yield return FadeToast(1f, 0f, fadeOutTime);

        toastRoot.SetActive(false);
    }

    IEnumerator FadeToast(float from, float to, float time)
    {
        float t = 0f;
        float safe = Mathf.Max(0.0001f, time);

        while (t < time)
        {
            t += Time.unscaledDeltaTime;
            float a = Mathf.Lerp(from, to, t / safe);
            SetToastAlpha(a);
            yield return null;
        }

        SetToastAlpha(to);
    }

    void SetToastAlpha(float a)
    {
        // Text alpha
        if (toastText)
        {
            Color tc = toastText.color;
            tc.a = a;
            toastText.color = tc;
        }

        // BG alpha (조금 더 진하게 보이게 0.85 배)
        var img = toastBG ? toastBG.GetComponent<UnityEngine.UI.Image>() : null;
        if (img)
        {
            Color bc = img.color;
            bc.a = a * 0.85f;
            img.color = bc;
        }
    }

    public string GetSelectedMapDisplayName()
    {
        switch (selectedMap)
        {
            case MapType.Corridor: return "CORRIDOR";
            case MapType.Plain:    return "PLAIN";
            case MapType.Add:      return "ADD MAP";
            default:               return "UNKNOWN";
        }
    }

    /* =======================
     * Map Selection API
     * ======================= */

    public void ConfirmMapSelection(MapType type)
    {
        selectedMap = type;
        Debug.Log($"[UI] Map Selected: {selectedMap}");

        GoToMain();

        string mapName = GetSelectedMapDisplayName();
        string template = LocalizationManager.Instance.Get("TOAST_MAP_SELECTED");
        ShowToast(string.Format(template, mapName));
    }

    public void SelectDefaultUI() => ConfirmUISelection(UIMode.Default);
    public void SelectSeniorUI()  => ConfirmUISelection(UIMode.Senior);

    public void ConfirmUISelection(UIMode mode)
    {
        selectedUIMode = mode;

        // 필요하면 UI 선택 페이지 닫고 메인으로 복귀
        GoToMain();

        // 토스트 문구: 언어에 따라 바뀜
        string key = (mode == UIMode.Default) ? "TOAST_UI_DEFAULT" : "TOAST_UI_SENIOR";
        string msg = LocalizationManager.Instance.Get(key);
        ShowToast(msg);

        Debug.Log($"[UI] UI Mode Selected: {selectedUIMode}");
    }
}
