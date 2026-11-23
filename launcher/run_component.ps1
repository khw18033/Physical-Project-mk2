# MK2 엣지 — 구성요소 하나를 이 창에서 띄운다 (2026-11-23)
# 런처가 구성요소마다 새 PowerShell 창으로 이 파일을 부른다:
#   powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File C:\mk2_edge\launcher\run_component.ps1 -Name <이름>
# 이름: mosquitto · otelcol · prometheus · availability
# 명령은 엣지 구축 때(2026-11-20) 손으로 띄운 것과 같다 — 설정 파일을 새로 쓰지 않고 있는 것을 읽는다.
# 끌 때는 이 창에서 Ctrl+C (창은 남는다 — 로그를 보고 닫는다).
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('mosquitto', 'otelcol', 'prometheus', 'availability')]
  [string]$Name
)

. (Join-Path $PSScriptRoot 'edge_common.ps1')

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$c = $COMPONENTS[$Name]
$Host.UI.RawUI.WindowTitle = $c.Title
New-Item -ItemType Directory -Force $LOGS | Out-Null
$stamp = Get-Date -Format yyMMdd_HHmm

Write-Host ("== {0} - {1}" -f $c.Title, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
if (Test-Listening $c.Port) {
  Write-Host ("포트 {0} 이 이미 쓰이고 있다 — 같은 프로그램이 벌써 떠 있는 것으로 보고 띄우지 않는다." -f $c.Port)
  Write-Host "이 창은 닫아도 된다."
  return
}

try {
  switch ($Name) {
    'mosquitto' {
      Set-Location $EDGE
      Write-Host "설정 $MOSQ_CONF · 로그 파일 $LOGS\mosquitto.log (Mosquitto 가 직접 쓴다)"
      Write-Host "파이가 꺼져 있으면 'Connecting bridge … / next backoff' 줄이 계속 반복된다 — 정상이다."
      & $MOSQ_EXE -c $MOSQ_CONF -v
    }
    'otelcol' {
      Set-Location (Join-Path $EDGE 'obs')
      $log = Join-Path $LOGS "otelcol_$stamp.log"
      Write-Host "설정 $OTEL_CONF · 로그 $log"
      cmd /c "$OTEL_EXE --config=$OTEL_CONF 2>&1" | Tee-Object -FilePath $log
    }
    'prometheus' {
      Set-Location (Join-Path $EDGE 'obs')
      $log = Join-Path $LOGS "prometheus_$stamp.log"
      Write-Host "설정 $PROM_CONF · 저장 $PROM_DATA · 로그 $log"
      cmd /c "$PROM_EXE --config.file=$PROM_CONF --storage.tsdb.path=$PROM_DATA 2>&1" | Tee-Object -FilePath $log
    }
    'availability' {
      $env:PYTHONUNBUFFERED = '1'
      $env:PYTHONIOENCODING = 'utf-8'
      Set-Location $AVAIL_DIR
      $log = Join-Path $LOGS "availability_$stamp.log"
      Write-Host "브로커 127.0.0.1:1883 · /metrics :9105 · 로그 $log"
      cmd /c "$PY_EDGE -m availability --broker 127.0.0.1 --port 1883 --metrics-port 9105 2>&1" | Tee-Object -FilePath $log
    }
  }
}
finally {
  Write-Host ""
  Write-Host ("== 멈췄다 - {0}. 위 줄을 보고 창을 닫으면 된다." -f (Get-Date -Format 'HH:mm:ss'))
}
