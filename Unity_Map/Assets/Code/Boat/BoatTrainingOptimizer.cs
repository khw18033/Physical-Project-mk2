using UnityEngine;
using Unity.MLAgents;

/// <summary>
/// ML-Agents 학습 중 렉을 줄이기 위한 최적화 설정.
/// 씬의 빈 GameObject에 부착하면 자동으로 적용된다.
/// </summary>
public class BoatTrainingOptimizer : MonoBehaviour
{
    [Header("Time")]
    [Tooltip("학습 배속. 높을수록 빠르게 학습 (20 이하 권장)")]
    [Range(1f, 20f)]
    public float trainingTimeScale = 20f;

    [Tooltip("물리 스텝 크기. 작을수록 안정적 (기본 0.02, 높은 timeScale에서도 변경 금지)")]
    public float fixedTimestep = 0.02f;

    [Header("Rendering")]
    [Tooltip("학습 중 프레임레이트 제한. -1 = 무제한")]
    public int targetFrameRate = 10;

    [Tooltip("학습 중 그래픽 품질 레벨 (0 = 최저)")]
    public int qualityLevel = 0;

    [Header("Camera")]
    [Tooltip("학습 중 메인 카메라 비활성화 (렌더링 비용 절감)")]
    public bool disableCameraOnTraining = true;

    private void Start()
    {
        StartCoroutine(ApplyAfterConnect());
    }

    private System.Collections.IEnumerator ApplyAfterConnect()
    {
        // Academy 연결 대기 (Awake에서 체크하면 Python 연결 전이라 false 반환)
        yield return null;

        if (!Academy.Instance.IsCommunicatorOn)
        {
            Debug.Log("[BoatTrainingOptimizer] 추론 모드 — 최적화 적용 안 함");
            yield break;
        }

        Time.timeScale      = trainingTimeScale;
        Time.fixedDeltaTime = fixedTimestep;
        Application.targetFrameRate = targetFrameRate;
        QualitySettings.SetQualityLevel(qualityLevel, true);

        if (disableCameraOnTraining && Camera.main != null)
            Camera.main.gameObject.SetActive(false);

        Debug.Log($"[BoatTrainingOptimizer] 학습 최적화 적용: " +
                  $"timeScale={trainingTimeScale}, FPS={targetFrameRate}, 카메라={!disableCameraOnTraining}");
    }
}
