@echo off
chcp 65001 >nul
rem ============================================================================
rem  SAR 드론 — 노트북(지상국) 한 번에 켜기 (Windows)
rem    1) RTK 베이스(MicoAir M-RTK, USB) 보정을 Pi 로 보낸다       — BASE_COM 을 비우면 건너뜀
rem    2) Pi 의 끝난 패스를 가져와 SAR 영상을 자동으로 만든다(미러) — 화면 「비행 데이터」가 여기 붙는다
rem  처음 한 번은 파이썬 환경을 만든다(몇 분). 창 두 개가 뜬다 — 끄려면 각 창을 닫는다.
rem ============================================================================

rem ---- 현장값 (여기만 고친다) ----------------------------------------------------
set PI=192.168.137.2
set BASE_COM=COM12
set BASE_BAUD=115200
set RTCM_PORT=14660
set PORT=8765
set MIRROR_DIR=%USERPROFILE%\sar_mirror
set TILE_DIR=%USERPROFILE%\sar_tiles
set RADAR_JSON=%~dp0radar.json
set ADAPTER=sar_image.adapters:fmcw_dechirped_npz
set FORMER=
set FOCUSER=
rem -------------------------------------------------------------------------------

set HERE=%~dp0
set DRONE=%HERE%..\..
set VENV=%HERE%.venv

if not exist "%VENV%\Scripts\python.exe" (
  echo [준비] 파이썬 환경을 만든다 — 처음 한 번, 몇 분 걸린다
  py -3 -m venv "%VENV%" || (echo 파이썬 3.10 이상을 설치한다: https://www.python.org/downloads/ & pause & exit /b 1)
  "%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip
  "%VENV%\Scripts\python.exe" -m pip install -q -e "%DRONE%[base,image]" || (echo 설치 실패 & pause & exit /b 1)
)

if not exist "%RADAR_JSON%" (
  echo [안내] %RADAR_JSON% 이 없다 — 화면 「SAR 패스 → 안테나」에서 radar.json 을 내려받아 이 폴더에 둔다.
  echo        지금은 예시 값으로 시작한다.
  copy "%DRONE%\sar_image\example_radar.json" "%RADAR_JSON%" >nul
)

set EXTRA=
if not "%FORMER%"=="" set EXTRA=%EXTRA% --former %FORMER%
if not "%FOCUSER%"=="" set EXTRA=%EXTRA% --focuser %FOCUSER%
set REFL=
if exist "%HERE%reflectors.csv" set REFL=--reflectors "%HERE%reflectors.csv"

if not "%BASE_COM%"=="" (
  start "RTK 베이스 -> Pi" cmd /k ""%VENV%\Scripts\python.exe" -m rtk_relay.base_sender --port %BASE_COM% --baud %BASE_BAUD% --to %PI%:%RTCM_PORT%"
)
start "SAR 미러 · 자동 영상" cmd /k ""%VENV%\Scripts\python.exe" -m sar_data --flights "%MIRROR_DIR%" --mirror http://%PI%:8765 --bind 127.0.0.1 --port %PORT% --radar-json "%RADAR_JSON%" --adapter %ADAPTER% --auto-image --tile-cache "%TILE_DIR%" %REFL% %EXTRA%"

echo.
echo 켰다. 화면의 「연결 관리 → 드론 데이터 서버」를 http://127.0.0.1:%PORT% 로 둔다.
echo   RTK 베이스 : %BASE_COM% -^> %PI%:%RTCM_PORT%
echo   미러 폴더  : %MIRROR_DIR%
echo   지도 캐시  : %TILE_DIR%  (현장용 위성 주소 http://127.0.0.1:%PORT%/tiles/satellite/{z}/{x}/{y}.png)
timeout /t 5 >nul
