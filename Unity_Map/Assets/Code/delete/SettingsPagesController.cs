using UnityEngine;

/*
===============================================================================
SettingsPagesController.cs
-------------------------------------------------------------------------------
Settings 창 내부의 페이지(Sound / UI / Program / Copyright)를
전환하는 전용 컨트롤러

목적:
- 설정 창 안에서 여러 설정 카테고리를 분리
- 한 번에 하나의 페이지만 활성화
- 버튼 클릭으로 페이지 전환

-------------------------------------------------------------------------------
[구성 요소]

1) pageSound
2) pageUI
3) pageProgram
4) pageCopyright

각각 Settings 패널 내부의 개별 페이지 GameObject

-------------------------------------------------------------------------------
[동작 흐름]

Start()
- 기본 시작 페이지를 ShowSound()로 설정

HideAll()
- 모든 페이지 비활성화

ShowSound()
ShowUI()
ShowProgram()
ShowCopyright()
- HideAll() 호출 후 해당 페이지만 활성화

-------------------------------------------------------------------------------
[사용 방법]

1) SettingsPagesController를 Settings 패널에 추가
2) 각 페이지 GameObject를 Inspector에 연결
3) 버튼 OnClick()에:
   - ShowSound()
   - ShowUI()
   - ShowProgram()
   - ShowCopyright()
   연결

-------------------------------------------------------------------------------
[특징]

- 단순하고 직관적인 페이지 전환 구조
- 한 번에 하나의 페이지만 활성화
- 탭 방식 UI에 적합

-------------------------------------------------------------------------------
[주의사항]

- 각 page가 null이면 NullReferenceException 발생 가능
  → 실제 사용 시 null 체크 추가하는 것이 안전
- UIManager에서도 페이지 제어를 하고 있다면
  중복 구조가 될 수 있음 (통합 권장)

-------------------------------------------------------------------------------
[개선 아이디어]

- 현재 선택된 탭 버튼 강조 효과 추가
- 애니메이션 전환(Fade / Slide)
- enum 기반 페이지 관리로 확장성 향상
- 페이지 배열 + 인덱스 방식으로 리팩토링

===============================================================================
*/
public class SettingsPagesController : MonoBehaviour
{
    [Header("Pages")]
    public GameObject pageSound;
    public GameObject pageUI;
    public GameObject pageProgram;
    public GameObject pageCopyright;

    void Start()
    {
        ShowSound(); // 시작 페이지
    }

    void HideAll()
    {
        pageSound.SetActive(false);
        pageUI.SetActive(false);
        pageProgram.SetActive(false);
        pageCopyright.SetActive(false);
    }

    public void ShowSound()
    {
        HideAll();
        pageSound.SetActive(true);
    }

    public void ShowUI()
    {
        HideAll();
        pageUI.SetActive(true);
    }

    public void ShowProgram()
    {
        HideAll();
        pageProgram.SetActive(true);
    }

    public void ShowCopyright()
    {
        HideAll();
        pageCopyright.SetActive(true);
    }
}
