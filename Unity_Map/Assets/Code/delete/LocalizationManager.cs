using UnityEngine;
using System.Collections.Generic;
using UnityEngine.SceneManagement;
using TMPro;


/*
===============================================================================
LocalizationManager.cs
-------------------------------------------------------------------------------
간단한 다국어(Localization) 시스템의 중심 관리자(Singleton)

[개요]
이 스크립트는 EN/KR 번역 테이블(Dictionary)을 보유하고,
현재 언어(Language)를 전환하면 씬 안의 모든 LocalizedText / LocalizedImage를
갱신(Refresh)하여 UI 텍스트/이미지가 즉시 바뀌도록 한다.

또한 언어에 맞는 TMP 폰트(fontEN/fontKR)를 적용하여
한글/영문 글리프 깨짐을 방지한다.

-------------------------------------------------------------------------------
[구성 요소]

- Language enum: EN, KR
- 번역 테이블:
    Dictionary<string,string> en / kr
- 폰트:
    TMP_FontAsset fontEN, fontKR
- 싱글톤:
    LocalizationManager.Instance (DontDestroyOnLoad 유지)

-------------------------------------------------------------------------------
[동작 흐름]

Awake()
  1) Instance 중복 방지(중복이면 Destroy)
  2) DontDestroyOnLoad로 씬 전환 시 유지
  3) Init()으로 EN/KR 테이블 초기화
  4) SetLanguage(Language.EN)로 기본 언어 적용

SetLanguage(lang)
  1) currentLanguage 갱신
  2) ApplyFontForCurrentLanguage() : 현재 씬의 LocalizedText에 폰트 적용
  3) RefreshAll() : 현재 씬의 LocalizedText / LocalizedImage 전체 Refresh()

Get(key)
  - 현재 언어 테이블에서 key를 조회하여 번역 문자열 반환
  - 키가 없으면 key 그대로 반환(디버깅/누락 감지용)

-------------------------------------------------------------------------------
[씬 갱신 범위]

- RefreshAll() / ApplyFontForCurrentLanguage()는
  "현재 Active Scene"의 Root GameObject들을 대상으로만 동작한다.
  (즉, DontDestroyOnLoad 영역 오브젝트는 필요 시 별도 처리 필요)

-------------------------------------------------------------------------------
[PlayerPrefs 저장/로드 관련]

- LoadSavedLanguage()는 "LANG" 키를 읽어 currentLanguage에 반영하는 함수지만,
  현재 코드에서는 Awake()에서 호출되지 않는다.
- 또한 SetLanguage() 호출 시 PlayerPrefs에 저장하는 로직이 없다.
  → 저장/로드를 쓰려면 아래 중 하나가 필요:
    1) Awake에서 LoadSavedLanguage() 후 SetLanguage(currentLanguage)
    2) SetLanguage() 안에서 PlayerPrefs.SetInt("LANG",(int)lang) + Save()

-------------------------------------------------------------------------------
[키 설계 주의]

- 현재 AutoLocalizeInstaller는 TMP_Text의 '기존 텍스트'를 key로 쓸 수 있음.
  이 경우:
    - key 중복 가능(동일 문구 여러 곳)
    - 공백/개행/대소문자 차이에 민감
  → 운영 단계에서는 명시적인 key 규칙(예: UI_BTN_START 등) 권장

-------------------------------------------------------------------------------
[확장 포인트]

- 언어 추가(JP/CN 등): enum + Dictionary 추가 + 폰트 추가
- 외부 데이터(CSV/JSON)로 테이블 로드
- 폰트/스타일(크기, line spacing)까지 언어별 적용
- 씬 로드 이벤트(SceneManager.sceneLoaded)에서 자동 Refresh

===============================================================================
*/

public enum Language
{
    EN,
    KR
}

public class LocalizationManager : MonoBehaviour
{
    public static LocalizationManager Instance { get; private set; }

    Dictionary<string, string> en = new Dictionary<string, string>();
    Dictionary<string, string> kr = new Dictionary<string, string>();

    public TMP_FontAsset fontEN;   
    public TMP_FontAsset fontKR;  

    public Language currentLanguage = Language.EN;

    void Awake()
    {
        if (Instance != null)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
        DontDestroyOnLoad(gameObject);

        Init();

        SetLanguage(Language.EN);
    }

    void Init()
    {
        // =====================
        // EN (기본: 원문 그대로)
        // =====================
        en["start"] = "START";
        en["MAP SELECTION"] = "MAP SELECTION";
        en["ROBOT SELECTION"] = "ROBOT SELECTION";
        en["EXIT"] = "EXIT";
        en["ROBOT-HUMAN INTERACTION"] = "ROBOT-HUMAN INTERACTION";
        en["TRANSLATION"] = "TRANSLATION";

        // 소리
        en["MASTER"] = "MASTER";
        en["BGM"] = "BGM";
        en["UI"] = "UI";
        en["ETC"] = "ETC";

        // UI 선택
        en["UI SELECT"] = "UI SELECT";
        en["SENIOR UI"] = "SENIOR UI";
        en["DEFAULT UI"] = "DEFAULT UI";

        // 조작법/프로그램 설명
        en["PROGRAM DESCRIPTION"] = "PROGRAM DESCRIPTION";
        en["조작 방법등의 대한 설명1"] = "조작 방법등의 대한 설명1";
        en["조작 방법등의 대한 설명2"] = "조작 방법등의 대한 설명2";
        en["조작 방법등의 대한 설명3"] = "조작 방법등의 대한 설명3";
        en["조작 방법등의 대한 설명4"] = "조작 방법등의 대한 설명4";

        // 설정 메뉴 항목(중복 키는 한 번만 있으면 됨)
        en["SOUND OPTIONS"] = "SOUND OPTIONS";
        en["COPYRIGHT INFORMATION"] = "COPYRIGHT INFORMATION";
        en["UI SELECTION"] = "UI SELECTION";

        // 로봇 선택
        en["ROBOT SELECTION"] = "ROBOT SELECTION";
        en["Choose Robot you can use"] = "Choose Robot you can use";
        en["ROBOMASTER EP01"] = "ROBOMASTER EP01";
        en["Unitree Go1"] = "Unitree Go1";
        en["ADD ROBOT"] = "ADD ROBOT";

        // 맵 선택
        en["MAP SELECTION"] = "MAP SELECTION";
        en["Choose Map you can use"] = "Choose Map you can use";
        en["MAP EDITER"] = "MAP EDITER";
        en["CORRIDER"] = "CORRIDER";
        en["ADD MAP"] = "ADD MAP";

        // 토스트 메시지
        en["TOAST_ROBOT_SELECTED"] = "{0} IS SELECTED";
        en["TOAST_MAP_SELECTED"]   = "{0} MAP IS SELECTED";
        en["TOAST_UI_DEFAULT"] = "DEFAULT UI HAS BEEN APPLIED";
        en["TOAST_UI_SENIOR"]  = "SENIOR UI HAS BEEN APPLIED";


        // =====================
        // KR (여기서 한글로 바뀜)
        // =====================
        kr["start"] = "시작";
        kr["MAP SELECTION"] = "맵 선택";
        kr["ROBOT SELECTION"] = "로봇 선택";
        kr["EXIT"] = "종료";
        kr["ROBOT-HUMAN INTERACTION"] = "로봇-인간 상호작용";
        kr["TRANSLATION"] = "언어 선택";

        // 소리
        kr["MASTER"] = "마스터 볼륨";
        kr["BGM"] = "배경음";
        kr["UI"] = "UI 사운드";
        kr["ETC"] = "기타";

        // UI 선택
        kr["UI SELECT"] = "UI 선택";
        kr["SENIOR UI"] = "시니어 UI";
        kr["DEFAULT UI"] = "기본 UI";

        // 조작법/프로그램 설명
        kr["PROGRAM DESCRIPTION"] = "프로그램 설명";
        kr["조작 방법등의 대한 설명1"] = "조작 방법 설명 1";
        kr["조작 방법등의 대한 설명2"] = "조작 방법 설명 2";
        kr["조작 방법등의 대한 설명3"] = "조작 방법 설명 3";
        kr["조작 방법등의 대한 설명4"] = "조작 방법 설명 4";

        // 설정 메뉴 항목
        kr["SOUND OPTIONS"] = "사운드 옵션";
        kr["COPYRIGHT INFORMATION"] = "저작권 정보";
        kr["UI SELECTION"] = "UI 선택";

        // 로봇 선택
        kr["ROBOT SELECTION"] = "로봇 선택";
        kr["Choose Robot you can use"] = "사용할 로봇을 선택하세요";
        kr["ROBOMASTER EP01"] = "로보마스터 EP01";
        kr["Unitree Go1"] = "유니트리 Go1";
        kr["ADD ROBOT"] = "로봇 추가";

        // 맵 선택
        kr["MAP SELECTION"] = "맵 선택";
        kr["Choose Map you can use"] = "사용할 맵을 선택하세요";
        kr["MAP EDITER"] = "제작 맵";
        kr["CORRIDER"] = "복도";
        kr["ADD MAP"] = "맵 추가";

        // 토스트 메시지
        kr["TOAST_ROBOT_SELECTED"] = "{0}이(가) 선택되었습니다";
        kr["TOAST_MAP_SELECTED"]   = "{0} 맵이 선택되었습니다";
        kr["TOAST_UI_DEFAULT"] = "기본 UI가 적용되었습니다";
        kr["TOAST_UI_SENIOR"]  = "시니어 UI가 적용되었습니다";
    }
    public void SetLanguage(Language lang)
    {
        currentLanguage = lang;
        ApplyFontForCurrentLanguage();
        RefreshAll();
    }

    public void LoadSavedLanguage()
    {
        if (PlayerPrefs.HasKey("LANG"))
            currentLanguage = (Language)PlayerPrefs.GetInt("LANG");
    }

    public string Get(string key)
    {
        var table = (currentLanguage == Language.KR) ? kr : en;
        if (table.TryGetValue(key, out var value))
            return value;

        return key;
    }

    void RefreshAll()
    {
        var roots = SceneManager.GetActiveScene().GetRootGameObjects();
        foreach (var r in roots)
        {
            var texts = r.GetComponentsInChildren<LocalizedText>(true);
            foreach (var t in texts)
                t.Refresh();

            var images = r.GetComponentsInChildren<LocalizedImage>(true);
            foreach (var img in images)
            img.Refresh();
        }
    }
    void ApplyFontForCurrentLanguage()
    {
        TMP_FontAsset targetFont =
            (currentLanguage == Language.KR) ? fontKR : fontEN;

        var roots = SceneManager.GetActiveScene().GetRootGameObjects();
        foreach (var r in roots)
        {
            var localizedTexts = r.GetComponentsInChildren<LocalizedText>(true);
            foreach (var lt in localizedTexts)
            {
                lt.ApplyFont(targetFont);
            }
        }
    }
}
