# MK2 전체 켜기 v3 — 엣지 스택 넷 + 노트북 서버(WSL 의 PostgreSQL · 임무 이력 서버)를 한 번에 켜고,
#                    이 창 하나에서 30초마다 상태를 새로 보여 주며 볼 때마다 자동으로 파일에 덧붙인다. 끄기도 이 창에서 (2026-11-26)
#   바로가기 「MK2 전체 켜기」: powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\mk2_all_start_v3.ps1
#
# 저장: C:\mk2_edge\logs\mk2_status\ — 구동(이 바로가기를 켤 때)마다 새 파일 둘에 덧붙이고, 최신 한 번은 덮어쓴다
#   mk2_status_<구동 시각>.txt    사람이 읽는 화면 그대로(볼 때마다 한 덩어리)
#   mk2_status_<구동 시각>.jsonl  같은 내용을 값으로(볼 때마다 JSON 한 줄) — 시각화가 읽는 용도 · 칸 설명: docs\노트북서버_261125\ 의 JSON 설명 md
#   mk2_status_latest.json        가장 최근 한 번
#
# v2(mk2_all_start_v2.ps1)와 다른 점 — 「시각화가 「잘 된다」 를 보여 줄 재료」 를 더하고, 시험에서 드러난 두 가지를 고쳤다:
#   ① JSON 에 schema_version(3) · refresh_s · sources(Prometheus 주소 · 쓸 질의 등)를 더함
#   ② summary 의 다섯 항목을 {ok, reason} 으로 — [!!] 인 사유를 한 줄로
#   ③ 마지막으로 들어온 시각: 장치마다 심박 나이(hw_heartbeat_age_seconds) · Prometheus 대상마다 마지막 수집 시각과 나이
#   ④ DB 가 쌓이는 증거: 판 수 · 그림 수 · 마지막 저장 시각 · DB 크기(WSL 의 psql — 읽기 계정 khw67) · 마지막 백업 폴더
#   ⑤ 업무 메시지를 1분당 건수로(5초 표본 × 12) · Collector 가 지난번 뒤로 받은 수
#   ⑥ 장치마다 정상 기준: 10분 동안 쌓인 수가 36 이상(15초 수집이면 40 — 90%) · 판정 이름(online 등) · 심박이 있는지
#   ⑦ 고침: 같은 브리지가 여러 줄로 겹치던 것 → 브리지마다 마지막 값 하나
#   ⑧ 고침: 보관(retained) 메시지가 업무 토픽 건수에 섞이던 것 → 따로 센다(지금 보낸 것이 아니다)
# - 기존 파일은 고치지 않는다. 엣지 구성요소는 런처(edge_launcher.ps1) 「켜기」 와 같은 순서 · 같은 방법(run_component.ps1 창)으로 켠다.
#   구성요소 창 · WSL 창은 작게(최소화) 띄운다 — 볼 것은 이 창 하나다.
# - 노트북 서버: WSL 이 켜지면 PostgreSQL · 임무 이력 서버가 저절로 뜬다(systemd enable). 그래서 WSL 을 깨우고,
#   임무 이력 로그를 따라 보여 주는 창 하나를 띄워 둔다 — 이 창이 떠 있는 동안 WSL 이 꺼지지 않는다.
# - 이미 떠 있는 것은 건너뛴다 → 이 창을 닫은 뒤 다시 더블클릭하면 상태 화면만 다시 연다(새 구동 파일이 생긴다).
# - 끄기: 상태 화면에서 Q → Y — 엣지 스택 넷과 WSL 을 켜 두는 창을 끄고, 끈 뒤의 상태를 한 번 더 저장한다. 창을 그냥 닫으면 켜 둔 것은 그대로 돈다.
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
$SCHEMA_VERSION   = 3
$SAMPLES_EXPECTED = 40    # 10분 ÷ 15초(obs\prometheus.yml scrape_interval)
$SAMPLES_OK       = 36    # 그 90% 이상이면 「끊김 없이 쌓임」
$STATE_NAMES = @{ 0 = 'online'; 1 = 'offline_planned'; 2 = 'offline_fault'; 3 = 'stale' }
$script:prevAcc = $null

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

# 시각 글자 → DateTimeOffset (Prometheus 는 소수점 아래 9자리까지 쓴다 — .NET 은 7자리까지만 읽는다)
function To-Dto($v) {
  if ($null -eq $v) { return $null }
  if ($v -is [datetime]) { return [DateTimeOffset]$v }
  try { return [DateTimeOffset]::Parse((([string]$v) -replace '(\.\d{7})\d+', '$1')) } catch { return $null }
}

function Get-Short([string]$bridge) { $bridge -replace '^edge-[^-]+-', '' }

# ---- 상태 한 번 보기 — 화면 줄(Lines)과 같은 내용의 값(Data)을 돌려준다
#      아무것도 켜거나 바꾸지 않는다 · WSL 이 꺼져 있으면 깨우지 않는다
function Get-AllStatus {
  $D = New-Object System.Collections.Generic.List[string]
  $nowDate = Get-Date
  $nowDto = [DateTimeOffset]$nowDate

  # ---------- 노트북 서버 — WSL · 서비스 · 임무 이력 · DB · 백업
  $env:WSL_UTF8 = '1'
  $wl = @(wsl.exe -l -v 2>&1 | ForEach-Object { "$_" } | Where-Object { $_.Trim() -ne '' })
  $wslUp = @($wl | Where-Object { $_ -match [regex]::Escape($DISTRO) -and $_ -match 'Running' }).Count -gt 0
  $svc = @()
  $dbRow = $null
  $lastBackup = $null
  if ($wslUp) {
    $svc = @(wsl.exe -d $DISTRO --exec systemctl is-active @SERVICES 2>&1 | ForEach-Object { "$_".Trim() })
    # DB — 읽기 계정 khw67(같은 기기 소켓 · 비밀번호 없음)로 숫자 넷: VZ 에 보이는 판 · 그 그림 행 · 마지막 저장(초) · DB 크기(바이트)
    $sql = "SELECT (SELECT count(*) FROM mission_runs WHERE mission_doc IS NOT NULL AND date <> '000101'), (SELECT count(*) FROM mission_run_images WHERE date <> '000101'), (SELECT extract(epoch FROM max(updated_at))::bigint FROM mission_runs WHERE date <> '000101'), pg_database_size(current_database())"
    $dbOut = @(wsl.exe -d $DISTRO --exec psql -X -d mk2 -tA -c $sql 2>&1 | ForEach-Object { "$_".Trim() } | Where-Object { $_ -ne '' })
    if ($dbOut.Count -gt 0 -and $dbOut[0] -match '^(\d+)\|(\d+)\|(\d*)\|(\d+)$') {
      $dbRow = [ordered]@{
        ok         = $true
        runs       = [int]$Matches[1]
        images     = [int]$Matches[2]
        last_saved = $(if ($Matches[3] -ne '') { [DateTimeOffset]::FromUnixTimeSeconds([long]$Matches[3]).ToLocalTime().ToString('yyyy-MM-ddTHH:mm:sszzz') } else { $null })
        size_mb    = [Math]::Round([double]$Matches[4] / 1MB, 1)
        error      = $null
      }
    }
    else { $dbRow = [ordered]@{ ok = $false; runs = $null; images = $null; last_saved = $null; size_mb = $null; error = ($dbOut -join ' ') } }
    $bk = @(wsl.exe -d $DISTRO --exec ls -1t /home/khw67/mission_history/backups 2>&1 | ForEach-Object { "$_".Trim() } | Where-Object { $_ -match '^(daily|manual)_\d{6}_\d{6}$' })
    if ($bk.Count -gt 0) { $lastBackup = $bk[0] }
  }
  else { $dbRow = [ordered]@{ ok = $false; runs = $null; images = $null; last_saved = $null; size_mb = $null; error = 'WSL 이 꺼져 있다' } }
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

  # ---------- 엣지 스택 넷
  $compUp = 0
  $compLines = @()
  $compData = @()
  $compDown = @()
  foreach ($k in $COMPONENTS.Keys) {
    $c = $COMPONENTS[$k]
    $isUp = Test-Listening $c.Port
    if ($isUp) { $compUp++; $compLines += ('  떠 있음 :{0,-5} {1}' -f $c.Port, $c.Label) }
    else { $compDown += $c.Label; $compLines += ('  꺼짐    :{0,-5} {1}' -f $c.Port, $c.Label) }
    $compData += [pscustomobject][ordered]@{ name = $k; label = $c.Label; port = $c.Port; up = $isUp }
  }

  # ---------- 파이 브리지(이름마다 마지막 값 하나) · 업무 메시지 5초(보관 메시지는 따로)
  $bridgeRaw = @()
  $msgRaw = @()
  $brokerUp = Test-Listening 1883
  if ($brokerUp) {
    $bridgeRaw = @(& $MOSQ_SUB -h 127.0.0.1 -p 1883 -t '$SYS/broker/connection/#' -v -W 3 2>$null | ForEach-Object { "$_" })
    $msgRaw = @(& $MOSQ_SUB -h 127.0.0.1 -p 1883 -t '+/+/+/state' -t '+/+/+/status' -t '+/+/+/heartbeat' -F '%r %t' -W 5 2>$null | ForEach-Object { "$_" })
  }
  $bridgeMap = [ordered]@{}
  foreach ($l in $bridgeRaw) { if ($l -match '^\$SYS/broker/connection/(.+)/state (\d+)$') { $bridgeMap[$Matches[1]] = [int]$Matches[2] } }
  $bTotal = $bridgeMap.Count
  $bOn = @($bridgeMap.Values | Where-Object { $_ -eq 1 }).Count
  $bridgeData = @($bridgeMap.Keys | ForEach-Object { [pscustomobject][ordered]@{ name = $_; short = (Get-Short $_); connected = $bridgeMap[$_] } })
  $live = @()
  $ret = @()
  $parsed = 0
  foreach ($l in $msgRaw) {
    if ($l -match '^([01]) (\S+)$') { $parsed++; if ($Matches[1] -eq '1') { $ret += $Matches[2] } else { $live += $Matches[2] } }
  }
  if ($parsed -eq 0 -and $msgRaw.Count -gt 0) { $live = $msgRaw }   # 보관 표시(%r)를 못 읽으면 전부 「지금 보낸 것」 으로 센다
  $tg = @($live | Group-Object | Sort-Object Count -Descending)
  $topicData = @($tg | ForEach-Object { [pscustomobject][ordered]@{ topic = $_.Name; count = $_.Count } })
  $retTopics = @($ret | Sort-Object -Unique)
  $perMin = $live.Count * 12

  # ---------- Collector(OpenTelemetry)
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
  $accDelta = $null
  if ($colUp) {
    if ($null -ne $script:prevAcc) { $accDelta = $acc - $script:prevAcc }
    $script:prevAcc = $acc
  }

  # ---------- 엣지 Prometheus
  $promUp = $false
  try { $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 -Uri 'http://127.0.0.1:9090/-/healthy'; $promUp = $true } catch { }
  $targets = @()
  if ($promUp) { try { $targets = @((Invoke-RestMethod -TimeoutSec 5 -Uri 'http://127.0.0.1:9090/api/v1/targets').data.activeTargets) } catch { } }
  $tUp = @($targets | Where-Object { $_.health -eq 'up' }).Count
  $ent = @(); $avail = @(); $cnt = @(); $names = @(); $hbAge = @()
  if ($promUp) {
    $ent   = PQ 'hw_entity_up'
    $avail = PQ 'hw_availability_state'
    $cnt   = PQ 'count_over_time(hw_entity_up[10m])'
    $hbAge = PQ 'hw_heartbeat_age_seconds'
    $names = PQ 'count by (__name__) ({__name__=~"hw_.*|system_.*"})'
  }
  $online = @($ent | Where-Object { $_.value[1] -eq '1' }).Count
  $otelNames = @($names | Where-Object { $_.metric.__name__ -match '^(system_|hw_publish_)' }).Count
  $targetLines = @()
  $targetData = @()
  foreach ($t in $targets) {
    $ls = To-Dto $t.lastScrape
    $age = if ($ls) { [Math]::Round(($nowDto - $ls).TotalSeconds, 1) } else { $null }
    $dur = if ($null -ne $t.lastScrapeDuration) { [Math]::Round([double]$t.lastScrapeDuration, 3) } else { $null }
    $targetLines += ('  대상 {0,-18} {1,-6} {2}  마지막 수집 {3}초 전 {4}' -f $t.labels.job, $t.health, $t.scrapeUrl, $(if ($null -ne $age) { $age } else { '-' }), $t.lastError)
    $targetData += [pscustomobject][ordered]@{
      job = $t.labels.job; health = $t.health; url = $t.scrapeUrl; last_error = $t.lastError
      last_scrape = $(if ($ls) { $ls.ToLocalTime().ToString('yyyy-MM-ddTHH:mm:sszzz') } else { $null }); last_scrape_age_s = $age; scrape_duration_s = $dur
    }
  }
  $devLines = @()
  $devData = @()
  $devSamplesOk = 0
  foreach ($e in $ent) {
    $id = Get-SeriesName $e.metric
    $st = @($avail | Where-Object { (Get-SeriesName $_.metric) -eq $id } | Select-Object -First 1)
    $ct = @($cnt | Where-Object { (Get-SeriesName $_.metric) -eq $id } | Select-Object -First 1)
    $hb = @($hbAge | Where-Object { (Get-SeriesName $_.metric) -eq $id } | Select-Object -First 1)
    $stv = if ($st.Count -gt 0) { [int][double]$st[0].value[1] } else { $null }
    $ctv = if ($ct.Count -gt 0) { [double]$ct[0].value[1] } else { $null }
    $hbv = if ($hb.Count -gt 0) { [Math]::Round([double]$hb[0].value[1], 1) } else { $null }
    $stName = if ($null -ne $stv -and $STATE_NAMES.ContainsKey($stv)) { $STATE_NAMES[$stv] } else { $null }
    $sOk = ($null -ne $ctv -and $ctv -ge $SAMPLES_OK)
    if ($sOk) { $devSamplesOk++ }
    $devLines += ('  장치 {0}  up={1} · 판정={2}({3}) · 10분 동안 {4}{5} · {6}' -f $id, $e.value[1], $(if ($null -ne $stv) { $stv } else { '-' }), $(if ($stName) { $stName } else { '-' }),
      $(if ($null -ne $ctv) { $ctv } else { '-' }), $(if ($sOk) { ' [끊김 없음]' } else { '' }),
      $(if ($null -ne $hbv) { '심박 {0}초 전' -f $hbv } else { '심박 없음 - 상태 메시지 하나로만 판정(살아 있다는 증거 아님)' }))
    $dev = [ordered]@{}
    foreach ($p in $e.metric.PSObject.Properties) { if ($p.Name -notin @('__name__', 'job', 'instance')) { $dev[$p.Name] = $p.Value } }
    $dev['up'] = [double]$e.value[1]
    $dev['state'] = $stv
    $dev['state_name'] = $stName
    $dev['samples_10m'] = $ctv
    $dev['samples_expected_10m'] = $SAMPLES_EXPECTED
    $dev['samples_ok'] = $sOk
    $dev['heartbeat_age_s'] = $hbv
    $dev['has_heartbeat'] = ($null -ne $hbv)
    $devData += [pscustomobject]$dev
  }
  $nameData = @($names | ForEach-Object { [pscustomobject][ordered]@{ name = $_.metric.__name__; series = [double]$_.value[1] } })

  # ---------- 파일
  $fileLines = @()
  $fileData = @()
  foreach ($f in @(Get-ChildItem $LOGS -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(otel_logs\.jsonl|otel_traces\.jsonl|mosquitto\.log)$' } | Sort-Object Name)) {
    $fileLines += ('  {0,-18} {1,12:N0} B  {2:yyyy-MM-dd HH:mm:ss}' -f $f.Name, $f.Length, $f.LastWriteTime)
    $fileData += [pscustomobject][ordered]@{ name = $f.Name; bytes = $f.Length; modified = $f.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:sszzz') }
  }
  $sum = (Get-ChildItem $PROM_DATA -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
  if (-not $sum) { $sum = 0 }

  # ---------- 판정(요약) — 항목마다 ok 와 사유
  $why = @()
  if (-not $wslUp) { $why += 'WSL 꺼짐' }
  elseif ($svcOk -lt 3) { $why += ('서비스 active {0}/3' -f $svcOk) }
  if ($null -eq $h) { $why += '임무 이력 서버 응답 없음' }
  if ($wslUp -and -not $dbRow.ok) { $why += 'DB 를 못 읽음' }
  $sLaptop = [ordered]@{ ok = ($why.Count -eq 0); reason = $(if ($why.Count) { $why -join ' · ' } else { $null }) }
  $sEdge = [ordered]@{ ok = ($compUp -eq 4); reason = $(if ($compUp -lt 4) { '꺼짐: ' + ($compDown -join ', ') } else { $null }) }
  $piWhy = if (-not $brokerUp) { '브로커(1883) 꺼짐' } elseif ($bOn -eq 0) { '붙은 파이 브리지 없음(파이가 꺼져 있다)' } elseif ($live.Count -eq 0) { '5초 동안 새로 들어온 업무 메시지 없음' } else { $null }
  $sPi = [ordered]@{ ok = ($null -eq $piWhy); reason = $piWhy }
  $otWhy = if (-not $colUp) { 'Collector 꺼짐' } elseif ($acc -le 0) { '받은 것 없음 - 말단이 관측을 보내지 않는다(파이 무변경이면 0)' } else { $null }
  $sOtel = [ordered]@{ ok = ($null -eq $otWhy); reason = $otWhy }
  $prWhy = if (-not $promUp) { 'Prometheus 꺼짐' } elseif ($targets.Count -eq 0) { '수집 대상 없음' } elseif ($tUp -lt $targets.Count) { ('수집 대상 up {0}/{1}' -f $tUp, $targets.Count) } else { $null }
  $sProm = [ordered]@{ ok = ($null -eq $prWhy); reason = $prWhy }

  # ---------- 화면 줄
  $D.Add(('==================== MK2 전체 상태 · {0:yyyy-MM-dd HH:mm:ss} ({1}초마다 새로 보고 자동 저장 · v3) ====================' -f $nowDate, $REFRESH_S))
  $D.Add('요약')
  $latest = if ($runs.Count -gt 0) { '{0} {1}' -f $runs[0].date, $runs[0].run } else { '-' }
  $dbText = if ($dbRow.ok) { 'DB 판 {0} · 그림 {1} · 마지막 저장 {2}' -f $dbRow.runs, $dbRow.images, $(if ($dbRow.last_saved) { ([DateTimeOffset]::Parse($dbRow.last_saved)).ToString('MM-dd HH:mm:ss') } else { '-' }) } else { 'DB 못 읽음' }
  $D.Add(('  {0} 노트북 서버   WSL {1} · 서비스 {2}/3 · 임무 이력 {3} · {4}{5}' -f (Mark $sLaptop.ok), $(if ($wslUp) { 'Running' } else { '꺼짐' }), $svcOk, $(if ($h) { '응답(VZ 판 {0} · 맨 위 {1})' -f $runs.Count, $latest } else { '응답 없음' }), $dbText, $(if ($sLaptop.reason) { '   <- ' + $sLaptop.reason } else { '' })))
  $D.Add(('  {0} 엣지 스택     떠 있음 {1}/4 (브로커 · Collector · Prometheus · 가용성 판정기){2}' -f (Mark $sEdge.ok), $compUp, $(if ($sEdge.reason) { '   <- ' + $sEdge.reason } else { '' })))
  $D.Add(('  {0} 파이 -> 엣지  브리지 붙음 {1}/{2} · 업무 메시지 1분당 약 {3}건(5초 {4}건 · 토픽 {5}개){6}' -f (Mark $sPi.ok), $bOn, $bTotal, $perMin, $live.Count, $tg.Count, $(if ($sPi.reason) { '   <- ' + $sPi.reason } else { '' })))
  $D.Add(('  {0} 관측(OTel)    Collector 받은 것 {1}{2} · Prometheus 의 OTel 지표 이름 {3}개{4}' -f (Mark $sOtel.ok), $acc, $(if ($null -ne $accDelta) { ' (지난번 뒤 +{0})' -f $accDelta } else { '' }), $otelNames, $(if ($sOtel.reason) { '   <- ' + $sOtel.reason } else { '' })))
  $D.Add(('  {0} Prometheus    대상 up {1}/{2} · 장치 online {3}/{4} · 10분 동안 끊김 없이 쌓임 {5}/{4}{6}' -f (Mark $sProm.ok), $tUp, $targets.Count, $online, $ent.Count, $devSamplesOk, $(if ($sProm.reason) { '   <- ' + $sProm.reason } else { '' })))

  $D.Add('')
  $D.Add('== A 노트북 서버 - WSL · 서비스(postgresql@18-main · mission-history · 백업 타이머) · 임무 이력 · DB · 백업')
  foreach ($l in $wl) { $D.Add('  ' + $l) }
  if ($wslUp) { $D.Add('  서비스: ' + ($svc -join ' · ')) }
  else { $D.Add('  WSL 이 꺼져 있다 - 바탕화면 「MK2 전체 켜기」 를 다시 더블클릭한다') }
  if ($h) {
    $D.Add(('  health: ok={0} · 판 {1}개(검사 판 000101 포함) · 서버 시각 {2}' -f $h.ok, $h.runCount, $h.serverTime))
    $D.Add('  최근 판 셋 (임무를 하나 끝내면 맨 위에 그 판이 온다):')
    foreach ($r in $latestRuns) { $D.Add(('    {0} {1} {2}' -f $r.date, $r.run, $r.record_kind)) }
  }
  else { $D.Add(('  {0} 응답 없음 - WSL 이 꺼졌거나 임무 이력 서버가 안 떠 있다' -f $MH_URL)) }
  if ($dbRow.ok) { $D.Add(('  DB(검사 판 빼고): 판 {0} · 그림 행 {1} · 마지막 저장 {2} · DB 크기 {3} MB' -f $dbRow.runs, $dbRow.images, $dbRow.last_saved, $dbRow.size_mb)) }
  else { $D.Add(('  DB: 못 읽음 - {0}' -f $dbRow.error)) }
  $D.Add(('  마지막 백업: {0}' -f $(if ($lastBackup) { $lastBackup } else { '-' })))

  $D.Add('== B 엣지 스택 - 듣는 포트로 판정')
  foreach ($l in $compLines) { $D.Add($l) }

  $D.Add('== C 파이 브리지 (1 = 붙음 · 0 = 끊김) · 5초 동안 새로 들어온 업무 메시지')
  if (-not $brokerUp) { $D.Add('  브로커(1883)가 꺼져 있어 볼 수 없다') }
  else {
    if ($bTotal -gt 0) { $D.Add('  ' + (($bridgeData | ForEach-Object { '{0} {1}' -f $_.short, $_.connected }) -join ' · ')) } else { $D.Add('  (브리지 상태 줄 없음)') }
    if ($tg.Count -gt 0) { foreach ($g in $tg) { $D.Add(('  {0,6}  {1}' -f $g.Count, $g.Name)) } } else { $D.Add('  (5초 동안 새로 들어온 업무 메시지 없음)') }
    if ($retTopics.Count -gt 0) { $D.Add(('  보관 메시지 {0}개(지금 보낸 것 아님 - 예전에 남겨 둔 마지막 값): {1}' -f $retTopics.Count, ($retTopics -join ' · '))) }
  }

  $D.Add('== D Collector (OpenTelemetry) - 켠 뒤 누적')
  if (-not $colUp) { $D.Add('  8888 응답 없음 - Collector 가 꺼져 있다') }
  elseif ($col.Count -eq 0) { $D.Add('  (아직 받은 것 없음 - 말단이 관측을 안 보내면 0 이다)') }
  else { foreach ($l in $col) { $D.Add('  ' + $l) } }

  $D.Add(('== E 엣지 Prometheus - 대상 · 장치 판정 · 10분 동안 쌓인 수(15초마다 → {0}, {1} 이상이면 [끊김 없음]) · 심박 나이' -f $SAMPLES_EXPECTED, $SAMPLES_OK))
  if (-not $promUp) { $D.Add('  9090 응답 없음 - Prometheus 가 꺼져 있다') }
  else {
    foreach ($l in $targetLines) { $D.Add($l) }
    if ($ent.Count -eq 0) { $D.Add('  (장치 판정 없음 - 파이가 꺼져 있거나 아직 등록 · 심박이 안 왔다)') }
    foreach ($l in $devLines) { $D.Add($l) }
    $D.Add('  --- 쌓인 지표 이름 · 시계열 수 (hw_* · system_*)')
    if ($names.Count -eq 0) { $D.Add('  (없음)') }
    foreach ($n in $names) { $D.Add(('  {0,-44} {1}' -f $n.metric.__name__, $n.value[1])) }
  }

  $D.Add('== F 엣지에 쌓이는 파일')
  foreach ($l in $fileLines) { $D.Add($l) }
  $D.Add(('  Prometheus 저장(prom_data) {0:N1} MB' -f ($sum / 1MB)))

  # ---------- 같은 내용의 값 (시각화가 읽는 JSON) — 칸 설명은 docs\노트북서버_261125\ 의 JSON 설명 md
  $data = [ordered]@{
    schema_version = $SCHEMA_VERSION
    time           = $nowDate.ToString('yyyy-MM-ddTHH:mm:sszzz')
    run_id         = $RUN_ID
    refresh_s      = $REFRESH_S
    sources        = [ordered]@{
      prometheus           = 'http://127.0.0.1:9090'
      prometheus_queries   = [ordered]@{ device_up = 'hw_entity_up'; device_state = 'hw_availability_state'; heartbeat_age = 'hw_heartbeat_age_seconds'; samples_10m = 'count_over_time(hw_entity_up[10m])' }
      mission_history      = $MH_URL
      collector_metrics    = 'http://127.0.0.1:8888/metrics'
      availability_metrics = 'http://127.0.0.1:9105/metrics'
      broker               = 'mqtt://127.0.0.1:1883'
    }
    summary        = [ordered]@{ laptop_server = $sLaptop; edge_stack = $sEdge; pi_to_edge = $sPi; otel = $sOtel; prometheus = $sProm }
    laptop_server  = [ordered]@{
      wsl_running     = $wslUp
      services        = $svcObj
      mission_history = [ordered]@{
        url              = $MH_URL
        ok               = ($null -ne $h)
        run_count_all    = $(if ($h) { $h.runCount } else { $null })
        run_count_listed = $runs.Count
        latest_runs      = $latestRuns
      }
      db              = $dbRow
      last_backup     = $lastBackup
    }
    edge_stack     = $compData
    pi_to_edge     = [ordered]@{
      broker_up         = $brokerUp
      bridges           = $bridgeData
      bridges_connected = $bOn
      live_messages_5s  = $live.Count
      messages_per_min  = $perMin
      topics_5s         = $topicData
      retained_topics   = $retTopics
    }
    otel           = [ordered]@{ collector_up = $colUp; accepted_total = $acc; accepted_since_last = $accDelta; lines = $col; otel_metric_names = $otelNames }
    prometheus     = [ordered]@{ up = $promUp; targets = $targetData; devices = $devData; devices_online = $online; devices_samples_ok = $devSamplesOk; metric_names = $nameData }
    files          = [ordered]@{ logs = $fileData; prom_data_mb = [Math]::Round($sum / 1MB, 1) }
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
Write-Host ("# MK2 전체 켜기 v3 - {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
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
