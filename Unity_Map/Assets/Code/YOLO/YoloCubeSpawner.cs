using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

/*
===============================================================================
YoloCubeSpawner.cs
-------------------------------------------------------------------------------
YOLO 객체 탐지 결과를 Unity 월드에서 "기둥(큐브)"로 시각화하는 스포너
- (옵션) UDP로 탐지 결과 수신
- id별 다중 트래킹 또는 단일 오브젝트 재사용
- 정확도(confidence) 필터링, 지터 방지, 스무딩 이동, TTL 자동 삭제 지원

[개요]
외부(Python YOLO 등)에서 계산한 객체 좌표(x,z)와 id/conf 값을
Unity로 전달받아, 해당 위치에 큐브(기둥)를 생성/갱신한다.

목적:
- 디지털 트윈/로봇 프로젝트에서 객체 위치를 3D 씬에 즉시 표시
- 탐지 결과 디버깅 및 가시화(visualization)
- 여러 객체를 id 기준으로 지속 추적(멀티 트래킹)

-------------------------------------------------------------------------------
[입력 데이터(UDP 메시지) 지원 포맷]

1) "id x z conf"   (권장)
   예) "person_0  1.25  3.10  0.82"

2) "id x z"        (호환)
   예) "box_2  0.50  2.20"

3) "x z"           (호환, 단일 객체 모드로 처리)
   예) "1.00  4.00"

※ 구분자는 공백 또는 콤마 혼용 가능(내부에서 ',' → ' ' 처리)

-------------------------------------------------------------------------------
[주요 기능]

1) UDP 수신(옵션)
- useUdp=true일 때 listenPort에서 수신 스레드 시작
- 수신 스레드에서 파싱 후 메시지를 큐(_pending)에 적재
- 메인 스레드(Update)에서 DrainQueue()로 실제 오브젝트 생성/갱신 처리
  (Unity API는 메인 스레드에서만 호출해야 하므로 큐 구조 사용)

2) 단일 / 다중 트래킹
- reuseSingleCube=true  : 큐브 1개만 생성 후 위치만 갱신(기존 방식)
- reuseSingleCube=false : id별로 큐브를 생성/관리(Dictionary)

3) Confidence 필터
- minConfidence 이상인 탐지만 생성/갱신
- 낮은 conf는 무시(노이즈 제거)

4) Anti-jitter(지터 방지)
- minMoveEps 이하의 작은 위치 변화는 갱신하지 않음
  (탐지 좌표 흔들림으로 인한 떨림 감소)

5) 스무딩 이동
- smoothMove=true일 때 targetPos로 Lerp 이동
- moveLerp 값으로 추종 속도 조절

6) TTL 자동 삭제
- ttlSeconds 동안 특정 id가 업데이트 안 되면 해당 큐브 Destroy
- 단일 모드에서도 동일하게 일정 시간 미수신 시 삭제

7) 데모 스폰(P 키)
- demoSpawnKey(P)로 미리 정의된 위치에 테스트 스폰 가능
- UDP 없이도 동작 확인/디버깅 가능

-------------------------------------------------------------------------------
[좌표/높이 처리]

- 입력은 x,z 평면 기준으로 받고,
- y는 바닥에 붙이도록 GroundY()로 결정:
  - autoGroundSnap=true  → cubeScale.y/2 (바닥에 딱 닿게)
  - autoGroundSnap=false → yHeight 사용

-------------------------------------------------------------------------------
[주의사항]

- UDP 포트 중복 바인딩 시 bind 실패 가능
- YOLO 좌표계(카메라 기준) → Unity 월드 좌표 변환은 별도 보정이 필요할 수 있음
  (본 스크립트는 “이미 월드 좌표로 변환된 x,z가 들어온다”는 가정)
- Primitive Cube는 기본 Collider가 생성됨 (필요 시 제거/레이어 설정 권장)

-------------------------------------------------------------------------------
[확장 가능]

- 큐브 대신 프리팹(라벨/아이콘 포함) 스폰
- id별 색상/텍스트 표시(TMP_Text) 추가
- 카메라/로봇 좌표계를 이용한 자동 월드 변환 로직 통합
- 탐지 결과 히스토리(트레일) 시각화

===============================================================================
*/


public class YoloCubeSpawner : MonoBehaviour
{
    [Header("Spawn Settings")]
    public bool useUdp = false;
    public int listenPort = 15103;

    [Header("Shape (Pillar)")]
    public Vector3 cubeScale = new Vector3(0.2f, 1.0f, 0.2f); 
    [Tooltip("바닥에 붙이려면 자동으로 cubeScale.y/2를 사용합니다.")]
    public bool autoGroundSnap = true;
    public float yHeight = 0.5f; 

    [Header("Demo Spawn (Key Input)")]
    public KeyCode demoSpawnKey = KeyCode.L;
    public Vector3 demoSpawnPos1 = new Vector3(2f, 0f, 1f);
    public Vector3 demoSpawnPos2 = new Vector3(0f, 0f, 3f);
    public Vector3 demoSpawnPos3 = new Vector3(-1.5f, 0f, 2f);

    [Header("Single / Multi")]
    [Tooltip("true면 1개만 재사용(기존 방식). false면 id별로 여러 개 생성/관리.")]
    public bool reuseSingleCube = true;

    [Header("Anti-jitter")]
    public float minMoveEps = 0.01f; 

    [Header("TTL (Auto Delete)")]
    [Tooltip("이 시간(초) 동안 해당 id가 업데이트 안되면 삭제.")]
    public float ttlSeconds = 2.0f;

    [Header("Smoothing")]
    public bool smoothMove = true;
    public float moveLerp = 20f;

    [Header("Confidence Filter")]
    [Tooltip("confidence(정확도)가 이 값 이상일 때만 생성/갱신합니다.")]
    public float minConfidence = 0.5f;

    private UdpClient _udp;
    private Thread _rxThread;
    private volatile bool _running = false;

    private readonly object _queueLock = new object();
    private readonly Queue<Msg> _pending = new Queue<Msg>();

    private GameObject _singleCube;
    private Vector3 _singleTargetPos;
    private float _singleLastSeenTime = -999f;
    private Vector3 _lastPosSingle = new Vector3(float.NaN, float.NaN, float.NaN);

    private class TrackItem
    {
        public GameObject go;
        public Vector3 targetPos;
        public float lastSeenTime;
        public Vector3 lastAppliedPos; 
    }
    private readonly Dictionary<string, TrackItem> _items = new Dictionary<string, TrackItem>();

    private int _demoIndex = 0;

    private struct Msg
    {
        public bool hasId;
        public string id;     
        public Vector3 xz;    
        public float conf;   
        public bool hasConf; 
    }

    void Start()
    {
        if (useUdp) StartUdp();
    }

    void OnDisable() => StopUdp();
    void OnDestroy() => StopUdp();

    void Update()
    {
        if (Input.GetKeyDown(demoSpawnKey))
        {
            Vector3 p = GetDemoPos();

            if (reuseSingleCube)
            {
                EnqueueSingle(p, 1.0f, true);
                Debug.Log($"[DEMO] single enqueue at (x={p.x}, z={p.z})");
            }
            else
            {
                string id = $"DEMO_{_demoIndex}";
                EnqueueWithId(id, p, 1.0f, true);
                Debug.Log($"[DEMO] id={id} enqueue at (x={p.x}, z={p.z})");
            }
        }

        DrainQueue();

        if (smoothMove)
        {
            if (reuseSingleCube && _singleCube != null)
            {
                _singleCube.transform.position = Vector3.Lerp(
                    _singleCube.transform.position, _singleTargetPos, Time.deltaTime * moveLerp);
            }
            else if (!reuseSingleCube)
            {
                foreach (var kv in _items)
                {
                    var it = kv.Value;
                    if (it.go == null) continue;
                    it.go.transform.position = Vector3.Lerp(
                        it.go.transform.position, it.targetPos, Time.deltaTime * moveLerp);
                }
            }
        }

        CleanupExpired();
    }

    private Vector3 GetDemoPos()
    {
        _demoIndex = (_demoIndex + 1) % 3;
        if (_demoIndex == 0) return demoSpawnPos1;
        if (_demoIndex == 1) return demoSpawnPos2;
        return demoSpawnPos3;
    }

    private void EnqueueSingle(Vector3 worldXZ, float conf, bool hasConf)
    {
        lock (_queueLock)
        {
            _pending.Enqueue(new Msg { hasId = false, id = null, xz = worldXZ, conf = conf, hasConf = hasConf });
        }
    }

    private void EnqueueWithId(string id, Vector3 worldXZ, float conf, bool hasConf)
    {
        if (string.IsNullOrWhiteSpace(id)) return;
        lock (_queueLock)
        {
            _pending.Enqueue(new Msg { hasId = true, id = id.Trim(), xz = worldXZ, conf = conf, hasConf = hasConf });
        }
    }

    private float GroundY()
    {
        return autoGroundSnap ? (cubeScale.y * 0.5f) : yHeight;
    }

    private Vector3 MakeWorldPos(Vector3 xz)
    {
        return new Vector3(xz.x, GroundY(), xz.z);
    }

    private void DrainQueue()
    {
        Queue<Msg> local = null;
        lock (_queueLock)
        {
            if (_pending.Count > 0)
            {
                local = new Queue<Msg>(_pending);
                _pending.Clear();
            }
        }
        if (local == null) return;

        while (local.Count > 0)
        {
            Msg m = local.Dequeue();

            if (m.hasConf && m.conf < minConfidence)
            {
                continue;
            }

            Vector3 worldPos = MakeWorldPos(m.xz);

            if (reuseSingleCube)
            {
                ApplySingle(worldPos);
            }
            else
            {
                string id = m.hasId ? m.id : "UNKNOWN";
                ApplyMulti(id, worldPos);
            }
        }
    }

    private void ApplySingle(Vector3 worldPos)
    {
        if (!float.IsNaN(_lastPosSingle.x))
        {
            float d = Vector3.Distance(_lastPosSingle, worldPos);
            if (d < minMoveEps)
            {
                _singleLastSeenTime = Time.time;
                return;
            }
        }

        if (_singleCube == null)
        {
            _singleCube = CreateCube(worldPos);
            _singleCube.name = "YOLO_Single";
        }

        if (!smoothMove)
            _singleCube.transform.position = worldPos;

        _singleTargetPos = worldPos;
        _singleLastSeenTime = Time.time;
        _lastPosSingle = worldPos;
    }

    private void ApplyMulti(string id, Vector3 worldPos)
    {
        if (!_items.TryGetValue(id, out var it) || it.go == null)
        {
            var go = CreateCube(worldPos);
            go.name = $"YOLO_{id}";

            it = new TrackItem
            {
                go = go,
                targetPos = worldPos,
                lastSeenTime = Time.time,
                lastAppliedPos = worldPos
            };
            _items[id] = it;
            return;
        }

        float dist = Vector3.Distance(it.lastAppliedPos, worldPos);
        if (dist < minMoveEps)
        {
            it.lastSeenTime = Time.time;
            return;
        }

        if (!smoothMove)
            it.go.transform.position = worldPos;

        it.targetPos = worldPos;
        it.lastSeenTime = Time.time;
        it.lastAppliedPos = worldPos;
    }

    private void CleanupExpired()
    {
        float now = Time.time;

        if (reuseSingleCube && _singleCube != null)
        {
            if (now - _singleLastSeenTime > ttlSeconds)
            {
                Destroy(_singleCube);
                _singleCube = null;
                _singleLastSeenTime = -999f;
                _lastPosSingle = new Vector3(float.NaN, float.NaN, float.NaN);
            }
            return;
        }

        if (!reuseSingleCube)
        {
            List<string> toRemove = null;
            foreach (var kv in _items)
            {
                var id = kv.Key;
                var it = kv.Value;
                if (it.go == null)
                {
                    (toRemove ??= new List<string>()).Add(id);
                    continue;
                }

                if (now - it.lastSeenTime > ttlSeconds)
                {
                    Destroy(it.go);
                    (toRemove ??= new List<string>()).Add(id);
                }
            }

            if (toRemove != null)
            {
                foreach (var id in toRemove) _items.Remove(id);
            }
        }
    }

    private GameObject CreateCube(Vector3 pos)
    {
        GameObject cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
        cube.transform.localScale = cubeScale;
        cube.transform.position = pos;
        return cube;
    }

    private void StartUdp()
    {
        try
        {
            _udp = new UdpClient(listenPort);
            _udp.Client.ReceiveBufferSize = 1 << 20;

            _running = true;
            _rxThread = new Thread(RxLoop) { IsBackground = true };
            _rxThread.Start();

            Debug.Log($"[UDP] Listening on 0.0.0.0:{listenPort}");
        }
        catch (Exception e)
        {
            Debug.LogError($"[UDP] bind failed: {e.Message}");
            StopUdp();
        }
    }

    private void StopUdp()
    {
        _running = false;

        try { _udp?.Close(); } catch { }
        _udp = null;

        try
        {
            if (_rxThread != null && _rxThread.IsAlive)
                _rxThread.Join(200);
        }
        catch { }

        _rxThread = null;
    }

    private void RxLoop()
    {
        IPEndPoint ep = new IPEndPoint(IPAddress.Any, 0);

        while (_running)
        {
            try
            {
                byte[] data = _udp.Receive(ref ep);
                string msg = Encoding.UTF8.GetString(data).Trim();

                // 지원 포맷:
                // 1) "id x z conf"   (권장)
                // 2) "id x z"        (호환)
                // 3) "x z"           (호환, single로 처리)

                if (TryParseIdXZConf(msg, out string id, out float x, out float z, out float conf))
                {
                    if (conf >= minConfidence)
                        EnqueueWithId(id, new Vector3(x, 0f, z), conf, true);
                    else
                        Debug.Log($"[YOLO] ignored low conf={conf:F2} id={id}");
                }
                else if (TryParseIdXZ(msg, out id, out x, out z))
                {
                    EnqueueWithId(id, new Vector3(x, 0f, z), 0f, false);
                }
                else if (TryParseXZ(msg, out x, out z))
                {
                    EnqueueSingle(new Vector3(x, 0f, z), 0f, false);
                }
                else
                {
                    Debug.LogWarning($"[UDP] parse fail: '{msg}'");
                }
            }
            catch
            {
                // Close 중 예외는 무시
            }
        }
    }

    private bool TryParseXZ(string msg, out float x, out float z)
    {
        x = 0f; z = 0f;
        if (string.IsNullOrWhiteSpace(msg)) return false;

        msg = msg.Replace(",", " ");
        string[] parts = msg.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 2) return false;

        return float.TryParse(parts[0], out x) && float.TryParse(parts[1], out z);
    }

    private bool TryParseIdXZ(string msg, out string id, out float x, out float z)
    {
        id = null; x = 0f; z = 0f;
        if (string.IsNullOrWhiteSpace(msg)) return false;

        msg = msg.Replace(",", " ");
        string[] parts = msg.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 3) return false;

        id = parts[0];
        return float.TryParse(parts[1], out x) &&
               float.TryParse(parts[2], out z);
    }

    private bool TryParseIdXZConf(string msg, out string id, out float x, out float z, out float conf)
    {
        id = null; x = 0f; z = 0f; conf = 0f;
        if (string.IsNullOrWhiteSpace(msg)) return false;

        msg = msg.Replace(",", " ");
        string[] parts = msg.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 4) return false;

        id = parts[0];
        return float.TryParse(parts[1], out x) &&
               float.TryParse(parts[2], out z) &&
               float.TryParse(parts[3], out conf);
    }
}