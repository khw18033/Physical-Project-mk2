using UnityEngine;
using UnityEngine.UI;

/*
===============================================================================
MapSelectionController.cs
-------------------------------------------------------------------------------
맵 선택 UI를 "좌/우 버튼으로 넘기는 페이지 방식"으로 구성하고,
각 맵 버튼 클릭 시 UIManager.ConfirmMapSelection()으로 선택을 확정하는 컨트롤러

목적:
- Corridor / Plain / AddMap 3가지 맵 선택 화면 구성
- 좌/우 화살표 버튼으로 맵 버튼(페이지)을 전환
- 현재 활성 페이지(맵)만 보이게 처리
- 맵 버튼 클릭 시 UIManager에 선택 확정 및 토스트/메인 복귀 처리 위임

-------------------------------------------------------------------------------
[구성 요소]

1) UIManager 참조
- uiManager : 맵 선택 확정(ConfirmMapSelection) 호출에 사용

2) Map Buttons (페이지 역할)
- corridorButton : Corridor 맵 버튼(GameObject)
- plainButton    : Plain 맵 버튼(GameObject)
- addMapButton   : Add Map 버튼(GameObject)

3) Arrow Buttons
- leftButton  : 이전(Prev)
- rightButton : 다음(Next)

4) startIndex
- 시작 시 표시할 페이지 인덱스 (0=Corridor, 1=Plain, 2=Add)

-------------------------------------------------------------------------------
[동작 흐름]

Awake()
1) pages 배열 구성 (Corridor / Plain / Add)
2) 좌/우 버튼 클릭 이벤트 연결
   - leftButton  -> Prev()
   - rightButton -> Next()
3) startIndex를 범위 내로 보정(ClampIndex) 후 Apply()로 초기 표시
4) 각 페이지(맵 버튼)에 클릭 리스너를 붙여 선택 확정 처리
   - corridorButton 클릭 -> ConfirmMapSelection(Corridor)
   - plainButton 클릭    -> ConfirmMapSelection(Plain)
   - addMapButton 클릭   -> ConfirmMapSelection(Add)

Next()/Prev()
- index를 순환(circular) 방식으로 변경
- Apply()로 현재 페이지 1개만 활성화

Apply()
- pages 배열을 순회하며 i==index인 오브젝트만 SetActive(true)
- 나머지는 SetActive(false)

-------------------------------------------------------------------------------
[특징]

- "페이지 1개만 보여주는" 캐러셀 구조
- 좌/우 이동은 끝에서 다시 처음/마지막으로 순환
- 버튼 클릭 시 맵 선택 확정 로직을 UIManager로 위임
  (선택 후 메인 복귀, 토스트 출력 등은 UIManager가 담당)

-------------------------------------------------------------------------------
[주의사항]

- corridorButton/plainButton/addMapButton 는
  반드시 Button 컴포넌트가 붙어있는 UI 오브젝트여야 함
- BindSelectClick()에서 RemoveAllListeners()를 호출하므로
  해당 버튼에 기존에 걸려있던 클릭 이벤트는 제거됨
  (기존 이벤트가 필요하면 제거 방식 수정 필요)
- pages 배열에 null이 들어가면 해당 페이지는 표시되지 않음

-------------------------------------------------------------------------------
[확장 아이디어]

- 현재 선택된 맵 이름/아이콘 표시
- 현재 index에 맞춰 점(●●●) 인디케이터 표시
- Add 맵은 미구현일 때 비활성/잠금 처리
- 스와이프(드래그)로 좌/우 넘기기 지원

===============================================================================
*/

public class MapSelectionController : MonoBehaviour
{
    [Header("UIManager")]
    public UIManager uiManager; // 씬의 UIManager 드래그

    [Header("Map Buttons (GameObjects)")]
    public GameObject corridorButton;
    public GameObject plainButton;
    public GameObject addMapButton;

    [Header("Arrow Buttons")]
    public Button leftButton;
    public Button rightButton;

    [Header("Start (0=Corridor, 1=Plain, 2=Add)")]
    public int startIndex = 0;

    int index = 0;
    GameObject[] pages;

    void Awake()
    {
        pages = new GameObject[]
        {
            corridorButton,
            plainButton,
            addMapButton
        };

        if (leftButton) leftButton.onClick.AddListener(Prev);
        if (rightButton) rightButton.onClick.AddListener(Next);

        index = ClampIndex(startIndex);
        Apply();

        // 각 버튼 클릭 시 “선택 확정”
        BindSelectClick(corridorButton, UIManager.MapType.Corridor);
        BindSelectClick(plainButton, UIManager.MapType.Plain);
        BindSelectClick(addMapButton, UIManager.MapType.Add);
    }

    void BindSelectClick(GameObject go, UIManager.MapType type)
    {
        if (!go) return;

        var btn = go.GetComponent<Button>();
        if (!btn) return;

        btn.onClick.RemoveAllListeners();
        btn.onClick.AddListener(() =>
        {
            if (uiManager) uiManager.ConfirmMapSelection(type);
        });
    }

    public void Next()
    {
        if (pages == null || pages.Length == 0) return;
        index = (index + 1) % pages.Length;
        Apply();
    }

    public void Prev()
    {
        if (pages == null || pages.Length == 0) return;
        index = (index - 1 + pages.Length) % pages.Length;
        Apply();
    }

    void Apply()
    {
        for (int i = 0; i < pages.Length; i++)
        {
            if (pages[i]) pages[i].SetActive(i == index);
        }
    }

    int ClampIndex(int v)
    {
        int max = pages.Length - 1;
        if (v < 0) return 0;
        if (v > max) return max;
        return v;
    }
}
