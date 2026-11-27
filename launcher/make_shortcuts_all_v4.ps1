# MK2 전체 — 바탕화면 바로가기 「MK2 전체 켜기」 가 v4(mk2_all_start_v4.ps1 — v3 에서 수집 나이가 음수로 나오던 것을 고침)를 열게 한다 (2026-11-26).
#   같은 이름의 바로가기가 있으면 대상만 v4 로 다시 적는다. 기존 「MK2 엣지」 · 「MK2 엣지 상태 확인」 바로가기는 그대로 둔다.
# 실행: 일반 PowerShell 에서  powershell -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\make_shortcuts_all_v4.ps1

$ps   = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$desk = [Environment]::GetFolderPath('Desktop')
$ws   = New-Object -ComObject WScript.Shell

$path = Join-Path $desk 'MK2 전체 켜기.lnk'
$lnk = $ws.CreateShortcut($path)
$lnk.TargetPath = $ps
$lnk.Arguments = '-NoExit -NoProfile -ExecutionPolicy Bypass -File "C:\mk2_edge\launcher\mk2_all_start_v4.ps1"'
$lnk.WorkingDirectory = 'C:\mk2_edge'
$lnk.Description = 'MK2 전체 - 엣지 스택 + 노트북 서버를 켜고, 이 창 하나에서 상태를 보며 30초마다 자동 저장'
$lnk.Save()
"만듦(v4): $path"
