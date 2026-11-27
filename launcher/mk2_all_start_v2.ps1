# MK2 전체 켜기 v2 — 엣지 스택 넷 + 노트북 서버(WSL 의 PostgreSQL · 임무 이력 서버)를 한 번에 켜고,
#                    이 창 하나에서 30초마다 상태를 새로 보여 주며 **볼 때마다 자동으로 파일에 덧붙인다** (2026-11-25)
#   바로가기 「MK2 전체 켜기」: powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\mk2_all_start_v2.ps1
#
# v1(mk2_all_start.ps1)과 다른 점: ① S 키(손으로 저장)를 없애고 30초마다 자동 저장 ② 저장 자리를 별도 폴더로
#   C:\mk2_edge\logs\mk2_status\  — 구동(이 바로가기를 켤 때)마다 새 파일 둘을 만들어 거기에 덧붙인다:
#     mk2_status_<구동 시각>.txt    사람이 읽는 화면 그대로(볼 때마다 한 덩어리)
#     mk2_status_<구동 시각>.jsonl  같은 내용을 값으로(볼 때마다 JSON 한 줄) — 시각화가 읽는 용도
#     mk2_status_latest.json        가장 최근 한 번(볼 때마다 덮어씀)
#   ③ 파일 시각에 날짜를 붙였다(v1 은 시각만 나왔다).
# - 기존 파일은 고치지 않는다. 엣지 구성요소는 런처(edge_launcher.ps1) 「켜기」 와 같은 순서 · 같은 방법(run_component.ps1 창)으로 켠다.
#   구성요소 창 · WSL 창은 작게(최소화) 띄운다 — 볼 것은 이 창 하나다.
# - 노트북 서버: WSL 이 켜지면 PostgreSQL · 임무 이력 서버가 저절로 뜬다(systemd enable). 그래서 WSL 을 깨우고,
#   임무 이력 로그를 따라 보여 주는 창 하나를 띄워 둔다 — 이 창이 떠 있는 동안 WSL 이 꺼지지 않는다.
# - 이미 떠 있는 것은 건너뛴다 → 이 창을 닫은 뒤 다시 더블클릭하면 상태 화면만 다시 연다(새 구동 파일이 생긴다).
# - 끄기도 이 창에서: 상태 화면에서 Q → Y 를 누르면 엣지 스택 넷(런처 「끄기」 와 같은 방법)과 WSL 을 켜 두는 창을 끄고,
#   끈 뒤의 상태를 한 번 더 저장한다. 창을 그냥 닫으면 켜 둔 것은 그대로 돈다.
#   임무 이력 서버 · PostgreSQL 은 끄지 않는다 — WSL 안의 systemd 서비스라 끄려면 sudo 가 필요하고, WSL 은 DS 와 같이 쓴다.
# - DS · VZ 는 켜지도 끄지도 않는다(각자의 바로가기).
param([switch]$WslWindow)

. (Join-Path $PSScriptRoot 'edge_common.ps1')
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DISTRO    = 'Ubuntu-26.04'
$MH_URL    = 'http://100.125.104.23:8850'
$WSL_TITLE = 'MK2 노트북 서버 - WSL 을 켜 두는 창 (임무 이력 로그 · 닫지 않는다)'
$REFRESH_S = 30
$SERVICES  = @('postgresql@18-main', 'mission-history', 'mission-history-backup.timer')

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
$RUN_ID     = Get-Date -Format yyMMdd_HHmmss
$STATUS_DIR = Join-Path $LOGS 'mk2_status'
$TXT        = Join-Path $STATUS_DIR "mk2_status_$RUN_ID.txt"
$JSONL      = Join-Path $STATUS_DIR "mk2_status_$RUN_ID.jsonl"
$LATEST     = Join-Path $STATUS_DIR 'mk2_status_latest.json'
$UTF8       = New-Object System.Text.UTF8Encoding($false)
New-Item -ItemType Directory -Force $STATUS_DIR | Out-Null

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

# ---- 상태 한 번 보기 — 화면 줄(Lines)과 같은 내용의 값(Data)을 돌려준다
#      아무것도 켜거나 바꾸지 않는다 · WSL 이 꺼져 있으면 깨우지 않는다
function Get-AllStatus {
  $D = New-Object System.Collections.Generic.List[string]
  $nowDate = Get-Date

  # 노트북 서버 — WSL · 서비스 · 임무 이력
  $env:WSL_UTF8 = '1'
  $wl = @(wsl.exe -l -v 2>&1 | ForEach-Object { "$_" } | Where-Object { $_.Trim() -ne '' })
  $wslUp = @($wl | Where-Object { $_ -match [regex]::Escape($DISTRO) -and $_ -match 'Running' }).Count -gt 0
  $svc = @()
  if ($wslUp) { $svc = @(wsl.exe -d $DISTRO --exec systemctl is-active @SERVICES 2>&1 | ForEach-Object { "$_".Trim() }) }
  $svcOk = @($svc | Where-Object { $_ -eq 'active' }).Count
  $svcObj = [ordered]@{}
  for ($i = 0; $i -lt $SERVICES.Count; $i++) { $svcObj[$SERVICES[$i]] = $(if ($i -lt $svc.Count) { $svc[$i] } else { $null }) }
  $h = Get-MhHealth
  $runs = @()
  if ($h) { try { $runs = @((Invoke-RestMethod -TimeoutSec 10 -Uri "$MH_URL/api/v1/runs").runs | Where-Object { $_.date -ne '000101' }) } catch { } }
  $latestRuns = @($runs | Select-Object -First 3 | ForEach-Object {
      $kind = if ($_.mission -and $_.mission.recordKind) { $_.mission.recordKind } else { 'mission' }
      [pscustomobject][ordered]@{ date = $_.date; run = $_.run; record_kind = $kind }
    })

  # 엣지 스택 넷
  $compUp = 0
  $compLines = @()
  $compData = @()
  foreach ($k in $COMPONENTS.Keys) {
    $c = $COMPONENTS[$k]
    $isUp = Test-Listening $c.Port
    if ($isUp) { $compUp++; $compLines += ('  떠 있음 :{0,-5} {1}' -f $c.Port, $c.Label) }
    else { $compLines += ('  꺼짐    :{0,-5} {1}' -f $c.Port, $c.Label) }
    $compData += [pscustomobject][ordered]@{ name = $k; label = $c.Label; port = $c.Port; up = $isUp }
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
  $bridgeData = @($bState | ForEach-Object {
      if ($_ -match '^\$SYS/broker/connection/(.+)/state (\d+)$') { [pscustomobject][ordered]@{ name = $Matches[1]; connected = [int]$Matches[2] } }
    })
  $tg = @($topics | Group-Object | Sort-Object Count -Descending)
  $topicData = @($tg | ForEach-Object { [pscustomobject][ordered]@{ topic = $_.Name; count = $_.Count } })

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
  $devLines = @()
  $devData = @()
  foreach ($e in $ent) {
    $id = Get-SeriesName $e.metric
    $st = @($avail | Where-Object { (Get-SeriesName $_.metric) -eq $id } | Select-Object -First 1)
    $ct = @($cnt | Where-Object { (Get-SeriesName $_.metric) -eq $id } | Select-Object -First 1)
    $stv = if ($st.Count -gt 0) { $st[0].value[1] } else { '-' }
    $ctv = if ($ct.Count -gt 0) { $ct[0].value[1] } else { '-' }
    $devLines += ('  장치 {0}  up={1} · 판정={2} · 10분 동안 {3}' -f $id, $e.value[1], $stv, $ctv)
    $dev = [ordered]@{}
    foreach ($p in $e.metric.PSObject.Properties) { if ($p.Name -notin @('__name__', 'job', 'instance')) { $dev[$p.Name] = $p.Value } }
    $dev['up'] = [double]$e.value[1]
    $dev['state'] = $(if ($st.Count -gt 0) { [double]$st[0].value[1] } else { $null })
    $dev['samples_10m'] = $(if ($ct.Count -gt 0) { [double]$ct[0].value[1] } else { $null })
    $devData += [pscustomobject]$dev
  }
  $targetData = @($targets | ForEach-Object { [pscustomobject][ordered]@{ job = $_.labels.job; health = $_.health; url = $_.scrapeUrl; last_error = $_.lastError } })
  $nameData = @($names | ForEach-Object { [pscustomobject][ordered]@{ name = $_.metric.__name__; series = [double]$_.value[1] } })

  # 파일
  $fileLines = @()
  $fileData = @()
  foreach ($f in @(Get-ChildItem $LOGS -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(otel_logs\.jsonl|otel_traces\.jsonl|mosquitto\.log)$' } | Sort-Object Name)) {
    $fileLines += ('  {0,-18} {1,12:N0} B  {2:yyyy-MM-dd HH:mm:ss}' -f $f.Name, $f.Length, $f.LastWriteTime)
    $fileData += [pscustomobject][ordered]@{ name = $f.Name; bytes = $f.Length; modified = $f.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:sszzz') }
  }
  $sum = (Get-ChildItem $PROM_DATA -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
  if (-not $sum) { $sum = 0 }

  # 판정(요약)
  $okLaptop = ($wslUp -and $svcOk -eq 3 -and $null -ne $h)
  $okEdge   = ($compUp -eq 4)
  $okPi     = ($bOn -gt 0 -and $topics.Count -gt 0)
  $okOtel   = ($colUp -and $acc -gt 0)
  $okProm   = ($promUp -and $targets.Count -gt 0 -and $tUp -eq $targets.Count)

  # ---- 화면 줄
  $D.Add(('==================== MK2 전체 상태 · {0:yyyy-MM-dd HH:mm:ss} ({1}초마다 새로 보고 자동 저장) ====================' -f $nowDate, $REFRESH_S))
  $D.Add('요약')
  $latest = if ($runs.Count -gt 0) { '{0} {1}' -f $runs[0].date, $runs[0].run } else { '-' }
  $mhText = if ($h) { '임무 이력 응답 · VZ 에 보이는 판 {0}개 · 맨 위 {1}' -f $runs.Count, $latest } else { '임무 이력 응답 없음' }
  $D.Add(('  {0} 노트북 서버   WSL {1} · 서비스 active {2}/3 · {3}' -f (Mark $okLaptop), $(if ($wslUp) { 'Running' } else { '꺼짐' }), $svcOk, $mhText))
  $D.Add(('  {0} 엣지 스택     떠 있음 {1}/4 (브로커 · Collector · Prometheus · 가용성 판정기)' -f (Mark $okEdge), $compUp))
  $D.Add(('  {0} 파이 -> 엣지  브리지 붙음 {1}/{2} · 업무 토픽 5초 동안 {3}건(토픽 {4}개)   <- 파이가 꺼져 있으면 0' -f (Mark $okPi), $bOn, $bState.Count, $topics.Count, $tg.Count))
  $D.Add(('  {0} 관측(OTel)    Collector 받은 것 {1} · Prometheus 의 OTel 지표 이름 {2}개   <- 말단이 관측을 보내야 는다(파이 무변경이면 0)' -f (Mark $okOtel), $acc, $otelNames))
  $D.Add(('  {0} Prometheus    대상 up {1}/{2} · 장치 판정 online {3}/{4}' -f (Mark $okProm), $tUp, $targets.Count, $online, $ent.Count))

  $D.Add('')
  $D.Add('== A 노트북 서버 - WSL · 서비스(postgresql@18-main · mission-history · 백업 타이머) · 임무 이력')
  foreach ($l in $wl) { $D.Add('  ' + $l) }
  if ($wslUp) { $D.Add('  서비스: ' + ($svc -join ' · ')) }
  else { $D.Add('  WSL 이 꺼져 있다 - 바탕화면 「MK2 전체 켜기」 를 다시 더블클릭한다') }
  if ($h) {
    $D.Add(('  health: ok={0} · 판 {1}개(검사 판 000101 포함) · 서버 시각 {2}' -f $h.ok, $h.runCount, $h.serverTime))
    $D.Add('  최근 판 셋 (임무를 하나 끝내면 맨 위에 그 판이 온다):')
    foreach ($r in $latestRuns) { $D.Add(('    {0} {1} {2}' -f $r.date, $r.run, $r.record_kind)) }
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
    foreach ($l in $devLines) { $D.Add($l) }
    $D.Add('  --- 쌓인 지표 이름 · 시계열 수 (hw_* · system_*)')
    if ($names.Count -eq 0) { $D.Add('  (없음)') }
    foreach ($n in $names) { $D.Add(('  {0,-44} {1}' -f $n.metric.__name__, $n.value[1])) }
  }

  $D.Add('== F 엣지에 쌓이는 파일')
  foreach ($l in $fileLines) { $D.Add($l) }
  $D.Add(('  Prometheus 저장(prom_data) {0:N1} MB' -f ($sum / 1MB)))

  # ---- 같은 내용의 값 (시각화가 읽는 JSON)
  $data = [ordered]@{
    time          = $nowDate.ToString('yyyy-MM-ddTHH:mm:sszzz')
    run_id        = $RUN_ID
    summary       = [ordered]@{ laptop_server = $okLaptop; edge_stack = $okEdge; pi_to_edge = $okPi; otel = $okOtel; prometheus = $okProm }
    laptop_server = [ordered]@{
      wsl_running     = $wslUp
      services        = $svcObj
      mission_history = [ordered]@{
        url              = $MH_URL
        ok               = ($null -ne $h)
        run_count_all    = $(if ($h) { $h.runCount } else { $null })
        run_count_listed = $runs.Count
        latest_runs      = $latestRuns
      }
    }
    edge_stack    = $compData
    pi_to_edge    = [ordered]@{ broker_up = $brokerUp; bridges = $bridgeData; topics_5s = $topicData; messages_5s = $topics.Count }
    otel          = [ordered]@{ collector_up = $colUp; accepted_total = $acc; lines = $col; otel_metric_names = $otelNames }
    prometheus    = [ordered]@{ up = $promUp; targets = $targetData; devices = $devData; metric_names = $nameData }
    files         = [ordered]@{ logs = $fileData; prom_data_mb = [Math]::Round($sum / 1MB, 1) }
  }
  return @{ Lines = $D; Data = $data }
}

function Save-Status($res) {
  [System.IO.File]::AppendAllText($TXT, (($res.Lines -join "`r`n") + "`r`n`r`n"), $UTF8)
  [System.IO.File]::AppendAllText($JSONL, ((ConvertTo-Json -InputObject $res.Data -Depth 8 -Compress) + "`n"), $UTF8)
  [System.IO.File]::WriteAllText($LATEST, (ConvertTo-Json -InputObject $res.Data -Depth 8), $UTF8)
}

# ---- 끄기 — 엣지 스택 넷(런처 「끄기」 와 같은 방법: 켠 순서의 반대로 강제 종료 · 구성요소 창도 닫음) + WSL 을 켜 두는 창
function Stop-All {
  Write-Host "== 끄기"
  $rev = @($COMPONENTS.Keys)
  [array]::Reverse($rev)
  foreach ($k in $rev) {
    $procs = @(Get-EdgeProcesses $k)
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    foreach ($w in @(Get-ComponentWindows $k)) { Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host ('  {0}: 끔({1})' -f $COMPONENTS[$k].Label, $procs.Count)
  }
  $wins = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -like '*mk2_all_start*' -and $_.CommandLine -like '*-WslWindow*' })
  foreach ($w in $wins) {
    foreach ($ch in @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $w.ProcessId) -ErrorAction SilentlyContinue)) {
      Stop-Process -Id $ch.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Write-Host ('  WSL 을 켜 두는 창: 닫음({0})' -f $wins.Count)
  Write-Host '  임무 이력 서버 · PostgreSQL: 끄지 않음 (WSL 안의 서비스 - WSL 이 켜져 있는 동안 돈다)'
  Start-Sleep -Seconds 2
}

# ---- 켜기
Write-Host ("# MK2 전체 켜기 v2 - {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host ("  이번 구동의 상태 파일: {0}  ·  {1}" -f $TXT, $JSONL)

Write-Host "== 1 노트북 서버 - WSL 을 켜 두는 창 (작게 띄움)"
$open = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*mk2_all_start*' -and $_.CommandLine -like '*-WslWindow*' })
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

# ---- 상태 화면 — 30초마다 새로 그리고, 그때마다 이번 구동 파일에 덧붙인다
$saved = 0
while ($true) {
  Write-Host ''
  Write-Host '... 새로 보는 중 (10초쯤)'
  $res = Get-AllStatus
  $saveMsg = ''
  try { Save-Status $res; $saved++; $saveMsg = ('자동 저장 {0}번째 · {1:HH:mm:ss}' -f $saved, (Get-Date)) }
  catch { $saveMsg = ('!! 저장 실패: {0}' -f $_.Exception.Message) }
  Clear-Host
  foreach ($l in $res.Lines) { Write-Host $l }
  Write-Host ''
  Write-Host $saveMsg
  Write-Host ('  화면 그대로: {0}' -f $TXT)
  Write-Host ('  값(JSON):    {0}  ·  최신 한 번: {1}' -f $JSONL, $LATEST)
  Write-Host ('[R] 지금 다시 보기 · [Q] 모두 끄기(Y 로 한 번 더 확인) — {0}초마다 저절로 다시 보고 위 파일에 덧붙인다 · 창을 그냥 닫으면 켜 둔 것은 그대로 돈다' -f $REFRESH_S)
  $act = ''
  for ($i = 0; $i -lt $REFRESH_S -and $act -eq ''; $i++) {
    Start-Sleep -Seconds 1
    while ([Console]::KeyAvailable) {
      $key = [Console]::ReadKey($true)
      switch ($key.Key) {
        'R' { $act = 'r' }
        'Q' { $act = 'q' }
      }
    }
  }
  if ($act -eq 'q') {
    Write-Host ''
    Write-Host '모두 끌까? 엣지 스택 넷 · WSL 을 켜 두는 창을 끈다 (임무 이력 서버 · DS · VZ 는 그대로)  [Y] 끈다 · 다른 키 = 돌아간다'
    while ([Console]::KeyAvailable) { $null = [Console]::ReadKey($true) }
    $ans = [Console]::ReadKey($true)
    if ($ans.Key -eq 'Y') { break }
  }
}
Stop-All
Write-Host '== 끈 뒤 상태 (한 번 더 저장)'
$res = Get-AllStatus
try { Save-Status $res; $saved++; Write-Host ('  저장 {0}번째: {1}' -f $saved, $TXT) } catch { Write-Host ('  !! 저장 실패: {0}' -f $_.Exception.Message) }
foreach ($l in @($res.Lines | Select-Object -First 8)) { Write-Host $l }
Write-Host ''
Write-Host '모두 껐다. 이 창은 닫아도 된다. 다시 켜려면 바탕화면 「MK2 전체 켜기」 를 더블클릭한다.'
