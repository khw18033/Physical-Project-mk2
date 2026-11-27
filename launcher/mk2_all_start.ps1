# MK2 전체 켜기 — 엣지 스택 넷 + 노트북 서버(WSL 의 PostgreSQL · 임무 이력 서버)를 한 번에 켜고,
#                 이 창 하나에서 데이터가 잘 오는지 30초마다 새로 보여 준다 (2026-11-25)
#   바로가기 「MK2 전체 켜기」: powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\mk2_all_start.ps1
#
# - 기존 파일은 고치지 않는다. 엣지 구성요소는 런처(edge_launcher.ps1) 「켜기」 와 같은 순서 · 같은 방법(run_component.ps1 창)으로 켠다.
#   구성요소 창 · WSL 창은 작게(최소화) 띄운다 — 볼 것은 이 창 하나다. 상태 항목은 edge_status.ps1(1 ~ 6)과 같은 것을 본다.
# - 노트북 서버: WSL 이 켜지면 PostgreSQL · 임무 이력 서버가 저절로 뜬다(systemd enable). 그래서 WSL 을 깨우고,
#   임무 이력 로그를 따라 보여 주는 창 하나를 띄워 둔다 — 이 창이 떠 있는 동안 WSL 이 꺼지지 않는다.
# - 이미 떠 있는 것은 건너뛴다 → 이 창을 닫은 뒤 다시 더블클릭하면 상태 화면만 다시 연다.
# - DS · VZ 는 켜지 않는다(각자의 바로가기). 끄기는 「MK2 엣지」 런처의 「끄기」. 임무 이력 서버는 WSL 과 같이 늘 돈다.
# - 상태는 화면에만 새로 그린다. 파일은 처음 한 번 + S 키를 누를 때 C:\mk2_edge\logs\mk2_all_status_<날짜_시각>.txt 로 남긴다.
param([switch]$WslWindow)

. (Join-Path $PSScriptRoot 'edge_common.ps1')
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DISTRO    = 'Ubuntu-26.04'
$MH_URL    = 'http://100.125.104.23:8850'
$WSL_TITLE = 'MK2 노트북 서버 - WSL 을 켜 두는 창 (임무 이력 로그 · 닫지 않는다)'
$REFRESH_S = 30

# ---- -WslWindow 로 불리면: WSL 을 켜 두는 창이 된다
if ($WslWindow) {
  $Host.UI.RawUI.WindowTitle = $WSL_TITLE
  Write-Host ("== {0} - {1}" -f $WSL_TITLE, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
  Write-Host "이 창이 떠 있는 동안 WSL($DISTRO)이 켜져 있다. 임무 이력 서버 · PostgreSQL 의 로그를 따라 보여 준다."
  & wsl.exe -d $DISTRO --exec bash -c "journalctl -u mission-history -u postgresql@18-main -n 20 -f; exec sleep infinity"
  return
}

$Host.UI.RawUI.WindowTitle = 'MK2 전체 - 켜기 · 상태'
try {
  $raw = $Host.UI.RawUI
  $buf = $raw.BufferSize
  if ($buf.Width -lt 150) { $buf.Width = 150; $raw.BufferSize = $buf }
  $win = $raw.WindowSize
  $max = $raw.MaxPhysicalWindowSize
  $win.Width = [Math]::Min(150, $max.Width)
  $win.Height = [Math]::Min(55, $max.Height)
  $raw.WindowSize = $win
}
catch { }

$RUN = Join-Path $PSScriptRoot 'run_component.ps1'
New-Item -ItemType Directory -Force $LOGS | Out-Null

function Open-PsWindow([string]$File, [string[]]$Extra) {
  $argList = @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $File)
  if ($Extra) { $argList += $Extra }
  Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -WindowStyle Minimized
}

function Get-MhHealth {
  try { Invoke-RestMethod -TimeoutSec 4 -Uri "$MH_URL/api/v1/health" } catch { $null }
}

# Prometheus 질의 하나 — 결과 줄들(없거나 응답이 없으면 빈 배열)
function PQ([string]$q) {
  try { @((Invoke-RestMethod -TimeoutSec 5 -Uri ('http://127.0.0.1:9090/api/v1/query?query=' + [uri]::EscapeDataString($q))).data.result) }
  catch { @() }
}

# 시계열 이름표에서 job · instance · __name__ 을 뺀 것 — 장치가 무엇인지
function Get-SeriesName($metric) {
  $parts = @($metric.PSObject.Properties | Where-Object { $_.Name -notin @('__name__', 'job', 'instance') } |
      ForEach-Object { '{0}={1}' -f $_.Name, $_.Value })
  if ($parts.Count -eq 0) { '(이름표 없음)' } else { $parts -join ',' }
}

function Mark([bool]$ok) { if ($ok) { '[OK]' } else { '[!!]' } }

# ---- 상태 한 번 보기 — 화면에 그릴 줄들을 돌려준다(아무것도 켜거나 바꾸지 않는다 · WSL 이 꺼져 있으면 깨우지 않는다)
function Get-AllStatus {
  $D = New-Object System.Collections.Generic.List[string]

  # 노트북 서버 — WSL · 서비스 · 임무 이력
  $env:WSL_UTF8 = '1'
  $wl = @(wsl.exe -l -v 2>&1 | ForEach-Object { "$_" } | Where-Object { $_.Trim() -ne '' })
  $wslUp = @($wl | Where-Object { $_ -match [regex]::Escape($DISTRO) -and $_ -match 'Running' }).Count -gt 0
  $svc = @()
  if ($wslUp) { $svc = @(wsl.exe -d $DISTRO --exec systemctl is-active postgresql@18-main mission-history mission-history-backup.timer 2>&1 | ForEach-Object { "$_".Trim() }) }
  $svcOk = @($svc | Where-Object { $_ -eq 'active' }).Count
  $h = Get-MhHealth
  $runs = @()
  if ($h) { try { $runs = @((Invoke-RestMethod -TimeoutSec 10 -Uri "$MH_URL/api/v1/runs").runs | Where-Object { $_.date -ne '000101' }) } catch { } }

  # 엣지 스택 넷
  $compUp = 0
  $compLines = @()
  foreach ($k in $COMPONENTS.Keys) {
    $c = $COMPONENTS[$k]
    if (Test-Listening $c.Port) { $compUp++; $compLines += ('  떠 있음 :{0,-5} {1}' -f $c.Port, $c.Label) }
    else { $compLines += ('  꺼짐    :{0,-5} {1}' -f $c.Port, $c.Label) }
  }

  # 파이 브리지 · 업무 토픽(5초)
  $bridge = @()
  $topics = @()
  $brokerUp = Test-Listening 1883
  if ($brokerUp) {
    $bridge = @(& $MOSQ_SUB -h 127.0.0.1 -p 1883 -t '$SYS/broker/connection/#' -v -W 3 2>$null | ForEach-Object { "$_" })
    $topics = @(& $MOSQ_SUB -h 127.0.0.1 -p 1883 -t '+/+/+/state' -t '+/+/+/status' -t '+/+/+/heartbeat' -F '%t' -W 5 2>$null | ForEach-Object { "$_" })
  }
  $bState = @($bridge | Where-Object { $_ -match '/state ' })
  $bOn = @($bState | Where-Object { $_ -match ' 1$' }).Count
  $tg = @($topics | Group-Object | Sort-Object Count -Descending)

  # Collector(OpenTelemetry)
  $col = @()
  $colUp = $false
  try {
    $col = @((Get-HttpText 'http://127.0.0.1:8888/metrics') -split "`n" | ForEach-Object { $_.Trim() } |
        Where-Object { $_ -match '^otelcol_(receiver_accepted|receiver_refused|exporter_sent|exporter_send_failed)' })
    $colUp = $true
  }
  catch { }
  $acc = 0.0
  foreach ($l in $col) { if ($l -match '^otelcol_receiver_accepted\S*\s+([0-9.eE+-]+)$') { $acc += [double]$Matches[1] } }

  # 엣지 Prometheus
  $promUp = $false
  try { $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 -Uri 'http://127.0.0.1:9090/-/healthy'; $promUp = $true } catch { }
  $targets = @()
  if ($promUp) { try { $targets = @((Invoke-RestMethod -TimeoutSec 5 -Uri 'http://127.0.0.1:9090/api/v1/targets').data.activeTargets) } catch { } }
  $tUp = @($targets | Where-Object { $_.health -eq 'up' }).Count
  $ent = @(); $avail = @(); $cnt = @(); $names = @()
  if ($promUp) {
    $ent   = PQ 'hw_entity_up'
    $avail = PQ 'hw_availability_state'
    $cnt   = PQ 'count_over_time(hw_entity_up[10m])'
    $names = PQ 'count by (__name__) ({__name__=~"hw_.*|system_.*"})'
  }
  $online = @($ent | Where-Object { $_.value[1] -eq '1' }).Count
  $otelNames = @($names | Where-Object { $_.metric.__name__ -match '^(system_|hw_publish_)' }).Count

  # ---- 요약
  $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  $D.Add(('==================== MK2 전체 상태 · {0} ({1}초마다 새로 봄) ====================' -f $now, $REFRESH_S))
  $D.Add('요약')
  $latest = if ($runs.Count -gt 0) { '{0} {1}' -f $runs[0].date, $runs[0].run } else { '-' }
  $mhText = if ($h) { '임무 이력 응답 · VZ 에 보이는 판 {0}개 · 맨 위 {1}' -f $runs.Count, $latest } else { '임무 이력 응답 없음' }
  $D.Add(('  {0} 노트북 서버   WSL {1} · 서비스 active {2}/3 · {3}' -f (Mark ($wslUp -and $svcOk -eq 3 -and $null -ne $h)), $(if ($wslUp) { 'Running' } else { '꺼짐' }), $svcOk, $mhText))
  $D.Add(('  {0} 엣지 스택     떠 있음 {1}/4 (브로커 · Collector · Prometheus · 가용성 판정기)' -f (Mark ($compUp -eq 4)), $compUp))
  $D.Add(('  {0} 파이 -> 엣지  브리지 붙음 {1}/{2} · 업무 토픽 5초 동안 {3}건(토픽 {4}개)   <- 파이가 꺼져 있으면 0' -f (Mark ($bOn -gt 0 -and $topics.Count -gt 0)), $bOn, $bState.Count, $topics.Count, $tg.Count))
  $D.Add(('  {0} 관측(OTel)    Collector 받은 것 {1} · Prometheus 의 OTel 지표 이름 {2}개   <- 말단이 관측을 보내야 는다' -f (Mark ($colUp -and $acc -gt 0)), $acc, $otelNames))
  $D.Add(('  {0} Prometheus    대상 up {1}/{2} · 장치 판정 online {3}/{4}' -f (Mark ($promUp -and $targets.Count -gt 0 -and $tUp -eq $targets.Count)), $tUp, $targets.Count, $online, $ent.Count))

  # ---- 자세히
  $D.Add('')
  $D.Add('== A 노트북 서버 - WSL · 서비스(postgresql@18-main · mission-history · 백업 타이머) · 임무 이력')
  foreach ($l in $wl) { $D.Add('  ' + $l) }
  if ($wslUp) { $D.Add('  서비스: ' + ($svc -join ' · ')) }
  else { $D.Add('  WSL 이 꺼져 있다 - 이 바로가기를 다시 더블클릭한다') }
  if ($h) {
    $D.Add(('  health: ok={0} · 판 {1}개(검사 판 000101 포함) · 서버 시각 {2}' -f $h.ok, $h.runCount, $h.serverTime))
    $D.Add('  최근 판 셋 (임무를 하나 끝내면 맨 위에 그 판이 온다):')
    foreach ($r in @($runs | Select-Object -First 3)) {
      $kind = if ($r.mission -and $r.mission.recordKind) { $r.mission.recordKind } else { 'mission' }
      $D.Add(('    {0} {1} {2}' -f $r.date, $r.run, $kind))
    }
  }
  else { $D.Add(('  {0} 응답 없음 - WSL 이 꺼졌거나 임무 이력 서버가 안 떠 있다' -f $MH_URL)) }

  $D.Add('== B 엣지 스택 - 듣는 포트로 판정')
  foreach ($l in $compLines) { $D.Add($l) }

  $D.Add('== C 파이 브리지 (줄 끝 1 = 붙음 · 0 = 끊김) · 업무 토픽 5초 건수')
  if (-not $brokerUp) { $D.Add('  브로커(1883)가 꺼져 있어 볼 수 없다') }
  else {
    if ($bState.Count -gt 0) { foreach ($l in $bState) { $D.Add('  ' + $l) } } else { $D.Add('  (브리지 상태 줄 없음)') }
    if ($tg.Count -gt 0) { foreach ($g in $tg) { $D.Add(('  {0,6}  {1}' -f $g.Count, $g.Name)) } } else { $D.Add('  (5초 동안 들어온 업무 토픽 없음)') }
  }

  $D.Add('== D Collector (OpenTelemetry) - 켠 뒤 누적')
  if (-not $colUp) { $D.Add('  8888 응답 없음 - Collector 가 꺼져 있다') }
  elseif ($col.Count -eq 0) { $D.Add('  (아직 받은 것 없음 - 말단이 관측을 안 보내면 0 이다)') }
  else { foreach ($l in $col) { $D.Add('  ' + $l) } }

  $D.Add('== E 엣지 Prometheus - 대상 · 장치 판정 (0 online · 1 offline_planned · 2 offline_fault · 3 stale) · 10분 동안 쌓인 수(15초마다 → 장치마다 40 근처면 끊김 없음)')
  if (-not $promUp) { $D.Add('  9090 응답 없음 - Prometheus 가 꺼져 있다') }
  else {
    foreach ($t in $targets) { $D.Add(('  대상 {0,-18} {1,-6} {2} {3}' -f $t.labels.job, $t.health, $t.scrapeUrl, $t.lastError)) }
    if ($ent.Count -eq 0) { $D.Add('  (장치 판정 없음 - 파이가 꺼져 있거나 아직 등록 · 심박이 안 왔다)') }
    foreach ($e in $ent) {
      $id = Get-SeriesName $e.metric
      $st = @($avail | Where-Object { (Get-SeriesName $_.metric) -eq $id } | Select-Object -First 1)
      $ct = @($cnt | Where-Object { (Get-SeriesName $_.metric) -eq $id } | Select-Object -First 1)
      $stv = if ($st.Count -gt 0) { $st[0].value[1] } else { '-' }
      $ctv = if ($ct.Count -gt 0) { $ct[0].value[1] } else { '-' }
      $D.Add(('  장치 {0}  up={1} · 판정={2} · 10분 동안 {3}' -f $id, $e.value[1], $stv, $ctv))
    }
    $D.Add('  --- 쌓인 지표 이름 · 시계열 수 (hw_* · system_*)')
    if ($names.Count -eq 0) { $D.Add('  (없음)') }
    foreach ($n in $names) { $D.Add(('  {0,-44} {1}' -f $n.metric.__name__, $n.value[1])) }
  }

  $D.Add('== F 엣지에 쌓이는 파일')
  foreach ($f in @(Get-ChildItem $LOGS -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(otel_logs\.jsonl|otel_traces\.jsonl|mosquitto\.log)$' } | Sort-Object Name)) {
    $D.Add(('  {0,-18} {1,12:N0} B  {2:HH:mm:ss}' -f $f.Name, $f.Length, $f.LastWriteTime))
  }
  $sum = (Get-ChildItem $PROM_DATA -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
  if (-not $sum) { $sum = 0 }
  $D.Add(('  Prometheus 저장(prom_data) {0:N1} MB' -f ($sum / 1MB)))
  return $D
}

function Save-Status($lines) {
  $file = Join-Path $LOGS ('mk2_all_status_{0}.txt' -f (Get-Date -Format yyMMdd_HHmmss))
  $lines | Out-File -FilePath $file -Encoding utf8
  return $file
}

# ---- 켜기
Write-Host ("# MK2 전체 켜기 - {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

Write-Host "== 1 노트북 서버 - WSL 을 켜 두는 창 (작게 띄움)"
$open = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*mk2_all_start.ps1*' -and $_.CommandLine -like '*-WslWindow*' })
if ($open.Count -gt 0) { Write-Host "  이미 떠 있음" }
else { Open-PsWindow $PSCommandPath @('-WslWindow'); Write-Host "  켬" }

Write-Host "== 2 엣지 스택 (런처 「켜기」 와 같은 순서 · 구성요소마다 창 하나 · 작게 띄움)"
foreach ($k in $COMPONENTS.Keys) {
  $c = $COMPONENTS[$k]
  if (Test-Listening $c.Port) { Write-Host ("  {0}: 이미 떠 있음" -f $c.Label); continue }
  if ($k -eq 'availability') {
    $waited = 0
    while (-not (Test-Listening 1883) -and $waited -lt 10000) { Start-Sleep -Milliseconds 500; $waited += 500 }
    if (-not (Test-Listening 1883)) { Write-Host ("  {0}: 브로커(1883)가 안 떠 있어 켜지 않았다 - 작업 표시줄의 브로커 창을 본다" -f $c.Label); continue }
  }
  Open-PsWindow $RUN @('-Name', $k)
  Write-Host ("  {0}: 켬" -f $c.Label)
  Start-Sleep -Milliseconds 800
}

Write-Host "== 3 임무 이력 서버가 답할 때까지 (최대 60초)"
$h0 = $null
for ($i = 0; $i -lt 30; $i++) {
  $h0 = Get-MhHealth
  if ($h0 -and $h0.ok) { break }
  Start-Sleep -Seconds 2
}
if ($h0 -and $h0.ok) { Write-Host ("  답함 (판 {0}개 - 검사 판 포함)" -f $h0.runCount) }
else { Write-Host "  60초 안에 답이 없다 - 아래 상태 화면의 A 와 작업 표시줄의 「WSL 을 켜 두는 창」 을 본다" }

Write-Host "== 4 20초 뒤 상태 화면으로 바뀐다 (Prometheus 가 한 번 긁을 시간)"
Start-Sleep -Seconds 20

# ---- 상태 화면 — 30초마다 새로 그린다
$lastSave = $null
$first = $true
while ($true) {
  Write-Host ''
  Write-Host '... 새로 보는 중 (10초쯤)'
  $lines = Get-AllStatus
  if ($first) { $lastSave = Save-Status $lines; $first = $false }
  Clear-Host
  foreach ($l in $lines) { Write-Host $l }
  Write-Host ''
  Write-Host ('남긴 파일: {0}' -f $lastSave)
  Write-Host ('[R] 지금 다시 보기 · [S] 지금 화면을 파일로 남기기 · [Q] 그만 보기(켜 둔 것은 그대로 돈다) — {0}초 뒤 저절로 다시 본다' -f $REFRESH_S)
  $act = ''
  for ($i = 0; $i -lt $REFRESH_S -and $act -eq ''; $i++) {
    Start-Sleep -Seconds 1
    while ([Console]::KeyAvailable) {
      $key = [Console]::ReadKey($true)
      switch ($key.Key) {
        'R' { $act = 'r' }
        'S' { $act = 's' }
        'Q' { $act = 'q' }
      }
    }
  }
  if ($act -eq 's') { $lastSave = Save-Status $lines; Write-Host ('남김: {0}' -f $lastSave); Start-Sleep -Seconds 2 }
  if ($act -eq 'q') { break }
}
Write-Host '상태 화면을 멈췄다. 켜 둔 것은 그대로 돈다 - 끄기는 「MK2 엣지」 런처의 「끄기」. 이 창은 닫아도 된다.'
