using UnityEngine;
using UnityEngine.EventSystems;

/*
===============================================================================
UIButtonHoverScale.cs
-------------------------------------------------------------------------------
UI 버튼에 마우스를 올리면(hover) 크기를 부드럽게 확대하고,
마우스를 벗어나면 원래 크기로 되돌리는 애니메이션 스크립트

목적:
- 버튼 인터랙션 시 시각적 피드백 제공
- UI를 더 부드럽고 고급스럽게 표현
- 클릭 유도 및 UX 개선

-------------------------------------------------------------------------------
[인터페이스]

IPointerEnterHandler
IPointerExitHandler

→ Unity EventSystem 기반 UI 이벤트 사용
→ 반드시 Canvas + GraphicRaycaster + EventSystem 존재 필요

-------------------------------------------------------------------------------
[구성 요소]

hoverScale
- 기본 크기의 몇 배로 확대할지 설정
- 예: 1.08f → 8% 확대

duration
- 확대/축소 애니메이션 시간 (초)

-------------------------------------------------------------------------------
[동작 흐름]

Awake()
- RectTransform 캐싱
- 기본 스케일(baseScale) 저장

OnPointerEnter()
- 목표 스케일 = baseScale * hoverScale
- StartScale() 호출

OnPointerExit()
- 목표 스케일 = baseScale
- StartScale() 호출

StartScale()
- 기존 애니메이션이 있다면 중지
- ScaleRoutine 코루틴 시작

ScaleRoutine()
1) 현재 스케일 저장
2) duration 동안 보간
3) SmoothStep(k = k*k*(3-2k)) 방식으로 부드러운 가속/감속
4) Vector3.LerpUnclamped로 스케일 적용

-------------------------------------------------------------------------------
[특징]

- Time.unscaledDeltaTime 사용
  → Time.timeScale = 0 (일시정지) 상태에서도 정상 작동
- 애니메이션 중 재진입 시 이전 코루틴 자동 중단
- 자연스러운 이징(Easing) 적용

-------------------------------------------------------------------------------
[주의사항]

- 반드시 RectTransform이 있는 UI 오브젝트에 사용
- EventSystem이 씬에 존재해야 Pointer 이벤트 작동
- 버튼이 비활성화되면 이벤트 발생하지 않음

-------------------------------------------------------------------------------
[확장 아이디어]

- 클릭 시 살짝 눌리는 효과 추가
- 색상 변화(Color.Lerp) 추가
- 사운드 효과 연동
- 모바일 터치 대응(IPointerDownHandler)
- VR 레이 인터랙션 대응(XR Interaction Toolkit 연동)

===============================================================================
*/

public class UIButtonHoverScale : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
{
    [Header("Scale")]
    public float hoverScale = 1.08f;     
    public float duration = 0.5f;     

    RectTransform rect;
    Vector3 baseScale;
    Coroutine animCo;

    void Awake()
    {
        rect = GetComponent<RectTransform>();
        baseScale = rect.localScale;
    }

    public void OnPointerEnter(PointerEventData eventData)
    {
        StartScale(baseScale * hoverScale);
    }

    public void OnPointerExit(PointerEventData eventData)
    {
        StartScale(baseScale);
    }

    void StartScale(Vector3 target)
    {
        if (animCo != null) StopCoroutine(animCo);
        animCo = StartCoroutine(ScaleRoutine(target));
    }

    System.Collections.IEnumerator ScaleRoutine(Vector3 target)
    {
        Vector3 start = rect.localScale;
        float t = 0f;

        while (t < duration)
        {
            t += Time.unscaledDeltaTime;
            float k = Mathf.Clamp01(t / duration);

            k = k * k * (3f - 2f * k);

            rect.localScale = Vector3.LerpUnclamped(start, target, k);
            yield return null;
        }

        rect.localScale = target;
        animCo = null;
    }
}
