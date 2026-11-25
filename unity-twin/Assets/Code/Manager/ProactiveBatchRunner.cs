// ProactiveEvaluationRunner를 에디터 창 없이(-batchmode) 돌리는 실행기.
// 설정은 GO1_Proactive_Evaluation/batch_config.json 에서 읽는다
// (Play 진입 때 도메인이 다시 로드되므로 static 값으로는 넘길 수 없다).
// session 하나 = 조건 목록 + 트윈 위치 오차 한 값. session을 차례로 실행하고 Unity를 종료한다.

using System;
using System.Collections;
using System.IO;
using UnityEngine;

public class ProactiveBatchRunner : MonoBehaviour
{
    public const string ConfigPath = "GO1_Proactive_Evaluation/batch_config.json";

    [Serializable]
    public class Session
    {
        public string label = "";
        public string[] conditions;
        public float noiseSigma = 0f;
        public string placement = "AlongPath";   // AlongPath | AfterCorner
        public int trials = 0;                   // 0이면 전체 설정값
        public float detectLatencySec = -1f;     // 0 미만이면 전체 설정값
        public int obstacleCount = 1;            // 2 이상이면 가는 도중에 차례로 나타난다
        public float appearMin = -1f, appearMax = -1f;   // 장애물이 나타나는 거리 범위(m). 0 미만이면 러너 기본값
        public float sizeMin = -1f, sizeMax = -1f;       // 장애물 크기 범위(m). 0 미만이면 고정 크기
        public bool requireInfraCoverage = false;        // 인프라 탐지 범위 안에만 장애물을 놓는다
        public float pathLenMin = -1f, pathLenMax = -1f; // 시작→목표 경로 길이 범위(m). 0 미만이면 러너 기본값
    }

    [Serializable]
    public class Config
    {
        public int trials = 30;
        public int baseSeed = 5000;
        public float timeScale = 1f;
        public float detectLatencySec = 0f;
        public float watchdogMinutes = 300f;
        public bool debugNavMesh = false;
        public float obstacleSizeXZ = 0f;   // 0이면 러너 기본값
        public string recordDir = "";       // 비어 있지 않으면 run마다 화면을 프레임으로 저장 (-nographics 없이 실행해야 함)
        public float navMeshPadding = -99f; // -90 이하면 실제 시스템 보정 파일(anchor360_calib.json) 값을 쓴다
        public string scene = "";           // 비우면 Assets/lab.unity (런처가 읽는다)
        public string calibFile = "";       // 인프라 카메라 위치를 읽을 보정 파일 이름. 비우면 anchor360_calib.json
        public float[] scenarios;           // 고정 시나리오: x1,z1,x2,z2 를 반복. 있으면 자동 생성 대신 이것을 쓴다 (trial i → i번째)
        public bool obstaclesAsPeople = false; // 나타나는 장애물을 사람 모형으로 보여 준다
        public bool recordAutoFrame = false; // 녹화 화면을 run 의 시작·목표 주변으로 확대한다 (넓은 맵용)
        public Session[] sessions;
    }

    // 실제 장비와 통신하는 컴포넌트. 가상 실험에는 필요 없고, 켜 두면 실제 검출이 씬에 섞인다.
    private static readonly string[] LiveLinkComponents =
    {
        "MJPEGReceiver", "MJPEGMeshReceiver", "ArUcoUDPReceiver", "Anchor360ObstacleReceiver",
        "Go1ObstacleJsonReceiver", "Go1ObstacleWebSocketReceiver", "Go1FrontGuardReceiver",
    };

    private void Awake()
    {
        Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
        Application.SetStackTraceLogType(LogType.Warning, StackTraceLogType.None);
    }

    private void Start()
    {
        StartCoroutine(RunBatch());
    }

    private IEnumerator RunBatch()
    {
        string root = Directory.GetParent(Application.dataPath).FullName;
        string cfgPath = Path.Combine(root, ConfigPath);
        if (!File.Exists(cfgPath)) { Fail("config not found: " + cfgPath); yield break; }
        Config cfg = JsonUtility.FromJson<Config>(File.ReadAllText(cfgPath));
        if (cfg == null || cfg.sessions == null || cfg.sessions.Length == 0) { Fail("config has no sessions"); yield break; }

        DisableLiveLinks();
        float settle = Time.realtimeSinceStartup;
        while (Time.realtimeSinceStartup - settle < 5f) yield return null;
        DisableLiveLinks();   // Play 시작 뒤 스스로 생기는 수신기까지

        foreach (GO1Agent a in FindObjectsByType<GO1Agent>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            Log("robot = '" + a.gameObject.name + "' active=" + a.gameObject.activeInHierarchy +
                " pos=" + a.transform.position.ToString("F2") +
                " target=" + (a.target != null ? a.target.position.ToString("F2") : "none"));

        var runner = new GameObject("ProactiveEvaluationRunner").AddComponent<ProactiveEvaluationRunner>();
        runner.trials = cfg.trials;
        runner.baseSeed = cfg.baseSeed;
        runner.timeScale = cfg.timeScale;
        runner.detectLatencySec = cfg.detectLatencySec;
        runner.autoStart = false;
        runner.debugNavMesh = cfg.debugNavMesh;
        runner.obstacleAsPerson = cfg.obstaclesAsPeople;
        if (cfg.obstacleSizeXZ > 0f)
            runner.obstacleSize = new Vector3(cfg.obstacleSizeXZ, runner.obstacleSize.y, cfg.obstacleSizeXZ);
        runner.navMeshPadding = cfg.navMeshPadding > -90f ? cfg.navMeshPadding : ReadCalibPadding();
        Log("navMeshPadding = " + runner.navMeshPadding);
        calibFileName = string.IsNullOrEmpty(cfg.calibFile) ? "anchor360_calib.json" : cfg.calibFile;
        Calib calib = ReadCalib();
        if (cfg.scenarios != null && cfg.scenarios.Length >= 4)
        {
            int n = cfg.scenarios.Length / 4;
            runner.startPoints = new Transform[n]; runner.goalPoints = new Transform[n];
            for (int i = 0; i < n; i++)
            {
                runner.startPoints[i] = new GameObject("BatchStart" + i).transform;
                runner.goalPoints[i] = new GameObject("BatchGoal" + i).transform;
                runner.startPoints[i].position = new Vector3(cfg.scenarios[4 * i], 0f, cfg.scenarios[4 * i + 1]);
                runner.goalPoints[i].position = new Vector3(cfg.scenarios[4 * i + 2], 0f, cfg.scenarios[4 * i + 3]);
            }
            Log("fixed scenarios: " + n);
        }
        if (calib != null)
        {
            runner.infraAnchor = new Vector3(calib.anchorX, 0f, calib.anchorZ);
            runner.infraRange = calib.range360M;
        }
        if (!string.IsNullOrEmpty(cfg.recordDir))
        {
            GO1Agent recAgent = FindFirstObjectByType<GO1Agent>();
            var rec = runner.gameObject.AddComponent<ProactiveRunRecorder>();
            rec.outputDir = Path.IsPathRooted(cfg.recordDir) ? cfg.recordDir : Path.Combine(root, cfg.recordDir);
            rec.Setup(recAgent);
            rec.autoFrame = cfg.recordAutoFrame;
            runner.recorder = rec;
            runner.visualMarkers = true;
            Log("recording to " + rec.outputDir);
        }
        for (int i = 0; i < 5; i++) yield return null;   // runner.Start()가 시작 pose를 잡을 때까지

        Vector2 defaultAppearRange = runner.appearDistanceRange;
        Vector2 defaultPathLen = runner.autoScenarioPathLength;
        float startAll = Time.realtimeSinceStartup;
        float watchdog = cfg.watchdogMinutes * 60f;

        foreach (Session s in cfg.sessions)
        {
            var conds = new ProactiveEvaluationRunner.EvalCondition[s.conditions.Length];
            for (int i = 0; i < conds.Length; i++)
                conds[i] = (ProactiveEvaluationRunner.EvalCondition)Enum.Parse(
                    typeof(ProactiveEvaluationRunner.EvalCondition), s.conditions[i]);
            runner.conditions = conds;
            runner.twinNoiseSigma = s.noiseSigma;
            runner.placementMode = (ProactiveEvaluationRunner.PlacementMode)Enum.Parse(
                typeof(ProactiveEvaluationRunner.PlacementMode), string.IsNullOrEmpty(s.placement) ? "AlongPath" : s.placement);
            runner.trials = s.trials > 0 ? s.trials : cfg.trials;
            runner.detectLatencySec = s.detectLatencySec >= 0f ? s.detectLatencySec : cfg.detectLatencySec;
            runner.obstacleCount = Mathf.Max(1, s.obstacleCount);
            runner.obstacleSizeRange = (s.sizeMin > 0f && s.sizeMax > s.sizeMin) ? new Vector2(s.sizeMin, s.sizeMax) : Vector2.zero;
            runner.requireInfraCoverage = s.requireInfraCoverage;
            runner.autoScenarioPathLength = (s.pathLenMin > 0f && s.pathLenMax > s.pathLenMin)
                ? new Vector2(s.pathLenMin, s.pathLenMax) : defaultPathLen;
            runner.appearDistanceRange = (s.appearMin > 0f && s.appearMax > 0f)
                ? new Vector2(s.appearMin, s.appearMax) : defaultAppearRange;
            runner.sessionLabel = s.label;

            int total = runner.trials * conds.Length;
            Log("session '" + s.label + "' start | conditions=" + string.Join("|", s.conditions) +
                " noiseSigma=" + s.noiseSigma + " runs=" + total);
            runner.StartEvaluation();
            if (!runner.IsRunning) { Fail("session '" + s.label + "' did not start"); yield break; }

            float nextBeat = Time.realtimeSinceStartup + 60f;
            while (runner.IsRunning)
            {
                float now = Time.realtimeSinceStartup;
                if (now - startAll > watchdog)
                {
                    Debug.LogError("[ProactiveBatch] watchdog expired in session '" + s.label + "' at run " + runner.RunsDone);
                    Quit(2);
                    yield break;
                }
                if (now >= nextBeat)
                {
                    nextBeat = now + 60f;
                    Log("heartbeat " + ((now - startAll) / 60f).ToString("F1") + " min | session '" + s.label +
                        "' run " + runner.RunsDone + "/" + total + " trial " + runner.CurrentTrial +
                        " " + runner.CurrentCondition + " frame " + Time.frameCount);
                }
                yield return null;
            }
            Log("session '" + s.label + "' done | runs=" + runner.RunsDone + " out=" + runner.SessionDir);
            yield return new WaitForSecondsRealtime(1.1f);   // 다음 session 폴더 이름(초 단위)이 겹치지 않게
        }

        Log("ProactiveBatchRunner: OK, " + ((Time.realtimeSinceStartup - startAll) / 60f).ToString("F1") + " min");
        Quit(0);
    }

    [Serializable] private class Calib { public float navMeshPadding = 0f; public float anchorX, anchorZ, range360M = 4f; }

    private static string calibFileName = "anchor360_calib.json";
    private static Calib ReadCalib()
    {
        try
        {
            string p = Path.Combine(Application.streamingAssetsPath, calibFileName);
            return File.Exists(p) ? JsonUtility.FromJson<Calib>(File.ReadAllText(p)) : null;
        }
        catch { return null; }
    }

    private static float ReadCalibPadding()
    {
        Calib c = ReadCalib();
        return c != null ? c.navMeshPadding : 0f;
    }

    private void DisableLiveLinks()
    {
        int n = 0;
        foreach (MonoBehaviour mb in FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            if (mb == null || !mb.enabled) continue;
            if (Array.IndexOf(LiveLinkComponents, mb.GetType().Name) < 0) continue;
            mb.enabled = false;
            n++;
            Log("live link disabled: " + mb.GetType().Name + " on '" + mb.gameObject.name + "'");
        }
        Log("live links disabled: " + n);
    }

    private static void Log(string m) { Debug.Log("[ProactiveBatch] " + m); }

    private void Fail(string m)
    {
        Debug.LogError("[ProactiveBatch] FAILED: " + m);
        Quit(1);
    }

    private static void Quit(int code)
    {
#if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(code);
#else
        Application.Quit(code);
#endif
    }
}
