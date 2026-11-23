# MK2 엣지 런처 — 바탕화면 「MK2 엣지」 바로가기가 이 파일을 연다 (2026-11-23)
#   바로가기 대상: powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\mk2_edge\launcher\edge_launcher.ps1
# 체크한 구성요소를 켠다 · 끈다 · 상태를 본다. 구성요소마다 PowerShell 창이 하나씩 뜨고(run_component.ps1),
# 그 창이 프로그램을 돌리며 로그를 C:\mk2_edge\logs\ 에 남긴다. 이 런처 창을 닫아도 켜 둔 창들은 계속 돈다.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

. (Join-Path $PSScriptRoot 'edge_common.ps1')
$RUN    = Join-Path $PSScriptRoot 'run_component.ps1'
$STATUS = Join-Path $PSScriptRoot 'edge_status.ps1'
$PROBE  = Join-Path $PSScriptRoot 'edge_probe_test.ps1'

function Open-PsWindow([string]$File, [string[]]$Extra) {
  $argList = @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $File)
  if ($Extra) { $argList += $Extra }
  Start-Process -FilePath 'powershell.exe' -ArgumentList $argList
}

# ---- 창
$font = New-Object System.Drawing.Font('Malgun Gothic', 10)
$form = New-Object System.Windows.Forms.Form
$form.Text = 'MK2 엣지'
$form.Font = $font
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.ClientSize = New-Object System.Drawing.Size(640, 430)

function New-Button([string]$Text, [int]$X, [int]$Y, [int]$W) {
  $b = New-Object System.Windows.Forms.Button
  $b.Text = $Text
  $b.Location = New-Object System.Drawing.Point($X, $Y)
  $b.Size = New-Object System.Drawing.Size($W, 34)
  $form.Controls.Add($b)
  $b
}

$group = New-Object System.Windows.Forms.GroupBox
$group.Text = '구성요소 — 체크한 것만 켜고 끈다 (켜는 순서: 위에서 아래)'
$group.Location = New-Object System.Drawing.Point(12, 10)
$group.Size = New-Object System.Drawing.Size(616, 176)
$form.Controls.Add($group)

$checks = @{}
$statusLabels = @{}
$i = 0
foreach ($k in $COMPONENTS.Keys) {
  $c = $COMPONENTS[$k]
  $cb = New-Object System.Windows.Forms.CheckBox
  $cb.Text = $c.Label
  $cb.AutoSize = $true
  $cb.Checked = $true
  $cb.Location = New-Object System.Drawing.Point(16, (30 + $i * 34))
  $group.Controls.Add($cb)
  $checks[$k] = $cb

  $lb = New-Object System.Windows.Forms.Label
  $lb.AutoSize = $true
  $lb.Location = New-Object System.Drawing.Point(380, (32 + $i * 34))
  $lb.Text = '…'
  $group.Controls.Add($lb)
  $statusLabels[$k] = $lb
  $i++
}

$btnStart   = New-Button '켜기' 12 198 110
$btnStop    = New-Button '끄기' 130 198 110
$btnRefresh = New-Button '새로 보기' 248 198 110
$btnStatus  = New-Button '상태 확인 (파일로 남김)' 12 240 230
$btnProbe   = New-Button '관측 사슬 시험 (가짜 1분)' 250 240 230
$btnProm    = New-Button 'Prometheus 화면' 12 282 150
$btnLogs    = New-Button '로그 폴더' 170 282 110
$btnManual  = New-Button '매뉴얼' 288 282 110
$btnClose   = New-Button '닫기' 518 282 110

$msg = New-Object System.Windows.Forms.Label
$msg.Location = New-Object System.Drawing.Point(12, 326)
$msg.Size = New-Object System.Drawing.Size(616, 56)
$msg.Text = ''
$form.Controls.Add($msg)

$hint = New-Object System.Windows.Forms.Label
$hint.Location = New-Object System.Drawing.Point(12, 388)
$hint.Size = New-Object System.Drawing.Size(616, 40)
$hint.ForeColor = [System.Drawing.Color]::Gray
$hint.Text = '이 런처를 닫아도 켜 둔 창들은 계속 돈다. 노트북을 재부팅하면 다시 켠다. 깔끔히 끄려면 각 창에서 Ctrl+C.'
$form.Controls.Add($hint)

function Set-Msg([string]$Text) { $msg.Text = $Text }

function Update-Status {
  foreach ($k in $COMPONENTS.Keys) {
    $c = $COMPONENTS[$k]
    if (Test-Listening $c.Port) {
      $statusLabels[$k].Text = ('● 떠 있음  (:{0})' -f $c.Port)
      $statusLabels[$k].ForeColor = [System.Drawing.Color]::ForestGreen
    }
    else {
      $statusLabels[$k].Text = ('○ 꺼짐  (:{0})' -f $c.Port)
      $statusLabels[$k].ForeColor = [System.Drawing.Color]::Gray
    }
  }
}

# ---- 켜기: 브로커 → Collector → Prometheus → 가용성 판정기(브로커가 열린 뒤)
$btnStart.Add_Click({
  $sel = @($COMPONENTS.Keys | Where-Object { $checks[$_].Checked })
  if ($sel.Count -eq 0) { Set-Msg '켤 구성요소를 하나 이상 고른다.'; return }
  $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
  $msgs = @()
  foreach ($k in $sel) {
    $c = $COMPONENTS[$k]
    if (Test-Listening $c.Port) { $msgs += ('{0}: 이미 떠 있음' -f $c.Label); continue }
    if ($k -eq 'availability') {
      $waited = 0
      while (-not (Test-Listening 1883) -and $waited -lt 10000) {
        Start-Sleep -Milliseconds 500
        $waited += 500
        [System.Windows.Forms.Application]::DoEvents()
      }
      if (-not (Test-Listening 1883)) { $msgs += ('{0}: 브로커(1883)가 안 떠 있어 켜지 않았다 - 브로커부터 켠다' -f $c.Label); continue }
    }
    Open-PsWindow $RUN @('-Name', $k)
    $msgs += ('{0}: 켬' -f $c.Label)
    Start-Sleep -Milliseconds 800
    [System.Windows.Forms.Application]::DoEvents()
  }
  $form.Cursor = [System.Windows.Forms.Cursors]::Default
  Set-Msg ($msgs -join ' · ')
  Update-Status
})

# ---- 끄기: 켠 순서의 반대로, 강제 종료
$btnStop.Add_Click({
  $sel = @($COMPONENTS.Keys | Where-Object { $checks[$_].Checked })
  if ($sel.Count -eq 0) { Set-Msg '끌 구성요소를 하나 이상 고른다.'; return }
  $names = ($sel | ForEach-Object { $COMPONENTS[$_].Label }) -join ', '
  $ans = [System.Windows.Forms.MessageBox]::Show(
    ("다음을 강제 종료한다:`n{0}`n`n깔끔히 끄려면 「아니요」를 누르고 각 창에서 Ctrl+C 를 누른다." -f $names),
    'MK2 엣지 - 끄기', [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
  if ($ans -ne [System.Windows.Forms.DialogResult]::Yes) { return }
  $rev = @($sel)
  [array]::Reverse($rev)
  $msgs = @()
  foreach ($k in $rev) {
    $procs = @(Get-EdgeProcesses $k)
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    foreach ($w in @(Get-ComponentWindows $k)) { Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue }
    $msgs += ('{0}: 끔({1})' -f $COMPONENTS[$k].Label, $procs.Count)
  }
  Start-Sleep -Milliseconds 800
  Set-Msg ($msgs -join ' · ')
  Update-Status
})

$btnRefresh.Add_Click({ Update-Status; Set-Msg ('새로 봤다 - {0}' -f (Get-Date -Format 'HH:mm:ss')) })
$btnStatus.Add_Click({ Open-PsWindow $STATUS @(); Set-Msg ('상태 확인 창을 열었다 - 결과는 {0}\edge_status_*.txt 에도 남는다' -f $LOGS) })
$btnProbe.Add_Click({
  $ans = [System.Windows.Forms.MessageBox]::Show(
    "가짜 말단 관측을 1분 동안 이 노트북 Collector 로 보낸 뒤 상태 확인을 돌린다.`n가짜 시계열(hw-sensor-node · wl-edge-001 · edge-pc)이 엣지 Prometheus 에 15일 남는다.`n`n진행할까?",
    'MK2 엣지 - 관측 사슬 시험', [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
  if ($ans -eq [System.Windows.Forms.DialogResult]::Yes) { Open-PsWindow $PROBE @(); Set-Msg '관측 사슬 시험 창을 열었다 (약 1분 30초)' }
})
$btnProm.Add_Click({ Start-Process 'http://127.0.0.1:9090' })
$btnLogs.Add_Click({ Start-Process -FilePath 'explorer.exe' -ArgumentList $LOGS })
$btnManual.Add_Click({
  if (Test-Path -LiteralPath $MANUAL) { Start-Process -FilePath 'notepad.exe' -ArgumentList ('"{0}"' -f $MANUAL) }
  else { Set-Msg ('매뉴얼 파일이 없다: {0}' -f $MANUAL) }
})
$btnClose.Add_Click({ $form.Close() })

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 3000
$timer.Add_Tick({ Update-Status })
$form.Add_Shown({ Update-Status; $timer.Start() })
$form.Add_FormClosed({ $timer.Stop() })

[void]$form.ShowDialog()
