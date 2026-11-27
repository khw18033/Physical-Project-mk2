# MK2 전체 — 바탕화면 바로가기 「MK2 전체 켜기」 를 더한다 (한 번만 돌린다 · 2026-11-25).
#   기존 「MK2 엣지」 · 「MK2 엣지 상태 확인」 바로가기는 그대로 둔다.
# 실행: 일반 PowerShell 에서  powershell -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\make_shortcuts_all.ps1
# 같은 이름의 바로가기가 있으면 덮어쓴다(대상만 다시 적힌다).

$ps   = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$desk = [Environment]::GetFolderPath('Desktop')
$ws   = New-Object -ComObject WScript.Shell

$path = Join-Path $desk 'MK2 전체 켜기.lnk'
$lnk = $ws.CreateShortcut($path)
$lnk.TargetPath = $ps
$lnk.Arguments = '-NoExit -NoProfile -ExecutionPolicy Bypass -File "C:\mk2_edge\launcher\mk2_all_start.ps1"'
$lnk.WorkingDirectory = 'C:\mk2_edge'
$lnk.Description = 'MK2 전체 - 엣지 스택 + 노트북 서버를 켜고, 이 창 하나에서 상태를 본다'
$lnk.Save()
"만듦: $path"
