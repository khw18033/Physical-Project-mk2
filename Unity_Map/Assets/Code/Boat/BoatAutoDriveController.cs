using System.Collections;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using Unity.MLAgents.Policies;
using Unity.InferenceEngine;

/// <summary>
/// Play 모드에서 UI 버튼 클릭으로 학습된 ONNX 모델을 활성화해
/// 배가 GoalPoint 까지 자율항해하도록 한다.
///
/// 사용법:
///   1. 씬의 BoatAutoDriveController GameObject 확인 (이미 추가됨)
///   2. onnxModel 필드에 BoatColregAgent.onnx 가 할당되어 있는지 확인
///   3. Play → "자율주행" 버튼 클릭
///   4. 수동 모드에서 우클릭으로 목표 위치 변경 가능
/// </summary>
public class BoatAutoDriveController : MonoBehaviour
{
    [Header("참조 (미설정 시 씬에서 자동 탐색)")]
    public BoatColregAgent targetBoat;
    public Transform       goalPoint;

    [Header("ONNX 모델")]
    public ModelAsset onnxModel;

    [Header("목표 표시")]
    public float goalDiscRadius = 5f;
    public Color goalDiscColor  = new Color(0f, 1f, 0.3f, 0.55f);

    // ── 런타임 ─────────────────────────────────────────────────────────────
    private BehaviorParameters bp;
    private bool               isAutoDriving;
    private GameObject         goalDisc;

    // UI
    private Text buttonLabel;
    private Text statusLabel;

    // ═══════════════════════════════════════════════════════════════════════
    // 초기화
    // ═══════════════════════════════════════════════════════════════════════

    private void Start()
    {
        if (targetBoat == null)
            targetBoat = FindFirstObjectByType<BoatColregAgent>();

        if (goalPoint == null)
        {
            var gp = GameObject.Find("GoalPoint");
            if (gp != null) goalPoint = gp.transform;
        }

        if (targetBoat == null)
        {
            Debug.LogError("[BoatAutoDrive] BoatColregAgent 를 찾지 못했습니다.");
            return;
        }

        bp = targetBoat.GetComponent<BehaviorParameters>();
        targetBoat.onGoalReached = HandleGoalReached;

        // 초기 상태는 씬 YAML 값을 그대로 사용 (별도 SetModel 호출 없음)
        // BehaviorType이 무엇이든 HeuristicOnly로 안전하게 전환
        bp.BehaviorType = BehaviorType.HeuristicOnly;

        CreateGoalDisc();
        BuildUI();
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 매 프레임
    // ═══════════════════════════════════════════════════════════════════════

    private void Update()
    {
        // 우클릭 → 수면(Y=0 평면)에 목표 이동 (수동 모드에서만)
        if (!isAutoDriving && goalPoint != null && Input.GetMouseButtonDown(1))
            TryMoveGoalToClick();

        // 목표 표시 원판 위치 동기화
        if (goalDisc != null && goalPoint != null)
            goalDisc.transform.position = new Vector3(
                goalPoint.position.x, 0.05f, goalPoint.position.z);
    }

    private void TryMoveGoalToClick()
    {
        if (Camera.main == null) return;
        var ray   = Camera.main.ScreenPointToRay(Input.mousePosition);
        var plane = new Plane(Vector3.up, Vector3.zero);
        if (plane.Raycast(ray, out float dist))
        {
            var hit = ray.GetPoint(dist);
            goalPoint.position = new Vector3(hit.x, goalPoint.position.y, hit.z);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 자율주행 제어
    // ═══════════════════════════════════════════════════════════════════════

    private void ToggleAutoDrive()
    {
        if (isAutoDriving) StopAutoDrive();
        else               StartAutoDrive();
    }

    private void StartAutoDrive()
    {
        if (targetBoat == null) return;
        if (onnxModel == null)  { SetStatus("오류: ONNX 모델 미할당"); return; }
        if (goalPoint == null)  { SetStatus("오류: GoalPoint 없음"); return; }

        targetBoat.SetGoal(goalPoint);

        // 순서 중요: 모델을 먼저 설정한 뒤 InferenceOnly로 전환
        // 반대 순서면 "InferenceOnly without model" 예외 발생
        bp.Model        = onnxModel;
        bp.BehaviorType = BehaviorType.InferenceOnly;

        isAutoDriving = true;
        buttonLabel.text = "수동 제어";
        SetStatus("자율주행 중...");
    }

    private void StopAutoDrive()
    {
        if (bp != null)
        {
            // HeuristicOnly 는 모델 유무와 무관하게 항상 안전하게 전환 가능
            bp.BehaviorType = BehaviorType.HeuristicOnly;
        }

        isAutoDriving = false;
        buttonLabel.text = "자율주행";
        SetStatus("대기 중  (WASD 조작 가능 | 우클릭: 목표 이동)");
    }

    private void HandleGoalReached()
    {
        SetStatus("목표 도달!");
        StartCoroutine(AfterGoalReached());
    }

    private IEnumerator AfterGoalReached()
    {
        yield return new WaitForSeconds(2f);
        if (isAutoDriving)
            StopAutoDrive();
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 목표 시각화
    // ═══════════════════════════════════════════════════════════════════════

    private void CreateGoalDisc()
    {
        if (goalPoint == null) return;

        goalDisc = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        goalDisc.name = "GoalDisc";
        goalDisc.transform.localScale = new Vector3(goalDiscRadius * 2f, 0.05f, goalDiscRadius * 2f);
        goalDisc.transform.position   = new Vector3(goalPoint.position.x, 0.05f, goalPoint.position.z);

        Destroy(goalDisc.GetComponent<Collider>());

        var rend = goalDisc.GetComponent<Renderer>();
        // URP / HDRP / Built-in 모두 호환되는 Unlit 계열 셰이더 사용
        var shader = Shader.Find("Universal Render Pipeline/Unlit")
                  ?? Shader.Find("Unlit/Color")
                  ?? Shader.Find("Standard");
        if (shader != null)
        {
            var mat = new Material(shader);
            mat.color = goalDiscColor;
            rend.material = mat;
        }
        else
        {
            rend.material.color = goalDiscColor;
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // UI (런타임 생성 — UGUI 레거시)
    // ═══════════════════════════════════════════════════════════════════════

    private void BuildUI()
    {
        // EventSystem 없으면 생성
        if (FindFirstObjectByType<EventSystem>() == null)
        {
            var esGO = new GameObject("EventSystem");
            esGO.AddComponent<EventSystem>();
            esGO.AddComponent<StandaloneInputModule>();
        }

        // Canvas
        var cvGO = new GameObject("BoatDriveCanvas");
        var cv   = cvGO.AddComponent<Canvas>();
        cv.renderMode   = RenderMode.ScreenSpaceOverlay;
        cv.sortingOrder = 100;
        cvGO.AddComponent<CanvasScaler>();
        cvGO.AddComponent<GraphicRaycaster>();

        // 패널 (좌하단)
        var panel    = MakeGO("Panel", cvGO.transform);
        var panelImg = panel.AddComponent<Image>();
        panelImg.color = new Color(0f, 0f, 0f, 0.6f);
        var pr = panel.GetComponent<RectTransform>();
        pr.anchorMin = pr.anchorMax = pr.pivot = Vector2.zero;
        pr.anchoredPosition = new Vector2(20f, 20f);
        pr.sizeDelta        = new Vector2(250f, 120f);

        // 타이틀
        var title = AddText(panel.transform, "Title", "선박 자율주행", 14, Color.cyan);
        SetAnchors(title, 0, 1, 1, 1, 8, -26, -8, -6);

        // 버튼
        var btnGO  = MakeGO("AutoBtn", panel.transform);
        var btnImg = btnGO.AddComponent<Image>();
        btnImg.color = new Color(0.15f, 0.5f, 0.9f);
        var btn = btnGO.AddComponent<Button>();
        btn.targetGraphic = btnImg;
        btn.onClick.AddListener(ToggleAutoDrive);
        var cs = btn.colors;
        cs.highlightedColor = new Color(0.3f, 0.65f, 1f);
        cs.pressedColor     = new Color(0.05f, 0.35f, 0.7f);
        btn.colors = cs;
        SetAnchors(btnGO, 0, 1, 1, 1, 8, -68, -8, -30);

        var btnLbl = AddText(btnGO.transform, "BtnLabel", "자율주행", 17, Color.white);
        Fill(btnLbl);
        buttonLabel = btnLbl.GetComponent<Text>();

        // 상태 텍스트
        var st = AddText(panel.transform, "Status",
                         "대기 중  (WASD 조작 가능 | 우클릭: 목표 이동)", 11,
                         new Color(0.8f, 0.8f, 0.8f));
        SetAnchors(st, 0, 0, 1, 0, 6, 6, -6, 34);
        statusLabel = st.GetComponent<Text>();
    }

    // ── UI 헬퍼 ──────────────────────────────────────────────────────────

    private static GameObject MakeGO(string name, Transform parent)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.AddComponent<RectTransform>();
        return go;
    }

    private static GameObject AddText(Transform parent, string name,
                                       string content, int size, Color color)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var t = go.AddComponent<Text>();
        t.text      = content;
        t.fontSize  = size;
        t.color     = color;
        t.alignment = TextAnchor.MiddleCenter;
        t.font      = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf")
                   ?? Resources.GetBuiltinResource<Font>("Arial.ttf");
        return go;
    }

    private static void SetAnchors(GameObject go,
                                    float anMinX, float anMinY, float anMaxX, float anMaxY,
                                    float ofMinX, float ofMinY, float ofMaxX, float ofMaxY)
    {
        var rt = go.GetComponent<RectTransform>();
        rt.anchorMin = new Vector2(anMinX, anMinY);
        rt.anchorMax = new Vector2(anMaxX, anMaxY);
        rt.offsetMin = new Vector2(ofMinX, ofMinY);
        rt.offsetMax = new Vector2(ofMaxX, ofMaxY);
    }

    private static void Fill(GameObject go)
    {
        var rt = go.GetComponent<RectTransform>();
        rt.anchorMin = Vector2.zero;
        rt.anchorMax = Vector2.one;
        rt.offsetMin = rt.offsetMax = Vector2.zero;
    }

    private void SetStatus(string msg)
    {
        if (statusLabel != null) statusLabel.text = msg;
    }
}
