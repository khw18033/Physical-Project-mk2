using UnityEngine;
using UnityEngine.UI;

/*
===============================================================================
LocalizedImage.cs
-------------------------------------------------------------------------------
언어(Language)에 따라 UI Image의 Sprite를 자동 교체하는 컴포넌트

[개요]
LocalizationManager의 currentLanguage 값을 기준으로
Image 컴포넌트의 sprite를 영어/한국어 버전으로 교체한다.

텍스트가 아닌 "이미지 기반 UI 요소(버튼 배경, 타이틀 로고, 안내 이미지 등)"
를 다국어 처리할 때 사용된다.

-------------------------------------------------------------------------------
[사용 방법]

1) Image가 붙어있는 UI 오브젝트에 LocalizedImage 추가
2) Inspector에서
   - englishSprite 설정
   - koreanSprite 설정
3) LocalizationManager가 SetLanguage() 호출 시
   RefreshAll() → img.Refresh()가 실행되어 sprite 자동 교체

-------------------------------------------------------------------------------
[동작 흐름]

Awake()
  → Image 컴포넌트 캐싱

OnEnable()
  → Refresh() 호출 (씬 진입 시 자동 반영)

Refresh()
  → LocalizationManager.Instance.currentLanguage 확인
  → KR이면 koreanSprite
  → 그 외(EN)면 englishSprite 적용

-------------------------------------------------------------------------------
[주의사항]

- LocalizationManager.Instance가 null이면 동작하지 않음
- Image 컴포넌트가 반드시 같은 GameObject에 있어야 함
- Sprite가 비어있으면 해당 언어에서 이미지가 표시되지 않음

-------------------------------------------------------------------------------
[확장 가능]

- 언어가 3개 이상일 경우:
  Dictionary<Language, Sprite> 구조로 확장 가능
- 버튼 Hover/Pressed 상태까지 언어별로 분리 가능
- Addressables로 언어별 리소스 분리 로딩 가능

===============================================================================
*/


public class LocalizedImage : MonoBehaviour
{
    [Header("Sprites by Language")]
    public Sprite englishSprite;
    public Sprite koreanSprite;

    Image img;

    void Awake()
    {
        img = GetComponent<Image>();
    }

    void OnEnable()
    {
        Refresh();
    }

    public void Refresh()
    {
        if (LocalizationManager.Instance == null || img == null) return;

        if (LocalizationManager.Instance.currentLanguage == Language.KR)
            img.sprite = koreanSprite;
        else
            img.sprite = englishSprite;
    }
}
