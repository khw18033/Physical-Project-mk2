using UnityEngine;
using TMPro;

/*
===============================================================================
LocalizedText.cs
-------------------------------------------------------------------------------
TMP_Text 기반 다국어 텍스트 자동 갱신 컴포넌트

[개요]
이 스크립트는 하나의 TMP_Text(UI 텍스트)에 붙어,
LocalizationManager의 현재 언어(currentLanguage)에 맞는
번역 문자열을 자동으로 적용한다.

또한, 언어에 따라 폰트(TMP_FontAsset)도 교체할 수 있도록 지원한다.

-------------------------------------------------------------------------------
[핵심 역할]

1) key 값을 기반으로 번역 문자열 조회
   → LocalizationManager.Instance.Get(key)

2) 언어 변경 시 Refresh()를 통해 텍스트 즉시 갱신

3) 필요 시 ApplyFont()로 언어별 폰트 교체

-------------------------------------------------------------------------------
[사용 방법]

1) TMP_Text가 붙은 UI 오브젝트에 LocalizedText 추가
2) Inspector에서 key 입력 (번역 테이블과 동일한 키)
   예: "start", "MAP SELECTION", "TOAST_ROBOT_SELECTED"
3) LocalizationManager.SetLanguage() 호출 시
   → RefreshAll() → 각 LocalizedText.Refresh() 자동 실행

-------------------------------------------------------------------------------
[동작 흐름]

Awake()
  → TMP_Text 캐싱

OnEnable()
  → Refresh() 실행 (씬 진입 시 자동 적용)

Refresh()
  → LocalizationManager.Instance.Get(key) 호출
  → tmp.text에 번역 문자열 적용

ApplyFont(font)
  → changeFontByLanguage=true일 경우만 적용
  → TMP_Text.font 교체

-------------------------------------------------------------------------------
[주의사항]

- key는 LocalizationManager의 Dictionary에 존재해야 정상 번역됨
- key가 없으면 key 문자열 그대로 출력됨 (누락 감지용)
- LocalizationManager.Instance가 null이면 동작하지 않음
- 폰트 교체 시 해당 폰트에 필요한 글리프가 포함되어 있어야 함

-------------------------------------------------------------------------------
[확장 가능]

- string.Format 지원 (예: "{0} MAP IS SELECTED")
- 자동 key 생성기와 연동 (AutoLocalizeInstaller)
- 폰트 크기/라인스페이싱 언어별 분리
- RTL(오른쪽→왼쪽) 언어 대응

===============================================================================
*/


public class LocalizedText : MonoBehaviour
{
    [Header("Localization Key (고정 키)")]
    public string key;

    [Header("Font Control")]
    public bool changeFontByLanguage = true; 

    TMP_Text tmp;

    void Awake()
    {
        tmp = GetComponent<TMP_Text>();
    }

    void OnEnable()
    {
        Refresh();
    }

    public void Refresh()
    {
        if (tmp == null) tmp = GetComponent<TMP_Text>();
        if (LocalizationManager.Instance == null) return;

        tmp.text = LocalizationManager.Instance.Get(key);
    }

    public void ApplyFont(TMP_FontAsset font)
    {
        if (!changeFontByLanguage) return;
        if (tmp == null) tmp = GetComponent<TMP_Text>();

        tmp.font = font;
    }
}
