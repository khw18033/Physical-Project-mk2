# MK2 엣지 — 바탕화면 바로가기 둘을 만든다 (한 번만 돌린다 · 2026-11-23)
#   「MK2 엣지」          → 런처(켜기 · 끄기 · 상태 · 시험 · 로그 · 매뉴얼)
#   「MK2 엣지 상태 확인」 → 상태 확인 창(읽기만)
# 실행: 일반 PowerShell 에서  powershell -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\make_shortcuts.ps1
# 같은 이름의 바로가기가 있으면 덮어쓴다(대상만 다시 적힌다).

$ps   = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$desk = [Environment]::GetFolderPath('Desktop')
$ws   = New-Object -ComObject WScript.Shell

$items = @(
  @{ Name = 'MK2 엣지.lnk'
     Args = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\mk2_edge\launcher\edge_launcher.ps1"'
     Desc = 'MK2 엣지 - 켜기 · 끄기 · 상태 · 시험' },
  @{ Name = 'MK2 엣지 상태 확인.lnk'
     Args = '-NoExit -NoProfile -ExecutionPolicy Bypass -File "C:\mk2_edge\launcher\edge_status.ps1"'
     Desc = 'MK2 엣지 - 상태 확인(읽기만)' }
)

foreach ($it in $items) {
  $path = Join-Path $desk $it.Name
  $lnk = $ws.CreateShortcut($path)
  $lnk.TargetPath = $ps
  $lnk.Arguments = $it.Args
  $lnk.WorkingDirectory = 'C:\mk2_edge'
  $lnk.Description = $it.Desc
  $lnk.Save()
  "만듦: $path"
}
