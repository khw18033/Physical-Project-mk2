using UnityEngine;

/*
===============================================================================
SettingsBackButton.cs
-------------------------------------------------------------------------------
Settings 패널의 "뒤로가기(Back)" 버튼 전용 스크립트

목적:
- 설정 패널(Settings Panel) 닫기
- 배경 어둡게 처리한 Dim Overlay 비활성화
- UIManager를 거치지 않고 간단히 패널만 닫는 용도

-------------------------------------------------------------------------------
[구성 요소]

1) settingsPanel
   - 닫을 설정 패널(GameObject)

2) dimOverlay
   - 어두운 배경 오버레이(GameObject)

-------------------------------------------------------------------------------
[동작 방식]

OnBack()
- settingsPanel.SetActive(false)
- dimOverlay.SetActive(false)

→ 버튼 OnClick 이벤트에 OnBack()을 연결해서 사용

-------------------------------------------------------------------------------
[사용 방법]

1) SettingsBackButton 스크립트를 Back 버튼에 붙이기
2) Inspector에서:
   - settingsPanel 에 Settings 패널 오브젝트 드래그
   - dimOverlay 에 공통 Overlay 오브젝트 드래그
3) Button → OnClick() → OnBack() 연결

-------------------------------------------------------------------------------
[주의사항]

- UIManager를 사용하는 구조라면
  UIManager.CloseSettings()를 호출하는 방식이 더 일관적일 수 있음
- 현재 구조는 단순 패널 닫기 전용이므로
  다른 패널 정리 로직은 포함되지 않음

-------------------------------------------------------------------------------
[개선 아이디어]

- UIManager 참조 후 uiManager.CloseSettings() 호출 방식으로 통일
- ESC 키 입력으로도 닫히도록 확장
- 애니메이션(Fade Out) 추가

===============================================================================
*/


public class SettingsBackButton : MonoBehaviour
{
    [Header("UI References")]
    public GameObject settingsPanel;
    public GameObject dimOverlay;

    public void OnBack()
    {
        if (settingsPanel != null)
            settingsPanel.SetActive(false);

        if (dimOverlay != null)
            dimOverlay.SetActive(false);
    }
}
