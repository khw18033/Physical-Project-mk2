@echo off
chcp 65001 >nul
rem ============================================================================
rem  SAR 드론 — 노트북 ↔ 처리 서버 SSH 터널 (Windows 10/11 기본 OpenSSH)
rem    -R 서버 127.0.0.1:18766 → 노트북 데이터 서버(8766)  : 서버가 끝난 패스를 가져간다
rem    -L 노트북 127.0.0.1:8767 → 서버 데이터 서버(8768)   : 화면이 서버에서 만든 영상을 본다
rem  먼저 sar-laptop.bat 를 켠다. 핫스팟(LTE)이 끊겨도 5 초마다 다시 붙는다. 창을 닫으면 끈다.
rem  처음 한 번: 서버 비밀번호 대신 키로 — ssh-keygen 후 공개키를 서버 ~/.ssh/authorized_keys 에 넣는다.
rem ============================================================================

rem ---- 현장값 (여기만 고친다) ----------------------------------------------------
set SERVER=사용자@서버주소
set LOCAL_DATA=8766
set REMOTE_IN=18766
set REMOTE_DATA=8768
set LOCAL_VIEW=8767
rem ------------------------------------------------------------------------------

echo 터널 — 화면 「연결 관리 → 드론 데이터 서버」를 http://127.0.0.1:%LOCAL_VIEW% 로 두면 서버 영상을 본다
:loop
ssh -N -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R %REMOTE_IN%:127.0.0.1:%LOCAL_DATA% -L %LOCAL_VIEW%:127.0.0.1:%REMOTE_DATA% %SERVER%
echo [터널] 끊김 — 5 초 뒤 다시
timeout /t 5 /nobreak >nul
goto loop
