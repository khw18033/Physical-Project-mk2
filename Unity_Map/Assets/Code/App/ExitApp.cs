using UnityEngine;

/*
===============================================================================
ExitApp.cs
-------------------------------------------------------------------------------
게임/애플리케이션을 종료하는 간단한 유틸리티 스크립트

[개요]
UI 버튼(OnClick 등)에서 호출하여
실행 중인 애플리케이션을 종료한다.

Unity Editor에서 실행 중일 경우에는
Editor의 Play Mode를 종료하고,
빌드된 애플리케이션에서는 Application.Quit()을 호출한다.

-------------------------------------------------------------------------------
[동작 방식]

Quit()
  - UNITY_EDITOR 정의되어 있을 경우:
      UnityEditor.EditorApplication.isPlaying = false;
      → 에디터 Play 모드 종료

  - 빌드 환경(PC/Android/Quest 등)에서는:
      Application.Quit();
      → 실제 앱 종료

-------------------------------------------------------------------------------
[왜 분기 처리가 필요한가?]

Application.Quit()은
Unity Editor 안에서는 동작하지 않는다.
따라서 에디터 테스트 중에도 버튼으로
"종료" 동작을 재현하기 위해 조건부 컴파일을 사용한다.

-------------------------------------------------------------------------------
[사용 방법]

1) 종료 버튼(GameObject)에 이 스크립트 추가
2) Button → OnClick()에 ExitApp.Quit() 연결

-------------------------------------------------------------------------------
[플랫폼 참고]

- PC Standalone: 정상 종료
- Android / Quest: 앱이 백그라운드로 이동 후 종료
- WebGL: Application.Quit() 동작하지 않음 (브라우저 정책상 제한)

===============================================================================
*/

public class ExitApp : MonoBehaviour
{
    public void Quit()
    {
#if UNITY_EDITOR
        UnityEditor.EditorApplication.isPlaying = false;
#else
        Application.Quit();
#endif
    }
}
