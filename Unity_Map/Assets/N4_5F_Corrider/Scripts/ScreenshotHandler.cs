using UnityEngine;

public class ScreenshotHandler : MonoBehaviour
{
    void Update()
    {
        // P 키를 누르면 스크린샷 찍기
        if (Input.GetKeyDown(KeyCode.P))
        {
            // 파일 이름: Screenshot_날짜_시간.png
            string fileName = "Screenshot_" + System.DateTime.Now.ToString("yyyyMMdd_HHmmss") + ".png";
            
            // 1은 현재 해상도, 2를 넣으면 2배 해상도(고화질)로 찍힘
            ScreenCapture.CaptureScreenshot(fileName, 1);
            
            Debug.Log("스크린샷 저장됨: " + fileName);
        }
    }
}