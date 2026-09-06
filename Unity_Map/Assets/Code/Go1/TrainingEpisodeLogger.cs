using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using Unity.MLAgents;

/// <summary>
/// ML-Agents 학습 중 에피소드별 보상·성공 여부를 CSV로 저장합니다.
/// 논문 Section 6.1 "학습 결과 / 보상 곡선" 그래프용 데이터를 제공합니다.
///
/// 사용법:
///   - GO1 Agent 프리팹에 이 컴포넌트를 추가합니다.
///   - mlagents-learn 학습 중 자동으로 에피소드마다 기록됩니다.
///   - 출력: GO1_Training_Log/<session_id>/training_reward_curve.csv
/// </summary>
[DisallowMultipleComponent]
public class TrainingEpisodeLogger : MonoBehaviour
{
    [Header("References")]
    [Tooltip("로깅 대상 GO1Agent입니다.")]
    public GO1Agent agent;

    [Header("Output")]
    [Tooltip("결과 CSV를 저장할 프로젝트 루트 기준 폴더 이름입니다.")]
    public string outputFolderName = "GO1_Training_Log";

    [Tooltip("실행별 하위 폴더를 생성합니다 (타임스탬프).")]
    public bool createSessionSubfolder = true;

    [Header("Logging")]
    [Tooltip("N 에피소드마다 이동 평균 성공률을 계산합니다.")]
    [Min(1)]
    public int rollingWindowSize = 20;

    [Tooltip("학습 로그를 Console에 출력합니다.")]
    public bool debugLogs = false;

    // ─── 런타임 상태 ───
    private static readonly string sessionId =
        DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);

    private string csvPath;
    private bool initialized;

    private int  episodeCount;
    private int  successCount;
    private float cumulativeRewardSum;

    private readonly Queue<bool> rollingSuccess = new Queue<bool>();
    private int rollingSuccessCount;

    private float episodeStartTime;
    private float episodeStartReward;
    private Vector3 episodeStartPos;

    private void Awake()
    {
        if (agent == null)
            agent = GetComponent<GO1Agent>();
    }

    private void Start()
    {
        if (!Academy.Instance.IsCommunicatorOn)
            return;

        EnsureInit();
    }

    private void EnsureInit()
    {
        if (initialized) return;
        initialized = true;

        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        string baseDir = Path.Combine(projectRoot, outputFolderName);
        string dir = createSessionSubfolder
            ? Path.Combine(baseDir, sessionId)
            : baseDir;
        Directory.CreateDirectory(dir);

        csvPath = Path.Combine(dir, "training_reward_curve.csv");

        if (!File.Exists(csvPath) || new FileInfo(csvPath).Length == 0)
        {
            string header =
                "session_id,agent_name,episode,step_count,cumulative_reward," +
                "duration_sec,travel_distance_m,success,rolling_success_rate,total_success_rate\n";
            File.WriteAllText(csvPath, header, new UTF8Encoding(true));
        }

        episodeStartTime   = Time.time;
        episodeStartReward = 0f;
        episodeStartPos    = agent != null ? agent.transform.position : Vector3.zero;

        if (debugLogs)
            Debug.Log("[TrainingEpisodeLogger] 학습 에피소드 로그 초기화 | path=" + csvPath, this);
    }

    /// <summary>
    /// GO1Agent.OnEpisodeBegin 또는 SafeEndEpisode 시점에서 호출합니다.
    /// </summary>
    public void OnEpisodeEnded(bool success)
    {
        if (!Academy.Instance.IsCommunicatorOn)
            return;

        EnsureInit();

        episodeCount++;
        if (success) successCount++;

        // 이동 평균 성공률
        rollingSuccess.Enqueue(success);
        if (success) rollingSuccessCount++;
        if (rollingSuccess.Count > rollingWindowSize)
        {
            bool dropped = rollingSuccess.Dequeue();
            if (dropped) rollingSuccessCount--;
        }

        float rollingRate = rollingSuccess.Count > 0
            ? (float)rollingSuccessCount / rollingSuccess.Count
            : 0f;
        float totalRate = episodeCount > 0
            ? (float)successCount / episodeCount
            : 0f;

        float cumReward = agent != null ? agent.GetCumulativeReward() : 0f;
        int   steps     = agent != null ? agent.StepCount : 0;
        float duration  = Time.time - episodeStartTime;
        float travelDist = agent != null ? agent.GetActiveTrialTravelDistance() : 0f;

        string row = string.Join(",", new[]
        {
            Q(sessionId),
            Q(agent != null ? agent.gameObject.name : "unknown"),
            episodeCount.ToString(CultureInfo.InvariantCulture),
            steps.ToString(CultureInfo.InvariantCulture),
            F(cumReward),
            F(duration),
            F(travelDist),
            success ? "1" : "0",
            F(rollingRate),
            F(totalRate)
        });

        try { File.AppendAllText(csvPath, row + "\n", new UTF8Encoding(false)); }
        catch (Exception e)
        { Debug.LogError("[TrainingEpisodeLogger] CSV 저장 실패: " + e.Message); }

        if (debugLogs && episodeCount % 50 == 0)
        {
            Debug.Log(
                $"[TrainingEpisodeLogger] ep={episodeCount} " +
                $"reward={cumReward:F3} rolling={rollingRate:F3} total={totalRate:F3}",
                this
            );
        }

        episodeStartTime   = Time.time;
        episodeStartReward = 0f;
        episodeStartPos    = agent != null ? agent.transform.position : Vector3.zero;
    }

    private void OnEnable()
    {
        if (Academy.Instance.IsCommunicatorOn)
            EnsureInit();
    }

    private string F(float v) => v.ToString("F6", CultureInfo.InvariantCulture);
    private string Q(string v) => "\"" + (v ?? "").Replace("\"", "\"\"") + "\"";
}
