# MK2 엣지 — 상태 확인 (읽기만 · 2026-11-23)
# 무엇이 떠 있고, 파이 브리지가 붙었고, 무엇이 쌓이고 있는지 한 번에 본다. 아무것도 켜거나 바꾸지 않는다.
# 결과는 화면과 C:\mk2_edge\logs\edge_status_<날짜_시각>.txt 에 같이 남는다.

. (Join-Path $PSScriptRoot 'edge_common.ps1')

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'MK2 엣지 - 상태 확인'
New-Item -ItemType Directory -Force $LOGS | Out-Null
$OUT = Join-Path $LOGS ("edge_status_{0}.txt" -f (Get-Date -Format yyMMdd_HHmm))

& {
  "# MK2 엣지 상태 확인 - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

  "== 1 구성요소 - 듣는 포트로 판정"
  foreach ($k in $COMPONENTS.Keys) {
    $c = $COMPONENTS[$k]
    $pids = Get-ListenPids $c.Port
    if ($pids.Count -gt 0) {
      $p = Get-Process -Id $pids[0] -ErrorAction SilentlyContinue
      "떠 있음  :{0,-5} {1}  ({2})" -f $c.Port, $c.Label, $p.Path
    }
    else {
      "꺼짐    :{0,-5} {1}" -f $c.Port, $c.Label
    }
  }

  "== 2 파이 브리지 - 연결 상태 (줄 끝 1 = 붙음 · 0 = 끊김)"
  if (Test-Listening 1883) {
    & $MOSQ_SUB -h 127.0.0.1 -p 1883 -t '$SYS/broker/connection/#' -v -W 3 2>$null
    "--- 지금 이 노트북 브로커로 들어오는 업무 토픽 (5초 · 토픽별 건수 — 파이가 꺼져 있으면 비어 있다)"
    $topics = @(& $MOSQ_SUB -h 127.0.0.1 -p 1883 -t '+/+/+/state' -t '+/+/+/status' -t '+/+/+/heartbeat' -F '%t' -W 5 2>$null)
    if ($topics.Count -gt 0) { $topics | Group-Object | Sort-Object Count -Descending | Format-Table Count, Name -AutoSize }
    else { "(들어온 것 없음)" }
  }
  else {
    "브로커(1883)가 꺼져 있어 볼 수 없다"
  }

  "== 3 Collector - 받은 것 · 보낸 것 · 거부 (Collector 를 켠 뒤 누적)"
  try {
    $lines = @((Get-HttpText 'http://127.0.0.1:8888/metrics') -split "`n" |
        Where-Object { $_ -match '^otelcol_(receiver_accepted|receiver_refused|exporter_sent|exporter_send_failed)' })
    if ($lines.Count -gt 0) { $lines } else { "(아직 받은 것 없음 - 말단이 관측을 안 보내면 0 이다)" }
  }
  catch { "8888 응답 없음 - Collector 가 꺼져 있다" }

  "== 4 엣지 Prometheus"
  try { Invoke-RestMethod -TimeoutSec 5 -Uri 'http://127.0.0.1:9090/-/healthy' } catch { "9090 응답 없음 - Prometheus 가 꺼져 있다" }
  try {
    (Invoke-RestMethod -TimeoutSec 5 -Uri 'http://127.0.0.1:9090/api/v1/targets').data.activeTargets |
      ForEach-Object { "{0,-18} {1,-6} {2}  {3}" -f $_.labels.job, $_.health, $_.scrapeUrl, $_.lastError }
    "--- 쌓인 지표 이름 · 시계열 수 (hw_* · system_*)"
    $res = @((Invoke-RestMethod -TimeoutSec 5 -Uri 'http://127.0.0.1:9090/api/v1/query' `
          -Body @{ query = 'count by (__name__) ({__name__=~"hw_.*|system_.*"})' }).data.result)
    if ($res.Count -gt 0) { $res | ForEach-Object { "{0,-44} {1}" -f $_.metric.__name__, $_.value[1] } }
    else { "(없음)" }
  }
  catch { }

  "== 5 가용성 판정기 - 장치별 판정 (hw_availability_state: 0 online · 1 offline_planned · 2 offline_fault · 3 stale)"
  try {
    $dev = @((Get-HttpText 'http://127.0.0.1:9105/metrics') -split "`n" |
        Where-Object { $_ -match '^hw_(entity_up|availability_state|heartbeat_age_seconds)\{' })
    if ($dev.Count -gt 0) { $dev } else { "(장치 줄 없음 - 파이가 꺼져 있거나 아직 등록 · 심박이 안 왔다)" }
  }
  catch { "9105 응답 없음 - 가용성 판정기가 꺼져 있다" }

  "== 6 엣지에 쌓이는 파일"
  Get-ChildItem $LOGS -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(otel_|mosquitto\.log|quarantine|unsent)' } |
    Sort-Object Name | Format-Table Name, Length, LastWriteTime -AutoSize
  $mb = (Get-ChildItem $PROM_DATA -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1MB
  "Prometheus 저장(prom_data) 크기: {0:N1} MB" -f $mb

  "# 끝 $(Get-Date -Format 'HH:mm:ss')"
} *>&1 | Tee-Object -FilePath $OUT

""
"남김: $OUT"
