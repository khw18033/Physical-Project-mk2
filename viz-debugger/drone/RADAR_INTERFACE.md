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

무게 ❓ g · 소비 전력 ❓ W · 전원 전압 ❓ V · Pi 와 연결 = 기가비트 이더넷 · 레이더를 켰을 때 GPS 위성 수 · RTK 가 떨어지는지는
드론 파트가 지상 시험으로 잽니다(`python -m sar_pass emi`).

## 7. SDR (Zynq-7020 + AD9361) 일 때

레이더가 AD9361 SDR 이라 위 항목이 이렇게 구체화됩니다. 드론 파트가 먼저 제안하는 형식 · 코드가 있고, 맞지 않으면 바꾸면 됩니다.

### 확인해 주실 것

| 항목 | 값 | 왜 |
|---|---|---|
| 보드 이름 · 펌웨어 | ❓ (Pluto 계열 libiio / UHD 계열) | 시각 표시(time_spec) 지원 여부가 갈린다 |
| **PPS · 10 MHz 기준 입력** 단자 | ❓ 있음 / 없음 | 있으면 GPS PPS 를 보드에 직접 — 표본마다 GPS 시각 |
| Pi 와 연결 | **기가비트 이더넷** (확정) · 보드 IP ❓ | 실효 약 110 MB/s — 20 MS/s 복소 16 비트(80 MB/s)까지 여유. 30 MS/s 이상은 FPGA 에서 자르거나 줄인다 |
| 중심 주파수 · 대역폭 · 표본화 | ❓ GHz · ❓ MHz · ❓ MS/s | AD9361 은 70 MHz–6 GHz, 순간 대역 최대 56 MHz |
| 파형 | ❓ 처프 길이 · PRF · 업/다운 · 송수신 안테나 분리 | 정합 필터 기준 신호 |
| 기록 방식 | ❓ 연속(stream) / 펄스마다 잘라서(gated, FPGA) | gated 면 데이터가 수백 배 준다 |
| 기록 위치 | ❓ 보드 SD · Pi SSD | SD 카드는 수십 MB/s 를 오래 못 버틴다 |

### 기가비트 이더넷 연결 — 맞춰 둘 것

- Pi 5 의 유선 포트는 SDR 전용으로 쓴다(지상국은 핫스팟 WiFi). 두 망의 주소 대역이 겹치지 않게 한다
  (예: SDR `192.168.2.1`, Pi 유선 `192.168.2.10/24`, 핫스팟은 다른 대역). 유선 쪽에는 기본 경로(gateway)를 두지 않는다.
- Pi 설정 `/etc/sar-drone.env` 에 `SAR_SDR_HOST=192.168.2.1` 을 넣으면 `python -m sar_pass check` 가 연결 속도(1000 Mb/s)와
  SDR 응답(iiod 30431 또는 `SAR_SDR_PORT`)을 점검하고, 상태판 「Pi」 칩 설명에 유선 속도 · 오류가 나온다.
- **Pi 저장장치가 병목**: SD 카드는 오래 쓰면 수십 MB/s 로 떨어진다. 80 MB/s 로 받으면 NVMe(Pi 5 HAT) 나 USB 3 SSD 에 기록한다.
  또는 SDR 보드 쪽 SD 에 기록하고 Pi 는 줄인 것(거리 압축)만 받는다.

### 시각 — 표본 수가 시계다

libiio 처럼 표본에 시각이 붙지 않으면 **t = t0 + (표본 번호) / fs** 로 시각을 만든다. 그래서
1) **t0(첫 표본의 시각)** 를 정확히 — PPS 에 맞춰 시작하거나, 시작 순간을 Pi 시계(PPS 동기)로 찍는다
2) **표본이 하나도 빠지면 안 된다** — 빠지면 그 뒤 시각이 전부 밀린다. 빠진 곳(위치 · 개수)을 기록해 주면 고쳐 쓴다
AD9361 기준 발진기 오차(수 ppm)는 20 초 패스에 수십 µs 라 괜찮다.

### 제안 원시 형식 — `sar_image/sdr.py`

`<이름>.npy`(complex64 또는 int16 I/Q) + 같은 이름 `.json`(fs · fc · t0 · 처프 · stream/gated · 빠진 표본) + gated 면 `_idx.npy`(FPGA 펄스 계수).
어댑터 `sar_image.sdr:iq_npy` 가 정합 필터로 거리 압축한다. 가짜 데이터 생성기 `sdr.write_fake` 로 형식을 맞춰 볼 수 있다.

### 데이터 양 — Pi 에서 줄여 보낸다

Pi 데이터 서버에 `--reduce-adapter sar_image.sdr:iq_npy --radar-json …` 를 주면 패스마다 원시를 거리 압축 파일로 줄인다
(시험: 120 MB → 0.1 MB). 노트북은 줄인 것만 핫스팟으로 가져가 영상을 만든다. 원시는 Pi 에 그대로 남는다(비행 뒤 USB 로).

### 요구 정밀도가 바뀐다 (예시 X대역 → C/S대역)

| 주파수 | 파장 | λ/8 (초점 한계) | 거리 해상도(56 MHz) | RTK(1~2 cm)만으로 |
|---|---|---|---|---|
| 9.6 GHz (예전 예시) | 3.1 cm | 3.9 mm | — | 안 됨 (−13 dB) |
| 5.8 GHz | 5.2 cm | 6.5 mm | 2.7 m | 부족 — 리플렉터 자동 초점 필요 |
| 2.4 GHz | 12.5 cm | 15.6 mm | 2.7 m | 거의 됨 |

거리 해상도는 수 m(대역폭 한계), 방위 해상도는 수 cm 라 영상이 한쪽으로 긴 모양이 된다. 리플렉터 확인 · 위치 검증에는 충분하다.
예시 사양: `sar_image/example_radar_sdr.json` (5.8 GHz · 50 MHz).
