using UnityEngine;

/*
===============================================================================
SettingsModalController.cs
-------------------------------------------------------------------------------
Settings 패널을 "모달(Modal) 창" 방식으로 제어하는 컨트롤러

목적:
- Settings 창을 열 때:
    → 배경을 어둡게(dimOverlay 활성화)
    → Settings 패널 표시
- 닫을 때:
    → Settings 패널 숨김
    → 배경 Overlay 제거

-------------------------------------------------------------------------------
[구성 요소]

1) dimOverlay
   - 배경을 어둡게 만드는 UI 오브젝트
   - 일반적으로 반투명 Image 전체화면

2) settingsPanel
   - 실제 설정 내용이 들어있는 패널

-------------------------------------------------------------------------------
[동작 흐름]

Awake()
- 씬 시작 시 Hide() 호출
  → 기본적으로 설정창과 오버레이는 꺼진 상태로 시작

Show()
- dimOverlay.SetActive(true)
- settingsPanel.SetActive(true)

Hide()
- settingsPanel.SetActive(false)
- dimOverlay.SetActive(false)

-------------------------------------------------------------------------------
[사용 방법]

1) 빈 GameObject에 SettingsModalController 추가
2) dimOverlay / settingsPanel 드래그 연결
3) 버튼 OnClick()에 Show() 또는 Hide() 연결

-------------------------------------------------------------------------------
[특징]

- 모달 구조로 단순하고 안전함
- UIManager 없이 독립적으로 사용 가능
- 다른 패널과 충돌하지 않음 (단일 모달 전용)

-------------------------------------------------------------------------------
[주의사항]

- UIManager에서도 Settings를 제어 중이라면
  제어 로직이 중복될 수 있음
- 여러 모달이 동시에 존재하면 Overlay 충돌 가능
  → 중앙 UIManager 통합 관리 권장

-------------------------------------------------------------------------------
[확장 아이디어]

- Fade In/Out 애니메이션 추가
- ESC 키 입력 시 Hide()
- Overlay 클릭 시 Hide()
- Show 시 특정 버튼 자동 선택 (EventSystem)

===============================================================================
*/

public class SettingsModalController : MonoBehaviour
{
    [Header("References")]
    public GameObject dimOverlay;
    public GameObject settingsPanel;

    void Awake()
    {
        Hide();
    }

    public void Show()
    {
        if (dimOverlay) dimOverlay.SetActive(true);
        if (settingsPanel) settingsPanel.SetActive(true);
    }

    public void Hide()
    {
        if (settingsPanel) settingsPanel.SetActive(false);
        if (dimOverlay) dimOverlay.SetActive(false);
    }
}
