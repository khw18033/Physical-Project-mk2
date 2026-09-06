using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

/*
===============================================================================
ArUcoUDPReceiver.cs
-------------------------------------------------------------------------------
GO1 디지털 트윈을 위한 ArUco 마커 기반 위치 동기화 수신기

[개요]
이 스크립트는 Python(OpenCV + ArUco) 측에서 UDP로 전송한
마커 위치 JSON 데이터를 수신하여 Unity 월드 좌표로 변환한 뒤,
GO1 디지털 트윈(Go1WASDLegacyDrive 또는 Transform)에 적용한다.

즉,
현실 → ArUco 마커 추정 → UDP → Unity → GO1 디지털 트윈 이동
의 흐름을 담당하는 네트워크 수신 모듈이다.

-------------------------------------------------------------------------------
[데이터 흐름 구조]

Python(OpenCV ArUco)
        ↓ UDP (JSON)
Unity ArUcoUDPReceiver
        ↓
좌표 변환 (scale / invert / offset / Y lock)
        ↓
Go1WASDLegacyDrive.SetMarkerWorldPose()
        ↓
Unity 디지털 트윈 이동

-------------------------------------------------------------------------------
[수신 JSON 형식 예시]

{
    "camera": "go1_bottom",
    "timestamp": 1700000000.123,
    "markers": [
        { "id": 0, "x": 0.12, "y": 0.00, "z": 1.25, "cam": "go1_bottom" }
    ]
}

-------------------------------------------------------------------------------
[주요 기능]

1. UDP 비동기 수신 (백그라운드 Thread)
2. 특정 카메라 필터링 (useCameraFilter)
3. 특정 마커 ID만 추적 (targetMarkerId)
4. 좌표 변환 옵션
   - posScale : 단위 스케일 조정
   - invertX / invertZ : 좌표 반전
   - worldOffset : Unity 월드 오프셋
   - lockY / fixedY : Y축 고정
5. 위치 스무딩 (지터 완화)
6. Go1WASDLegacyDrive로 전달 (우선 적용)
   → 없으면 Transform 직접 이동

-------------------------------------------------------------------------------
[사용 목적]

- GO1 현실 위치를 Unity 디지털 트윈과 동기화
- Sim-to-Real 오차 보정 실험
- 마커 기반 절대 위치 정렬
- 카메라 기반 위치 추정 검증

-------------------------------------------------------------------------------
[주의사항]

- UDP 포트 중복 사용 시 bind 실패 발생
- JSON 형식이 정확해야 파싱 가능
- Unity 좌표계와 카메라 좌표계 방향 차이 주의
- ArUco 추정 노이즈가 있을 경우 smoothing 권장

-------------------------------------------------------------------------------
Author: choBottle
Project: GO1 Digital Twin & Marker Synchronization
===============================================================================
*/

public class ArUcoUDPReceiver : MonoBehaviour
{
    Thread receiveThread;
    UdpClient client;
    public int port = 5008;
    private string latestJsonData = "";
    private readonly object jsonLock = new object();
    private string lastUdpRaw = "";
    private volatile bool udpArrived = false;

    [Header("Move Target")]
    public Transform go1Root;                
    public Go1WASDLegacyDrive go1Driver;      
    public int targetMarkerId = 0;

    [Header("Source Filter")]
    public bool useCameraFilter = true;
    public string onlyCamera = "go1_bottom";

    [Header("Mapping")]
    public float posScale = 1.0f;
    public Vector3 worldOffset = Vector3.zero;
    public bool lockY = true;
    public float fixedY = 0.0f;
    public bool invertX = false;
    public bool invertZ = false;

    [Header("Smoothing")]
    public bool smooth = false;
    public float posLerp = 15f;
    private bool hasPrev;
    private Vector3 smPos;

    [Header("Debug")]
    public bool debugLog = true;
    public float debugInterval = 0.2f;
    private float nextDebugTime = 0f;

    [System.Serializable]
    public class Marker
    {
        public int id;
        public float x;
        public float y;
        public float z;
        public string cam;
    }

    [System.Serializable]
    public class ArucoPacket
    {
        public string camera;
        public double timestamp;
        public Marker[] markers;
    }

    void Start()
    {
        if (debugLog) Debug.Log("[ArUco] Receiver started on port " + port);

        receiveThread = new Thread(ReceiveData);
        receiveThread.IsBackground = true;
        receiveThread.Start();
    }

    private void ReceiveData()
    {
        try
        {
            client = new UdpClient(port);
        }
        catch (System.Exception e)
        {
            lock (jsonLock)
            {
                lastUdpRaw = "[ArUco] UDP bind failed: " + e.Message;
                udpArrived = true;
            }
            return;
        }

        while (true)
        {
            try
            {
                IPEndPoint anyIP = new IPEndPoint(IPAddress.Any, 0);
                byte[] data = client.Receive(ref anyIP);
                string text = Encoding.UTF8.GetString(data);

                lock (jsonLock)
                {
                    latestJsonData = text;
                    lastUdpRaw = text;
                    udpArrived = true;
                }
            }
            catch (System.Exception e)
            {
                lock (jsonLock)
                {
                    lastUdpRaw = "[ArUco] UDP recv error: " + e.Message;
                    udpArrived = true;
                }
            }
        }
    }

    void Update()
    {
        if (debugLog && udpArrived && Time.time >= nextDebugTime)
        {
            string msg;
            lock (jsonLock)
            {
                msg = lastUdpRaw;
                udpArrived = false;
            }
            Debug.Log("[ArUco] UDP received(raw): " + msg);
            nextDebugTime = Time.time + debugInterval;
        }

        string json = null;

        lock (jsonLock)
        {
            if (!string.IsNullOrEmpty(latestJsonData))
            {
                json = latestJsonData;
                latestJsonData = "";
            }
        }

        if (string.IsNullOrEmpty(json))
            return;

        ArucoPacket packet;
        try
        {
            packet = JsonUtility.FromJson<ArucoPacket>(json);
        }
        catch
        {
            Debug.LogWarning("[ArUco] JSON Parse Fail: " + json);
            return;
        }

        if (packet == null) return;

        if (debugLog) Debug.Log("[ArUco] Camera: " + packet.camera);

        if (useCameraFilter)
        {
            if (string.IsNullOrEmpty(packet.camera)) return;

            if (!packet.camera.Equals(onlyCamera))
            {
                if (debugLog) Debug.Log("[ArUco] Ignored camera: " + packet.camera);
                return;
            }
        }

        if (packet.markers == null || packet.markers.Length == 0)
        {
            if (debugLog) Debug.Log("[ArUco] No markers in packet");
            return;
        }

        Marker m = null;
        for (int i = 0; i < packet.markers.Length; i++)
        {
            if (packet.markers[i].id == targetMarkerId)
            {
                m = packet.markers[i];
                break;
            }
        }

        if (m == null)
        {
            if (debugLog) Debug.Log("[ArUco] Target marker not found: " + targetMarkerId);
            return;
        }

        if (debugLog)
            Debug.Log($"[ArUco] Marker Found id={m.id} raw=({m.x:F3},{m.y:F3},{m.z:F3})");

        float cx = m.x * posScale;
        float cy = m.y * posScale;
        float cz = m.z * posScale;

        if (invertX) cx = -cx;
        if (invertZ) cz = -cz;

        Vector3 targetPos = new Vector3(cx, cy, cz) + worldOffset;
        if (lockY) targetPos.y = fixedY;

        if (smooth)
        {
            if (!hasPrev) { smPos = targetPos; hasPrev = true; }
            float a = 1f - Mathf.Exp(-posLerp * Time.deltaTime);
            smPos = Vector3.Lerp(smPos, targetPos, a);
            targetPos = smPos;
        }

        if (debugLog)
            Debug.Log($"[ArUco] Final World Pos: {targetPos}");

        if (go1Driver != null)
        {
            go1Driver.SetMarkerWorldPose(targetPos);
            if (debugLog) Debug.Log("[ArUco] Sent to Go1 Driver");
        }
        else
        {
            if (go1Root != null)
            {
                go1Root.position = targetPos;
                if (debugLog) Debug.Log("[ArUco] Direct Transform Move (fallback)");
            }
            else
            {
                Debug.LogWarning("[ArUco] No go1Driver / go1Root assigned!");
            }
        }
    }

    void OnApplicationQuit()
    {
        try
        {
            if (receiveThread != null) receiveThread.Abort();
        }
        catch { }

        try
        {
            if (client != null) client.Close();
        }
        catch { }
    }
}