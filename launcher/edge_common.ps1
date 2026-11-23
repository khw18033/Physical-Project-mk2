# MK2 엣지 — 경로 · 포트 · 공용 함수 한곳 (2026-11-23)
# 런처(edge_launcher.ps1) · 창(run_component.ps1) · 상태 확인(edge_status.ps1) · 관측 시험(edge_probe_test.ps1)이
# 이 파일을 점(.)으로 읽어 같은 값을 쓴다. 경로가 바뀌면 여기만 고친다.

$EDGE      = 'C:\mk2_edge'
$LOGS      = Join-Path $EDGE 'logs'
$LAUNCHER  = Join-Path $EDGE 'launcher'
# 매뉴얼은 판이 바뀌어도 런처를 안 고치게 - C:\mk2_edge 바로 아래의 가장 새 '올인원 매뉴얼' md 를 연다
$MANUAL    = Get-ChildItem -LiteralPath $EDGE -Filter '*올인원 매뉴얼*.md' -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $MANUAL) { $MANUAL = Join-Path $EDGE '261123 MK2 엣지 올인원 매뉴얼 v2.md' }

$MOSQ_EXE  = 'C:\Program Files\mosquitto\mosquitto.exe'
$MOSQ_SUB  = 'C:\Program Files\mosquitto\mosquitto_sub.exe'
$MOSQ_CONF = Join-Path $EDGE 'mosquitto_edge.conf'

$OTEL_EXE  = Join-Path $EDGE 'obs\otelcol-contrib.exe'
$OTEL_CONF = Join-Path $EDGE 'obs\otel-agent.yaml'

$PROM_EXE  = Join-Path $EDGE 'obs\prometheus-3.9.1.windows-amd64\prometheus.exe'
$PROM_CONF = Join-Path $EDGE 'obs\prometheus.yml'
$PROM_DATA = Join-Path $EDGE 'obs\prom_data'

$PY_EDGE   = Join-Path $EDGE 'venv\Scripts\python.exe'
$PY_PROBE  = Join-Path $EDGE 'venv_probe\Scripts\python.exe'
$AVAIL_DIR = Join-Path $EDGE 'hw\edge'
$BE_DIR    = Join-Path $EDGE 'Physical-Project-mk2'

# 구성요소 넷 — 켜는 순서대로. 떠 있는지는 그 프로그램이 듣는 포트로 본다.
$COMPONENTS = [ordered]@{
  mosquitto    = @{ Label = '브로커 (Mosquitto + 파이 브리지)'; Title = 'MK2 엣지 - 브로커 (Mosquitto + 파이 브리지)'; Port = 1883 }
  otelcol      = @{ Label = 'Collector (OpenTelemetry)';        Title = 'MK2 엣지 - Collector (OpenTelemetry)';        Port = 4317 }
  prometheus   = @{ Label = '엣지 Prometheus';                  Title = 'MK2 엣지 - Prometheus';                       Port = 9090 }
  availability = @{ Label = '가용성 판정기';                    Title = 'MK2 엣지 - 가용성 판정기';                    Port = 9105 }
}

function Get-ListenPids([int]$Port) {
  @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-Listening([int]$Port) {
  (Get-ListenPids $Port).Count -gt 0
}

# 그 구성요소의 프로그램 프로세스(창이 아니라 실제로 도는 것)
function Get-EdgeProcesses([string]$Name) {
  $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
  switch ($Name) {
    'mosquitto'    { @($all | Where-Object { $_.Name -eq 'mosquitto.exe' -and $_.CommandLine -like '*mosquitto_edge.conf*' }) }
    'otelcol'      { @($all | Where-Object { $_.Name -eq 'otelcol-contrib.exe' -and $_.ExecutablePath -eq $OTEL_EXE }) }
    'prometheus'   { @($all | Where-Object { $_.Name -eq 'prometheus.exe' -and $_.ExecutablePath -eq $PROM_EXE }) }
    'availability' { @($all | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -like '*-m availability*' }) }
    default        { @() }
  }
}

# 런처가 띄운 창(run_component.ps1 을 도는 PowerShell)
function Get-ComponentWindows([string]$Name) {
  @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -like '*run_component.ps1*' -and $_.CommandLine -like "*-Name $Name*" })
}

# 응답 본문을 UTF-8 로 읽는다(Invoke-WebRequest 가 글자 인코딩을 다르게 읽어 한글 HELP 가 깨지는 것을 피한다)
function Get-HttpText([string]$Url) {
  $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $Url
  [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
}
