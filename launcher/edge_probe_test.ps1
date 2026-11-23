# MK2 엣지 — 관측 사슬 시험: 가짜 말단 관측 1분 → Collector → Prometheus · 파일 (2026-11-23)
# 파이가 관측을 보내지 않는 동안(T2 꺼짐) Collector · Prometheus 가 제대로 받는지 보는 유일한 방법이다.
# BE 의 가짜 B층 발신자(tests\edge_probe_publisher.py)가 5초마다 12번(1분) 이 노트북 Collector(localhost:4317)로 보내고,
# 끝나면 20초 뒤 상태 확인(edge_status.ps1)을 돌린다.
# ⚠ 가짜 시계열(service.name=hw-sensor-node · entity wl-edge-001 · node edge-pc)이 엣지 Prometheus 에 보존 기간(15일) 동안 남는다.

. (Join-Path $PSScriptRoot 'edge_common.ps1')

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'MK2 엣지 - 관측 사슬 시험 (가짜 발신 1분)'
New-Item -ItemType Directory -Force $LOGS | Out-Null

if (-not (Test-Listening 4317)) {
  Write-Host "Collector(4317)가 꺼져 있다 - 런처에서 Collector 와 Prometheus 를 먼저 켠다."
  return
}

$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $BE_DIR
$log = Join-Path $LOGS ("probe_{0}.log" -f (Get-Date -Format yyMMdd_HHmm))
Write-Host "== 가짜 발신 시작 - 로그 $log"
cmd /c "$PY_PROBE tests\edge_probe_publisher.py --interval 5 --rounds 12 2>&1" | Tee-Object -FilePath $log

Write-Host ""
Write-Host "== 발신 끝 - Prometheus 가 한 번 더 긁도록 20초 기다린 뒤 상태 확인을 돌린다"
Start-Sleep -Seconds 20
& (Join-Path $PSScriptRoot 'edge_status.ps1')
