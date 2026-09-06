using UnityEngine;

/*
===============================================================================
LanguageSelectButton.cs
-------------------------------------------------------------------------------
UI 버튼 클릭으로 언어(Language)를 선택하고, LocalizationManager에 적용하는 스크립트

[개요]
이 컴포넌트는 특정 Language 값을 하나 들고 있다가,
버튼 클릭 이벤트에서 LocalizationManager.Instance.SetLanguage(lang)를 호출하여
게임/앱의 현재 언어를 변경한다.

즉, "언어 선택 버튼"을 가장 간단하게 구현하기 위한 UI 연결용 스크립트이다.

-------------------------------------------------------------------------------
[사용 방법]

1) 언어 선택 버튼(GameObject)에 이 스크립트를 추가
2) Inspector에서 lang 값을 원하는 언어로 설정 (예: KR/EN/JP 등)
3) Button 컴포넌트의 OnClick() 이벤트에
   - 해당 오브젝트의 LanguageSelectButton.Click()을 연결

버튼 예시:
- "English" 버튼 → lang = Language.EN
- "한국어" 버튼 → lang = Language.KR

-------------------------------------------------------------------------------
[동작 흐름]

Click()
 → LocalizationManager.Instance 존재 확인
 → SetLanguage(lang) 호출
 → (LocalizationManager가 구현한 방식대로) 모든 LocalizedText가 갱신됨

-------------------------------------------------------------------------------
[주의사항]

- LocalizationManager.Instance가 null이면 아무 동작도 하지 않음
  (씬에 LocalizationManager가 존재하는지 확인 필요)
- Language enum 값과 번역 테이블의 키/언어 코드가 일치해야 정상 표시됨

===============================================================================
*/

public class LanguageSelectButton : MonoBehaviour
{
    public Language lang = Language.EN;

    public void Click()
    {
        if (LocalizationManager.Instance != null)
            LocalizationManager.Instance.SetLanguage(lang);
    }
}
