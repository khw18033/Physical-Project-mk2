# MK2 서버화 상태판 v1 — VZ 가 안 보여 주는 것만 한 창에: 1 노트북 서버 · 2 엣지 스택 · 3 파이 -> 노트북 · 4 쌓이고 있나 (2026-11-26)
#   「MK2 전체 켜기」(mk2_all_start_v5.ps1)가 켤 때 이 창을 띄운다:
#     powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\mk2_board_v1.ps1 -RunId <구동 시각>
#   손으로 열어도 된다(-RunId 없이 — 그때는 구동과 상관없이 가장 최근 파일을 보여 준다).
#
# - 보기만 한다. 아무것도 켜거나 끄거나 묻지 않는다(WSL · Prometheus · 브로커에 직접 묻지도 않는다).
#   켜기 · 상태 창이 30초마다 쓰는 C:\mk2_edge\logs\mk2_status\mk2_status_latest.json 을 1초마다 읽어 그린다
#   → 숫자는 30초마다 바뀌고, 맨 윗줄의 「몇 초 전」 만 1초마다 바뀐다. 숫자가 바뀔 때만 화면 전체를 다시 그린다(깜빡임 줄이기).
# - -RunId 를 받으면 그 구동이 쓴 것만 보여 준다 — 지난 구동이 남긴 파일을 지금 것으로 보이지 않게.
# - 데이터가 (갱신 주기 × 2 + 20)초 넘게 그대로면 맨 윗줄에 빨갛게 「멈춤」 — 켜기 · 상태 창이 닫혔거나 멈춘 것.
# - 넣지 않은 것: 5번(장치마다 켜짐 · 꺼짐 · 몇 초 전 심박 — VZ 가 파이 직결로 보여 준다) · 관측(OTel — 파이 무변경이면 늘 0).
# - 이 창을 닫아도 아무것도 꺼지지 않는다. 다시 열기: 켜기 · 상태 창에서 B.
param([string]$RunId = '')

. (Join-Path $PSScriptRoot 'edge_common.ps1')
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

$LATEST = Join-Path $LOGS 'mk2_status\mk2_status_latest.json'
$DOT    = [string][char]0x25CF
$INV    = [System.Globalization.CultureInfo]::InvariantCulture
$SAMPLES_OK_DEFAULT = 36
$script:Body = New-Object System.Collections.Generic.List[object]
$script:Problems = @()
$script:HeaderW = 0

$Host.UI.RawUI.WindowTitle = 'MK2 서버화 상태판 - VZ 가 안 보여 주는 1~4 (보기만 · 닫아도 아무것도 안 꺼짐)'
try {
  $raw = $Host.UI.RawUI
  $buf = $raw.BufferSize
  if ($buf.Width -lt 110) { $buf.Width = 110; $raw.BufferSize = $buf }
  $win = $raw.WindowSize
  $max = $raw.MaxPhysicalWindowSize
  $win.Width = [Math]::Min(110, $max.Width)
  $win.Height = [Math]::Min(50, $max.Height)
  $raw.WindowSize = $win
}
catch { }
try { [Console]::CursorVisible = $false } catch { }

# ---- 글자 폭 — 한글 · 한자 · 전각은 화면에서 두 칸
function DispW([string]$s) {
  $n = 0
  foreach ($ch in $s.ToCharArray()) {
    $c = [int]$ch
    if (($c -ge 0x1100 -and $c -le 0x115F) -or ($c -ge 0x2E80 -and $c -le 0xA4CF) -or ($c -ge 0xAC00 -and $c -le 0xD7A3) -or ($c -ge 0xF900 -and $c -le 0xFAFF) -or ($c -ge 0xFE30 -and $c -le 0xFE4F) -or ($c -ge 0xFF00 -and $c -le 0xFF60) -or ($c -ge 0xFFE0 -and $c -le 0xFFE6)) { $n += 2 }
    else { $n += 1 }
  }
  return $n
}

function PadW([string]$s, [int]$n) { return ($s + (' ' * [Math]::Max(0, $n - (DispW $s)))) }

function CutW([string]$s, [int]$n) {
  if ((DispW $s) -le $n) { return $s }
  $sb = ''
  foreach ($ch in $s.ToCharArray()) {
    if ((DispW ($sb + $ch)) -gt ($n - 1)) { break }
    $sb += $ch
  }
  return ($sb + '~')
}

# ---- 화면 한 줄 = 글 · 색 짝들:  Ln '글' '색' '글' '색' ...
function Ln { $script:Body.Add(@($args)) }

function Mk([string]$kind) {
  switch ($kind) { 'ok' { 'Green' } 'bad' { 'Red' } 'warn' { 'Yellow' } 'info' { 'White' } default { 'DarkGray' } }
}

# 항목 한 줄:  이름(칸 맞춤) · ● 한 낱말(색) · 덧붙임
function Row([string]$label, [string]$kind, [string]$word, [string]$rest, [int]$pad = 24) {
  Ln ('  ' + (PadW $label $pad)) 'Gray' ($DOT + ' ' + $word) (Mk $kind) $(if ($rest) { '  ' + $rest } else { '' }) 'Gray'
}

# 묶음 머리:  제목 · ● 정상 / ● 이상 - 사유
function Section([string]$title, $ok, [string]$reason) {
  Ln '' 'Gray'
  if ($ok) { Ln $title 'Cyan' ('   ' + $DOT + ' 정상') 'Green' }
  else {
    Ln $title 'Cyan' ('   ' + $DOT + ' 이상') 'Red' $(if ($reason) { ' - ' + $reason } else { '' }) 'Red'
    $script:Problems += $title
  }
}

function Ago([double]$s) {
  if ($s -lt 0) { $s = 0 }
  if ($s -lt 60) { return ('{0}초 전' -f [int][Math]::Floor($s)) }
  if ($s -lt 3600) { return ('{0}분 전' -f [int][Math]::Floor($s / 60)) }
  if ($s -lt 86400) { return ('{0}시간 {1}분 전' -f [int][Math]::Floor($s / 3600), [int][Math]::Floor(($s % 3600) / 60)) }
  return ('{0}일 전' -f [int][Math]::Floor($s / 86400))
}

# 시각 글자 → DateTimeOffset (소수점 아래 7자리까지만 읽는다)
function To-Dto($v) {
  if ($null -eq $v -or "$v" -eq '') { return $null }
  if ($v -is [datetime]) { return [DateTimeOffset]$v }
  try { return [DateTimeOffset]::Parse((([string]$v) -replace '(\.\d{7})\d+', '$1'), $INV) } catch { return $null }
}

# null 을 빼고 목록으로 (부르는 쪽에서 @( ) 로 감싼다)
function Items($x) { return @($x | Where-Object { $null -ne $_ }) }

function Svc($svcs, [string]$name) {
  if ($null -eq $svcs) { return $null }
  $p = $svcs.PSObject.Properties[$name]
  if ($null -ne $p -and $null -ne $p.Value) { return [string]$p.Value }
  return $null
}
function SvcKind([string]$st) { if ($st -eq 'active') { return 'ok' } elseif ($st -eq '') { return 'none' } else { return 'bad' } }
function SvcWord([string]$st) { if ($st -eq '') { return '-' } else { return $st } }

function Get-SamplesOk($x) {
  if ($null -ne $x.samples_ok) { return [bool]$x.samples_ok }
  return ($null -ne $x.samples_10m -and [double]$x.samples_10m -ge $SAMPLES_OK_DEFAULT)
}

# ---- 최신 파일 읽기 — 켜기 · 상태 창이 쓰는 중이어도 막지 않게 함께 열기로 연다. 다 못 읽었으면 null(다음 1초에 다시)
function Read-Latest {
  if (-not (Test-Path -LiteralPath $LATEST)) { return $null }
  $fs = $null
  $sr = $null
  try {
    $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
    $fs = [System.IO.File]::Open($LATEST, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $share)
    $sr = [System.IO.StreamReader]::new($fs, [System.Text.UTF8Encoding]::new($false))
    $txt = $sr.ReadToEnd()
    if ($txt.Trim() -eq '') { return $null }
    return (ConvertFrom-Json -InputObject $txt)
  }
  catch { return $null }
  finally {
    if ($null -ne $sr) { $sr.Dispose() } elseif ($null -ne $fs) { $fs.Dispose() }
  }
}

# ---- 그릴 줄 만들기 — 이번 구동의 데이터
function Build-Body($d) {
  $script:Body = New-Object System.Collections.Generic.List[object]
  $script:Problems = @()
  $snap = To-Dto $d.time
  $ls = $d.laptop_server
  $db = $ls.db

  # ---------- 1 노트북 서버
  $s1 = $d.summary.laptop_server
  Section '1 노트북 서버 - 살아 있나' $s1.ok ([string]$s1.reason)
  Row 'WSL (Ubuntu-26.04)' $(if ($ls.wsl_running) { 'ok' } else { 'bad' }) $(if ($ls.wsl_running) { '켜짐' } else { '꺼짐' }) ''
  $pg = Svc $ls.services 'postgresql@18-main'
  Row 'PostgreSQL' (SvcKind $pg) (SvcWord $pg) '서비스 postgresql@18-main'
  $mhs = Svc $ls.services 'mission-history'
  $mh = $ls.mission_history
  $mhOk = ($mh.ok -and $mhs -eq 'active')
  Row '임무 이력 서버 (8850)' $(if ($mhOk) { 'ok' } else { 'bad' }) $(if ($mh.ok) { '응답함' } else { '응답 없음' }) ('서비스 {0} · VZ 에 보이는 판 {1}개' -f (SvcWord $mhs), $(if ($mh.ok) { [string]$mh.run_count_listed } else { '-' }))
  $bt = Svc $ls.services 'mission-history-backup.timer'
  Row '백업 타이머' (SvcKind $bt) (SvcWord $bt) '매일 22:00 자동 백업'
  Row 'DB (PostgreSQL mk2)' $(if ($db.ok) { 'ok' } else { 'bad' }) $(if ($db.ok) { '읽힘' } else { '못 읽음' }) $(if ($db.ok) { '읽기 계정으로 읽어 봄' } else { [string]$db.error })

  # ---------- 2 엣지 스택
  $s2 = $d.summary.edge_stack
  Section '2 엣지 스택 - 넷이 떠 있나' $s2.ok ([string]$s2.reason)
  foreach ($c in @(Items $d.edge_stack)) {
    Row ([string]$c.label) $(if ($c.up) { 'ok' } else { 'bad' }) $(if ($c.up) { '떠 있음' } else { '꺼짐' }) (':' + [string]$c.port) 34
  }

  # ---------- 3 파이 -> 노트북
  $p = $d.pi_to_edge
  $s3 = $d.summary.pi_to_edge
  Section '3 파이 -> 노트북 - 데이터가 오나' $s3.ok ([string]$s3.reason)
  Row '브로커 (1883)' $(if ($p.broker_up) { 'ok' } else { 'bad' }) $(if ($p.broker_up) { '떠 있음' } else { '꺼짐' }) '파이 브리지가 붙는 곳'
  $br = @(Items $p.bridges)
  if ($br.Count -eq 0) { Row '파이 브리지' $(if ($p.broker_up) { 'bad' } else { 'none' }) '없음' '브리지 상태가 안 왔다' }
  else {
    $on = @($br | Where-Object { [int]$_.connected -eq 1 }).Count
    $segs = @(('  ' + (PadW '파이 브리지' 24)), 'Gray', ('붙음 {0}/{1} ' -f $on, $br.Count), $(if ($on -eq $br.Count) { 'Green' } elseif ($on -gt 0) { 'Yellow' } else { 'Red' }))
    foreach ($b in $br) {
      $short = if ($b.short) { [string]$b.short } else { ([string]$b.name) -replace '^edge-[^-]+-', '' }
      $isOn = ([int]$b.connected -eq 1)
      $segs += @((' ' + $DOT + ' ' + $short + $(if ($isOn) { ' 붙음' } else { ' 끊김' })), $(if ($isOn) { 'Green' } else { 'Red' }))
    }
    $script:Body.Add($segs)
  }
  $live = [int]$p.live_messages_5s
  $k3 = if ($live -gt 0) { 'ok' } elseif ($p.broker_up) { 'warn' } else { 'bad' }
  Row '새로 들어온 업무 메시지' $k3 ('5초 {0}건' -f $live) ('1분당 약 {0}건 (state · status · heartbeat)' -f [int]$p.messages_per_min)
  foreach ($t in @(Items $p.topics_5s | Select-Object -First 3)) {
    Ln ('      {0,4}건  ' -f [int]$t.count) 'DarkGray' ([string]$t.topic) 'DarkGray'
  }
  $ret = @(Items $p.retained_topics)
  if ($ret.Count -gt 0) {
    Row '보관 메시지' 'warn' ('{0}개' -f $ret.Count) '지금 보낸 것 아님 - 브로커에 남아 있던 마지막 값'
    foreach ($r in @($ret | Select-Object -First 2)) { Ln ('      ' + [string]$r) 'DarkGray' }
    if ($ret.Count -gt 2) { Ln ('      ... 그 밖에 {0}개' -f ($ret.Count - 2)) 'DarkGray' }
  }
  else { Row '보관 메시지' 'none' '없음' '' }

  # ---------- 4 쌓이고 있나 — Prometheus 가 끊김 없이 · DB · 백업
  $pr = $d.prometheus
  $tg = @(Items $pr.targets)
  $dv = @(Items $pr.devices)
  $young = $false
  $runMin = $null
  try {
    $start = [datetime]::ParseExact([string]$d.run_id, 'yyMMdd_HHmmss', $INV)
    if ($snap) { $runMin = ($snap.LocalDateTime - $start).TotalMinutes; $young = ($runMin -lt 10.5) }
  }
  catch { }
  $bkName = [string]$ls.last_backup
  $bkAge = $null
  if ($bkName -match '^(daily|manual)_(\d{6})_(\d{6})$') {
    try {
      $bkAt = [datetime]::ParseExact($Matches[2] + $Matches[3], 'yyMMddHHmmss', $INV)
      if ($snap) { $bkAge = ($snap.LocalDateTime - $bkAt).TotalSeconds }
    }
    catch { }
  }
  $devOk = 0
  foreach ($x in $dv) { if (Get-SamplesOk $x) { $devOk++ } }
  $why = @()
  if (-not $pr.up) { $why += 'Prometheus 꺼짐' }
  else {
    $tUp = @($tg | Where-Object { $_.health -eq 'up' }).Count
    if ($tg.Count -eq 0) { $why += '수집 대상 없음' }
    elseif ($tUp -lt $tg.Count) { $why += ('수집 대상 up {0}/{1}' -f $tUp, $tg.Count) }
    if ($dv.Count -gt 0 -and $devOk -lt $dv.Count -and -not $young) { $why += ('끊김 없이 쌓인 장치 {0}/{1}' -f $devOk, $dv.Count) }
  }
  if (-not $db.ok) { $why += 'DB 를 못 읽음' }
  if ($null -eq $bkAge) { $why += '백업 없음' }
  elseif ($bkAge -gt 26 * 3600) { $why += '마지막 백업이 26시간보다 오래됨' }
  Section '4 쌓이고 있나 - 끊김 없이 · DB · 백업' ($why.Count -eq 0) ($why -join ' · ')

  if (-not $pr.up) { Row 'Prometheus (9090)' 'bad' '꺼짐' '' }
  foreach ($t in $tg) {
    $age = $t.last_scrape_age_s
    $ageText = if ($null -ne $age -and [double]$age -ge 0) { '마지막 수집 {0}초 전 (15초마다)' -f $age } else { '마지막 수집 -' }
    $err = [string]$t.last_error
    Row ('수집 ' + [string]$t.job) $(if ($t.health -eq 'up') { 'ok' } else { 'bad' }) ([string]$t.health) ($ageText + $(if ($err) { ' - ' + $err } else { '' }))
  }
  Ln ('  ' + (PadW '장치마다 10분 동안 쌓인 수' 24)) 'Gray' '  15초마다 수집 -> 10분에 40번 · 36번 이상이면 끊김 없음' 'DarkGray'
  if ($young -and $null -ne $runMin) { Ln ('    켠 지 {0}분 - 켠 뒤 10분 동안은 40 보다 적은 것이 정상' -f [int][Math]::Floor($runMin)) 'Yellow' }
  if ($dv.Count -eq 0) { Ln '    (장치 판정 없음 - 파이가 꺼져 있거나 아직 심박이 안 왔다)' 'DarkGray' }
  foreach ($x in $dv) {
    $name = if ($x.entity_id) { [string]$x.entity_id } else { [string](@($x.PSObject.Properties)[0].Value) }
    $sok = Get-SamplesOk $x
    $exp = if ($x.samples_expected_10m) { [int]$x.samples_expected_10m } else { 40 }
    $cnt = if ($null -ne $x.samples_10m) { [int][double]$x.samples_10m } else { 0 }
    $col = if ($sok) { 'Green' } elseif ($young) { 'Yellow' } else { 'Red' }
    $word = if ($sok) { '끊김 없음' } elseif ($young) { '쌓는 중' } else { '모자람' }
    Ln ('    ' + (PadW $name 22)) 'Gray' ('{0} {1,2}/{2}  {3}' -f $DOT, $cnt, $exp, $word) $col ('   ' + [string]$x.entity_type + ' · ' + [string]$x.zone) 'DarkGray'
  }
  if ($db.ok) {
    Row 'DB 에 쌓인 것' 'ok' ('판 {0:N0} · 그림 {1:N0}' -f [double]$db.runs, [double]$db.images) ('{0} MB · 검사 판 000101 빼고' -f $db.size_mb)
    $saved = To-Dto $db.last_saved
    Row '마지막으로 판 저장' 'info' $(if ($saved) { $saved.ToLocalTime().ToString('MM-dd HH:mm:ss') } else { '-' }) $(if ($saved -and $snap) { '(' + (Ago (($snap - $saved).TotalSeconds)) + ' - 임무를 끝내면 바뀐다)' } else { '' })
  }
  else { Row 'DB 에 쌓인 것' 'bad' '못 읽음' ([string]$db.error) }
  Row '마지막 백업' $(if ($null -ne $bkAge -and $bkAge -le 26 * 3600) { 'ok' } else { 'warn' }) $(if ($bkName) { $bkName } else { '없음' }) $(if ($null -ne $bkAge) { '(' + (Ago $bkAge) + ' · 매일 22:00)' } else { '' })

  Ln '' 'Gray'
  Ln '  보기만 한다 - 이 창을 닫아도 아무것도 꺼지지 않는다 · 다시 열기: 「MK2 전체 - 켜기 · 상태」 창에서 B' 'DarkGray'
  Ln '  5번(장치마다 켜짐 · 꺼짐 · 몇 초 전 심박)은 VZ 가 보여 준다 · 끄기는 켜기 · 상태 창에서 Q -> Y' 'DarkGray'
}

# ---- 그릴 줄 만들기 — 이번 구동의 첫 데이터가 아직 없을 때
function Build-Waiting([string]$other) {
  $script:Body = New-Object System.Collections.Generic.List[object]
  $script:Problems = @()
  Ln '' 'Gray'
  Ln '  「MK2 전체 - 켜기 · 상태」 창이 이번 구동의 첫 상태를 모으면 여기에 숫자가 뜬다 (켠 뒤 1~2분).' 'Yellow'
  if ($other) { Ln ('  지금 파일은 다른 구동({0})이 쓴 것이라 보여 주지 않는다.' -f $other) 'DarkGray' }
  Ln ('  읽는 파일: {0}' -f $LATEST) 'DarkGray'
  Ln '' 'Gray'
  Ln '  보기만 한다 - 이 창을 닫아도 아무것도 꺼지지 않는다 · 다시 열기: 「MK2 전체 - 켜기 · 상태」 창에서 B' 'DarkGray'
}

# ---- 한 줄 그리기 — 창 폭을 넘지 않게 자른다(넘으면 줄이 꺾여 화면이 밀린다)
function Draw-Line($segs, [int]$maxW) {
  $used = 0
  for ($i = 0; $i + 1 -lt $segs.Count; $i += 2) {
    $t = [string]$segs[$i]
    $c = [string]$segs[$i + 1]
    if ($t -eq '') { continue }
    $room = $maxW - $used
    if ($room -le 0) { break }
    if ((DispW $t) -gt $room) { $t = CutW $t $room }
    Write-Host -NoNewline -ForegroundColor $c $t
    $used += (DispW $t)
  }
  Write-Host ''
}

# ---- 맨 윗줄 — 1초마다 그 자리에 다시 쓴다(데이터가 몇 초 전인지)
function Draw-Header($g, [int]$maxW) {
  [Console]::SetCursorPosition(0, 0)
  $segs = @('MK2 서버화 상태판 v1', 'Cyan')
  if ($null -eq $g) { $segs += @('   이번 구동의 첫 데이터를 기다리는 중', 'Yellow') }
  else {
    $snap = To-Dto $g.time
    $ref = 30
    if ($g.refresh_s) { $ref = [int]$g.refresh_s }
    if ($snap) {
      $age = ([DateTimeOffset](Get-Date) - $snap).TotalSeconds
      $segs += @(('   데이터 {0} ({1} · {2}초마다)' -f $snap.ToLocalTime().ToString('HH:mm:ss'), (Ago $age), $ref), 'Gray')
      if ($age -gt ($ref * 2 + 20)) { $segs += @('   !! 멈춤 - 켜기 · 상태 창이 닫혔거나 멈췄다', 'Red') }
      elseif ($script:Problems.Count -gt 0) { $segs += @(('   이상 {0}곳' -f $script:Problems.Count), 'Red') }
      else { $segs += @('   모두 정상', 'Green') }
    }
  }
  $w = 0
  for ($i = 0; $i -lt $segs.Count; $i += 2) { $w += (DispW ([string]$segs[$i])) }
  $padN = [Math]::Max(8, $script:HeaderW - $w + 8)
  $script:HeaderW = $w
  $segs += @((' ' * $padN), 'Gray')
  Draw-Line $segs $maxW
}

# ---- 1초마다 — 읽고, 숫자가 바뀌었으면 전체를, 아니면 맨 윗줄만 다시 그린다
$good = $null
$other = ''
$lastKey = $null
$lastWidth = -1
while ($true) {
  try {
    $d = Read-Latest
    if ($null -ne $d) {
      if ($RunId -eq '' -or [string]$d.run_id -eq $RunId) { $good = $d }
      elseif ($null -eq $good) { $other = [string]$d.run_id }
    }
    $width = 110
    try { $width = [int]$Host.UI.RawUI.WindowSize.Width } catch { }
    $maxW = [Math]::Max(40, $width - 1)
    if ($null -ne $good) { Build-Body $good } else { Build-Waiting $other }
    $key = (@($script:Body | ForEach-Object { $_ -join '|' })) -join "`n"
    if ($key -ne $lastKey -or $width -ne $lastWidth) {
      Clear-Host
      Write-Host ''
      Draw-Line @(('=' * [Math]::Min(104, $maxW)), 'DarkGray') $maxW
      foreach ($segs in $script:Body) { Draw-Line $segs $maxW }
      $lastKey = $key
      $lastWidth = $width
      $script:HeaderW = 0
    }
    Draw-Header $good $maxW
  }
  catch {
    $lastKey = $null
    try { Clear-Host } catch { }
    Write-Host ('!! 상태판 오류 - 1초 뒤 다시 그린다: {0}' -f $_.Exception.Message) -ForegroundColor Red
  }
  Start-Sleep -Seconds 1
}
