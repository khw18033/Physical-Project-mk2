using UnityEngine;
using TMPro;

/*
===============================================================================
FontReplacer.cs
-------------------------------------------------------------------------------
씬 내 모든 TMP_Text(TextMeshPro) 컴포넌트의 폰트를
지정한 TMP_FontAsset으로 일괄 교체하는 유틸리티 스크립트

목적:
- 다국어 대응 폰트 교체 (한글/영문/중문 등)
- UI 스타일 통일
- 프로젝트 전체 폰트 빠른 테스트
- 기존 프리팹/씬 텍스트를 한 번에 교체

-------------------------------------------------------------------------------
[사용 방법]

1) 빈 GameObject 생성 후 FontReplacer 스크립트 추가
2) Inspector에서 newFont에 TMP_FontAsset 지정
3) 우측 상단 ⋮ 또는 Context Menu에서
   "Change All Fonts" 클릭
4) 씬 내 모든 TMP_Text가 해당 폰트로 변경됨

-------------------------------------------------------------------------------
[동작 방식]

ReplaceAllFonts()
  1) newFont가 null이면 경고 후 종료
  2) FindObjectsByType<TMP_Text>()로
     씬 내 모든 TMP_Text 검색
     (비활성 오브젝트도 포함: FindObjectsInactive.Include)
  3) 각 TMP_Text.font를 newFont로 교체
  4) 교체된 개수 로그 출력

-------------------------------------------------------------------------------
[특징]

- 최신 Unity 방식 FindObjectsByType 사용
- 비활성 오브젝트까지 포함해서 검색
- 정렬 불필요하므로 FindObjectsSortMode.None 사용
- ContextMenu 속성으로 에디터에서 버튼처럼 실행 가능

-------------------------------------------------------------------------------
[주의사항]

- 프리팹 에셋 자체는 수정되지 않음
  → 현재 "씬에 존재하는 오브젝트"만 변경됨
- 런타임 중 실행 시 즉시 모든 텍스트가 변경됨
- 특정 UI만 바꾸고 싶으면 필터링 로직 추가 필요

-------------------------------------------------------------------------------
[확장 아이디어]

- 특정 Canvas 하위만 교체
- 특정 폰트(oldFont)인 경우만 교체
- 굵기(FontWeight) 또는 머티리얼도 함께 변경
- 언어 변경 시 자동으로 ReplaceAllFonts 호출
- Editor 전용 스크립트로 만들어 프리팹까지 일괄 변경

===============================================================================
*/

public class FontReplacer : MonoBehaviour
{
    public TMP_FontAsset newFont;

    [ContextMenu("Change All Fonts")]
    public void ReplaceAllFonts()
    {
        if (newFont == null)
        {
            Debug.LogWarning("새 폰트가 지정되지 않았습니다.");
            return;
        }

        // 최신 Unity 방식
        TMP_Text[] allText = UnityEngine.Object.FindObjectsByType<TMP_Text>(
            FindObjectsInactive.Include,
            FindObjectsSortMode.None
        );

        int count = 0;

        foreach (var text in allText)
        {
            text.font = newFont;
            count++;
        }

        Debug.Log($"{count}개의 폰트를 {newFont.name}(으)로 교체했습니다.");
    }
}