@echo off
rem 360 카메라 -> 로컬 검출 -> Unity(UDP 127.0.0.1:5010). 종료는 Ctrl+C.
rem 추가 옵션은 그대로 뒤에 붙인다.  예) run_anchor360_local.bat --u 50
chcp 65001 >nul
set PYTHONUTF8=1
"D:\capstone\venv\Scripts\python.exe" "%~dp0anchor360_local.py" --show --quiet %*
pause
