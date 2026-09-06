using UnityEngine;

/*
===============================================================================
DescriptionPager.cs
-------------------------------------------------------------------------------
여러 개의 설명 페이지(GameObject 배열)를
"한 번에 하나만 활성화"하는 간단한 페이지 전환 매니저

목적:
- 프로그램 설명 페이지 전환
- 튜토리얼 슬라이드 UI
- 좌/우 버튼으로 넘기는 설명 화면
- 이미지/텍스트 그룹 여러 개 중 1개만 표시

-------------------------------------------------------------------------------
[구성]

- descriptionPages : 페이지로 사용할 GameObject 배열
  (각 페이지는 하나의 패널/슬라이드 루트 오브젝트)

- currentIndex : 현재 표시 중인 페이지 인덱스

-------------------------------------------------------------------------------
[동작 흐름]

Start()
  → ShowPage(0) 호출
  → 시작 시 첫 번째 페이지만 활성화

NextPage()
  → currentIndex 증가
  → 배열 길이를 초과하면 0으로 되돌림 (순환 구조)
  → ShowPage(currentIndex)

PrevPage()
  → currentIndex 감소
  → 0보다 작아지면 마지막 인덱스로 이동 (순환 구조)
  → ShowPage(currentIndex)

ShowPage(index)
  → 모든 페이지를 순회하면서
     i == index 인 페이지만 SetActive(true)
     나머지는 SetActive(false)

-------------------------------------------------------------------------------
[특징]

- "순환(circular) 페이징" 구조
  → 마지막에서 Next 누르면 첫 페이지로
  → 첫 페이지에서 Prev 누르면 마지막으로

- 간단하고 안정적 (상태는 currentIndex 하나로 관리)

-------------------------------------------------------------------------------
[주의사항]

- descriptionPages 배열이 비어 있으면 오류 가능
  → Inspector에서 반드시 페이지들을 순서대로 할당

- 각 페이지는 반드시 "루트 오브젝트 단위"로 넣는 것이 좋음
  (자식 오브젝트들을 묶는 부모)

-------------------------------------------------------------------------------
[확장 아이디어]

- 현재 페이지 번호 UI 표시 (ex: 1 / 4)
- 특정 페이지로 직접 이동 (GoToPage(int))
- 애니메이션(슬라이드 전환 효과, 페이드)
- 페이지 전환 시 사운드 효과
- 마지막 페이지에서 Next를 막고 순환 제거 옵션 추가

===============================================================================
*/

public class DescriptionPager : MonoBehaviour
{
    [Header("Description Pages")]
    public GameObject[] descriptionPages; 

    private int currentIndex = 0;

    void Start()
    {
        ShowPage(0);
    }

    public void NextPage()
    {
        currentIndex++;
        if (currentIndex >= descriptionPages.Length)
            currentIndex = 0;

        ShowPage(currentIndex);
    }

    public void PrevPage()
    {
        currentIndex--;
        if (currentIndex < 0)
            currentIndex = descriptionPages.Length - 1;

        ShowPage(currentIndex);
    }

    void ShowPage(int index)
    {
        for (int i = 0; i < descriptionPages.Length; i++)
        {
            descriptionPages[i].SetActive(i == index);
        }
    }
}
