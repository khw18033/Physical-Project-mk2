using UnityEngine;
using System;
using System.IO;
using System.Net;
using System.Threading;

public class MJPEGMeshReceiver : MonoBehaviour
{
    [Header("Server Settings")]
    public string streamUrl = "http://210.110.250.33:5001/stream/go1_front";

    [Header("Mesh Target")]
    public Renderer targetRenderer;
    public string texturePropertyName = "_BaseMap"; 
    public bool autoStart = true;

    private Texture2D texture;
    private Thread workerThread;
    private bool isRunning = false;

    private byte[] receivedData;
    private bool newDataAvailable = false;
    private readonly object lockObject = new object();

    void Start()
    {
        if (targetRenderer == null)
            targetRenderer = GetComponent<Renderer>();

        texture = new Texture2D(2, 2, TextureFormat.RGB24, false);

        if (targetRenderer != null)
        {
            targetRenderer.material.SetTexture(texturePropertyName, texture);

            // Built-in Unlit/Texture 계열이면 _MainTex일 수도 있어서 같이 넣어둠
            targetRenderer.material.SetTexture("_MainTex", texture);
        }

        if (autoStart)
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

    public void StopStream()
    {
        isRunning = false;

        if (workerThread != null && workerThread.IsAlive)
        {
            workerThread.Join(200);
        }

        workerThread = null;
    }

    private void ReadMJPEGStream()
    {
        try
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(streamUrl);
            request.Method = "GET";

            using (WebResponse response = request.GetResponse())
            using (Stream stream = response.GetResponseStream())
            {
                byte[] buffer = new byte[1024 * 1024];
                int totalBytes = 0;

                while (isRunning)
                {
                    int bytesRead = stream.Read(buffer, totalBytes, buffer.Length - totalBytes);
                    if (bytesRead <= 0) break;

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
            }
        }
        catch (Exception e)
        {
            Debug.LogError("[MJPEGMeshReceiver] Error: " + e.Message);
            isRunning = false;
        }
    }

    void Update()
    {
        if (!newDataAvailable) return;

        byte[] dataToProcess = null;

        lock (lockObject)
        {
            dataToProcess = receivedData;
            newDataAvailable = false;
        }

        if (dataToProcess != null && texture != null)
        {
            texture.LoadImage(dataToProcess);
        }
    }

    void OnDestroy()
    {
        StopStream();
    }
}