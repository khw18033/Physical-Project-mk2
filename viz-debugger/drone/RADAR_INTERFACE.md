# 레이더 ↔ 드론 연동 규약 (초안 0.1)

레이더 팀(cansar)과 드론 파트가 맞춰야 하는 것을 한 장으로 정리했습니다. 칸마다 「누가」 를 적었고, ❓ 는 레이더 팀이 채워 주실 값입니다.

## 1. 캡처 신호 — CAP_ON / CAP_ACK (이미 합의된 것 + 부탁)

| 무엇 | 누가 | 내용 |
|---|---|---|
| `/home/physical/CAP_ON` | 드론 | 등속 구간에 들어서면 만들고, 감속 전 · 중단 · RTL · 예외 때 지운다 |
| CAP_ON 확인 주기 | 레이더 | ❓ ms (짧을수록 좋다 — 50 ms 이하 권장) |
| `/home/physical/CAP_ACK` | 레이더 | **실제 기록을 시작한 순간** `time.time()` 값을 글자로 써 넣고, 기록을 멈추면 지운다 |
| 기록 파일 이동 | 레이더 | 기록이 끝나고 ❓ 초 안에 `/home/physical/cansar_data/` 로 옮긴다 (데이터 서버가 시각으로 패스와 짝을 짓는다 — 지금 15 초 기다림) |

CAP_ON 은 「이 구간을 기록하라」는 **대략의** 신호입니다(파일 확인 방식이라 수십~수백 ms 흔들림).
**영상의 정밀한 시각은 아래 2 의 펄스 시각으로** 맞춥니다.

## 2. 시각 — 가장 중요

4 m/s 로 날 때 1 ms 는 4 mm 이고, X대역 초점 한계(λ/8)가 약 4 mm 입니다.

| 무엇 | 누가 | 내용 |
|---|---|---|
| Pi 시계 | 드론 | GPS PPS(Pi GPIO18) + FC GPS 시각으로 chrony 가 µs 수준으로 맞춘다 (`deploy/pi/pps/`) |
| **펄스(처프)마다 시각** | 레이더 | 원시 파일에 펄스마다 시각을 남긴다. 기준은 Pi 시계(`time.time()` 와 같은 UNIX 초, UTC) 또는 PPS 에 맞춘 레이더 클럭 ❓ |
| 시각을 찍는 순간 | 레이더 | 처프 시작 / 가운데 / ADC 첫 표본 중 무엇인지 ❓ |
| PPS 를 레이더 보드도 받나 | 레이더 | ❓ 받으면 레이더 클럭을 직접 GPS 에 맞출 수 있다 |

드론 쪽 영상 처리는 리플렉터로 레이더 시각 오프셋을 다시 재서 검산합니다(`sar_image/quicklook.py`).

## 3. 원시 데이터 — 어댑터 하나

드론 파트 영상 처리는 레이더 형식을 모릅니다. 아래 함수 하나만 맞춰 주시면 화면의 「영상 만들기」 가 그대로 돕니다.

```python
def load(raw_path: str, radar) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return pulse_times,   # (N,)  펄스 시각 — 2 의 기준(UNIX 초, UTC)
           range_axis,    # (M,)  균일 간격 경사거리 m
           rc             # (N,M) 복소 거리 압축 데이터
```

예시(FMCW 디처프 npz): `sar_image/adapters.py::fmcw_dechirped_npz`. 부탁: **리플렉터를 향해 몇 초 기록한 샘플 파일 1 개**.

## 4. 레이더 사양 — `radar.json`

| 칸 | 값 |
|---|---|
| `wavelength_m` (중심 주파수) · `bandwidth_hz` · `prf_hz` | ❓ |
| `range_min_m` · `range_max_m` (기록 거리) | ❓ |
| `side` (오른쪽 / 왼쪽) · `depression_deg` (내려다보는 각) | ❓ |
| `el_beamwidth_deg` · `az_beamwidth_deg` (3 dB 빔폭) | ❓ |
| `antenna_offset_m` (FC 보드 중심 → 위상중심, 앞 · 오른쪽 · 아래 m) | 장착 뒤 실측 |

화면 「SAR 패스 → 안테나」 에서 넣고 내려받을 수 있습니다.

## 5. 레이더 상태 → 화면 (새로 부탁)

화면이 「기록 중인지」 만이 아니라 「제대로 기록하고 있는지」 를 보도록, 레이더 프로그램이 1 초마다 상태를 내 주세요.
드론 파트가 만든 `sar_pass/radar_status.py` 를 불러 쓰면 됩니다(코드 몇 줄).

토픽 `zoneA/drone/<장비 id>/radar` · JSON · retained · 1 Hz

| 칸 | 형 | 뜻 |
|---|---|---|
| `schema_version` | `"radar-0.1"` | |
| `state` | `idle` · `armed` · `recording` · `error` | armed = CAP_ON 을 기다리는 중 |
| `recording` | bool | 지금 기록 중 |
| `file` | str | 지금 쓰는 파일 이름 |
| `pulses_per_s` | number | 실제로 받은 펄스 수 / 초 (PRF 와 같아야 한다) |
| `dropped` | int | 이번 기록에서 놓친 펄스 · 버퍼 넘침 |
| `buffer_pct` | number | 버퍼 찬 정도 % |
| `temp_c` | number | 레이더 보드 온도 |
| `time_source` | `pps` · `ntp` · `none` | 펄스 시각의 기준 |
| `pps_locked` | bool | PPS 에 맞춰져 있나 |
| `disk_free_gb` · `files_this_flight` | number | 저장 공간 · 이번 비행 파일 수 |
| `last_error` | str \| null | 마지막 오류 문구 |

화면: 상태판 「레이더」 칩 · SAR 패스 점검의 「레이더」 칸. 5 초 넘게 안 오면 「끊김」, `dropped > 0` · PRF 와 펄스 수가 5 % 넘게 다르면 주의.

## 6. 기구 · 전기 (레이더 팀 + 기구)

무게 ❓ g · 소비 전력 ❓ W · 전원 전압 ❓ V · Pi 와 연결(USB · 이더넷) ❓ · 레이더를 켰을 때 GPS 위성 수 · RTK 가 떨어지는지는
드론 파트가 지상 시험으로 잽니다(`python -m sar_pass emi`).
