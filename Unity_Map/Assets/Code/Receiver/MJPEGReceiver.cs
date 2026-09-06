using UnityEngine;
using UnityEngine.UI;
using System.Net;
using System.IO;
using System.Threading;
using System;

/*
===============================================================================
MJPEGReceiver.cs
-------------------------------------------------------------------------------
HTTP MJPEG 스트림(연속 JPEG) 수신 → RawImage에 실시간 표시하는 수신기

- streamUrl (예: http://IP:PORT/stream/go1_front)로 HttpWebRequest GET 접속
- 백그라운드 Thread에서 바이트 스트림을 계속 읽음
- 버퍼에서 JPEG 프레임 경계(SOI=0xFFD8, EOI=0xFFD9)를 찾아
  "한 장의 JPEG" 단위로 잘라낸 뒤 receivedData에 저장
- Unity 메인 스레드(Update)에서 Texture2D.LoadImage()로 텍스처 갱신
- 갱신된 텍스처를 RawImage(targetDisplay)에 연결해 화면에 출력

-------------------------------------------------------------------------------
[사용 방법]

1) Canvas 안에 RawImage 생성
2) RawImage 오브젝트에 이 스크립트 부착
3) targetDisplay가 비어있으면 자동으로 자기 RawImage를 GetComponent로 사용
4) streamUrl에 MJPEG 서버 주소 설정
5) Play 하면 Start()에서 StartStream() 실행 → 자동 재생

-------------------------------------------------------------------------------
[프레임 추출 방식]

MJPEG는 "multipart로 JPEG가 연속 전송"되는 형태가 많음.
이 스크립트는 HTTP multipart boundary를 파싱하지 않고,
바이트 스트림에서 JPEG 시그니처로 프레임을 찾는다.

- SOI(Start of Image)  : 0xFF 0xD8
- EOI(End of Image)    : 0xFF 0xD9

버퍼에 누적해서 읽다가:
1) SOI 위치(startIdx) 찾기
2) startIdx 이후에서 EOI 위치(endIdx) 찾기
3) [startIdx, endIdx) 구간을 복사 → imageBytes (= JPEG 1장)
4) 남은 바이트는 버퍼 앞으로 당겨서 다음 프레임 탐색 계속

-------------------------------------------------------------------------------
[스레드/동기화]

- ReadMJPEGStream(): 백그라운드 스레드에서 네트워크 I/O + 프레임 분리 수행
- Update(): 메인 스레드에서만 Texture2D.LoadImage 수행 (Unity API 안전)
- lockObject로 receivedData / newDataAvailable 접근을 보호

-------------------------------------------------------------------------------
[주의사항]

1) Thread.Abort()는 권장되지 않음(에디터/플랫폼에 따라 문제 가능)
   - 더 안전한 방식: isRunning=false 후 Join()으로 종료 대기, stream/response 닫기

2) 버퍼(1MB) 초과에 가까워지면 totalBytes를 0으로 리셋함
   - 네트워크 지연/프레임 크기 증가 시 프레임 손실 가능
   - 필요하면 버퍼 크기 조정 또는 boundary 기반 파싱으로 개선 가능

3) texture.LoadImage는 매 프레임 CPU 부하가 있을 수 있음
   - 해상도/프레임레이트가 높으면 VR에서 성능 저하 가능
   - 필요 시 프레임 스킵(예: 15fps 제한)이나 별도 디코더 사용 고려

4) https/인증/헤더가 필요한 스트림이면 request 설정 추가 필요

-------------------------------------------------------------------------------
[확장 아이디어]

- 연결 끊김 자동 재접속(reconnect)
- FPS 제한(프레임 드랍/스킵) 옵션
- multipart boundary 파싱 방식으로 더 안정적으로 프레임 분리
- 텍스처 해상도 고정/재사용 최적화
- VR에서 Canvas 렌더링/레이어 설정과 함께 사용

===============================================================================
*/

public class MJPEGReceiver : MonoBehaviour
{
    [Header("Server Settings")]
    public string streamUrl = "http://210.110.250.33:5001/stream/go1_front"; 
    
    [Header("UI Target")]
    public RawImage targetDisplay; 

    private Texture2D texture;
    private bool isRunning = false;
    private Thread workerThread;
    
    private byte[] receivedData;
    private bool newDataAvailable = false;
    private object lockObject = new object();

    void Start()
    {
        if (targetDisplay == null)
        {
            targetDisplay = GetComponent<RawImage>();
        }

        texture = new Texture2D(2, 2);
        targetDisplay.texture = texture;

        StartStream();
    }

    public void StartStream()
    {
        if (isRunning) return;
        isRunning = true;
        
        workerThread = new Thread(ReadMJPEGStream);
        workerThread.IsBackground = true;
        workerThread.Start();
    }

    private void ReadMJPEGStream()
    {
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(streamUrl);
        request.Method = "GET";

        try
        {
            WebResponse response = request.GetResponse();
            Stream stream = response.GetResponseStream();
            
            byte[] buffer = new byte[1024 * 1024]; 
            int totalBytes = 0;
            
            while (isRunning)
            {
                int bytesRead = stream.Read(buffer, totalBytes, buffer.Length - totalBytes);
                if (bytesRead == 0) break;
                
                totalBytes += bytesRead;

                int startIdx = -1;
                int endIdx = -1;

                for (int i = 0; i < totalBytes - 1; i++)
                {
                    if (buffer[i] == 0xFF && buffer[i + 1] == 0xD8)
                    {
                        startIdx = i;
                        break;
                    }
                }

                if (startIdx != -1)
                {
                    for (int i = startIdx; i < totalBytes - 1; i++)
                    {
                        if (buffer[i] == 0xFF && buffer[i + 1] == 0xD9)
                        {
                            endIdx = i + 2;
                            break;
                        }
                    }
                }

                if (startIdx != -1 && endIdx != -1)
                {
                    int imageSize = endIdx - startIdx;
                    byte[] imageBytes = new byte[imageSize];
                    Array.Copy(buffer, startIdx, imageBytes, 0, imageSize);

                    lock (lockObject)
                    {
                        receivedData = imageBytes;
                        newDataAvailable = true;
                    }

                    int remaining = totalBytes - endIdx;
                    Array.Copy(buffer, endIdx, buffer, 0, remaining);
                    totalBytes = remaining;
                }
                
                if (totalBytes >= buffer.Length - 1024)
                {
                    totalBytes = 0; 
                }
            }
            response.Close();
        }
        catch (Exception e)
        {
            Debug.LogError($"[MJPEG] Error: {e.Message}");
            isRunning = false;
        }
    }

    void Update()
    {
        if (newDataAvailable)
        {
            byte[] dataToProcess = null;

            lock (lockObject)
            {
                dataToProcess = receivedData;
                newDataAvailable = false;
            }

            if (dataToProcess != null)
            {
                texture.LoadImage(dataToProcess); 
            }
        }
    }

    void OnDestroy()
    {
        isRunning = false;
        if (workerThread != null && workerThread.IsAlive)
        {
            workerThread.Abort();
        }
    }
}
