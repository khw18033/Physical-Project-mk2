using UnityEngine;
using TMPro;

/*
===============================================================================
AutoLocalizeInstaller.cs
-------------------------------------------------------------------------------
TMP_Text 오브젝트에 LocalizedText 컴포넌트를 자동으로 추가하는
에디터 전용 자동 설치 도구

[개요]
프로젝트 내 모든 TMP_Text(TextMeshPro) 컴포넌트를 검색하여,
LocalizedText 컴포넌트가 없는 오브젝트에 자동으로 추가한다.

기존 텍스트 내용을 기본 로컬라이즈 key로 설정하여
다국어 시스템 구축을 빠르게 초기 세팅할 수 있도록 돕는다.

-------------------------------------------------------------------------------
[사용 방법]

1) Hierarchy에서 AutoLocalizeInstaller가 붙은 오브젝트 선택
2) Inspector 우측 상단 메뉴 → "Auto Attach LocalizedText to all TMP_Text" 클릭
3) 프로젝트 내 모든 TMP_Text 검색
4) LocalizedText가 없는 경우 자동 추가

※ UNITY_EDITOR 환경에서만 실행 가능
   빌드된 게임에서는 동작하지 않음

-------------------------------------------------------------------------------
[동작 방식]

- FindObjectsByType<TMP_Text>()로
  활성/비활성 포함 모든 TMP_Text 검색
- 이미 LocalizedText가 붙어 있으면 스킵
- 없으면 AddComponent<LocalizedText>()
- 기본 key 설정 규칙:
    1) 현재 텍스트 내용(trimmed)을 key로 사용
    2) 비어있으면 "TMP_오브젝트이름" 형태로 생성

-------------------------------------------------------------------------------
[예시]

버튼 텍스트:
    "Start Game"

→ LocalizedText.key = "Start Game"

텍스트가 비어있는 경우:
    오브젝트 이름이 "TitleText"

→ LocalizedText.key = "TMP_TitleText"

-------------------------------------------------------------------------------
[목적]

- 수십/수백 개의 TMP_Text에 수동으로 LocalizedText 추가하는 작업 제거
- 다국어 시스템 초기 세팅 자동화
- 로컬라이제이션 누락 방지

-------------------------------------------------------------------------------
[주의]

- 기존 텍스트 값이 곧 key가 되므로,
  추후 CSV/JSON 번역 파일과 key를 일치시켜야 함
- 중복 key 발생 가능 → 별도 정리 필요

===============================================================================
*/


public class AutoLocalizeInstaller : MonoBehaviour
{
    [ContextMenu("Auto Attach LocalizedText to all TMP_Text")]
    public void Install()   
    {
#if !UNITY_EDITOR
        Debug.LogWarning("[AutoLocalizeInstaller] This tool is intended for Editor use only.");
        return;
#endif

        var allTexts = UnityEngine.Object.FindObjectsByType<TMP_Text>(
            FindObjectsInactive.Include,
            FindObjectsSortMode.None
        );

        int added = 0;
        foreach (var t in allTexts)
        {
            if (t == null) continue;
            if (t.GetComponent<LocalizedText>() != null) continue;

            var lt = t.gameObject.AddComponent<LocalizedText>();

            var raw = t.text ?? string.Empty;
            var key = raw.Trim();

            if (string.IsNullOrEmpty(key))
                key = $"TMP_{t.gameObject.name}";

            lt.key = key;
            added++;
        }

        Debug.Log($"[AutoLocalizeInstaller] Added LocalizedText to {added} TMP_Text objects.");
    }
}