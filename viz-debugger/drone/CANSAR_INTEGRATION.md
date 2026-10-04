# CANSAR-2 연동 — 레이더 팀 코드(2026-10-04)를 드론 쪽에 붙인 것

레이더 팀에게 받은 `cansar_flight.py` · `cansar_quick.py` · README 세 개를 드론 쪽 시스템에 붙였습니다.
받은 파일은 `tests/data/cansar/` 에 그대로 두고 시험에 씁니다(고치지 않았습니다).

## 1. 레이더 팀이 부탁한 것 — 패스마다 quick-look 을 화면에

| 무엇 | 어떻게 |
|---|---|
| 돌리기 | Pi 의 드론 데이터 서버(`sar-data`)가 `passes.csv` 에 새 줄이 생기고 `iq_N.bin` · `meta_N.txt` 가 있으면 `cansar_quick.py --nopull …` 을 실행 (`sar_data/quick.py`) |
| 지킨 것 | `nice -n 19` · `--fine` 안 씀 · **CAP_ON 이 있으면 미룸** · 한 번에 하나 · 패스마다 따로 만든 작업 폴더(flight_img.png 겹침 없음) · 명령 형식과 `quick_N.png` · `quick_N.npz` 이름만 사용 |
| 화면 | SAR 패스 화면에 「레이더 팀 영상 · quick-look」 카드. 영상 · `[판정]` 줄 · `영상 첨두` 줄 · 처리 기록 · npz 받기 (`screenshots/34_레이더팀_quicklook.png`) |
| 노트북 · 서버 | 노트북 미러가 결과(png · npz · 기록)를 받아 가므로 Pi 에 직접 붙지 않아도 보입니다 |
| 실패 | 0 이 아닌 종료면 「실패」 + 마지막 오류 줄 + 처리 기록 링크 |

Pi 설정(`/etc/sar-drone.env`):

```bash
SAR_CANSAR_QUICK=/home/physical/cansar_radar/cansar_quick.py   # cansar_flight.py 와 같은 폴더 (레이더 팀이 정함)
SAR_CANSAR_DATA=/home/physical/flight
SAR_CANSAR_LOGS=/home/physical/cansar_logs
SAR_CANSAR_SIDE=right            # 안테나가 보는 쪽 — 비행 전에 레이더 팀이 정한다
```

`sudo systemctl restart sar-data` 뒤 `curl http://<Pi>:8766/api/cansar` 로 목록이 보이면 됩니다.

## 2. 드론 쪽 영상 파이프라인에도 넣었다 — `sar_image/cansar.py` (어댑터 `sar_image.cansar:load`)

같은 원시를 **드론 쪽 RTK 궤적 · 레버암 · 리플렉터 검증 · 패스 비교 · mm 변위 · GPU 자동 초점**에 넣습니다
(그쪽 quick-look 은 FC 의 LOCAL_POSITION_NED 를 씁니다). 그쪽 처리와 다르게 한 점:

- 거리 압축을 **보간 없이** 실제 주파수로 직접 합한다 — 그쪽 4096 칸 선형 보간은 먼 표적을 깎는다(60 m −5.7 dB · 80 m −10.7 dB)
- 부대역 0~7 이 다 있는 스윕만 쓰고, 시각은 파일 안 행 위치로 — 표시 행이 빠져도 뒤 스윕이 밀리지 않는다
- 시각은 Pi 시계(events.csv) → 파이프라인이 비행 기록의 Pi−FC 차이로 **FC GPS 시각**으로 바꾼다
- Pi 에서 패스마다 거리 압축으로 줄여 둠(`SAR_REDUCE_ADAPTER=sar_image.cansar:load`) → 노트북 · 서버는 줄인 것만 받음
- 레이더 설정 예시: `sar_image/example_radar_cansar.json` (가운데 5.684 GHz, 대역 368 MHz)

가짜 CANSAR-2 비행(그쪽 형식 그대로, `cansar.write_fake`)으로 확인한 것:

| | 결과 |
|---|---|
| 그쪽 `cansar_quick.py` 가 우리 가짜 파일에서 그대로 도나 | 됩니다 — 가장 밝은 리플렉터를 제자리(진행 +4.1 m, 옆 24.0 m)에서 찾음 |
| 드론 쪽 파이프라인 | 리플렉터 4/4 제자리(오차 0.0 m) · 진행 방향 해상도 3.3 cm · 옆 15 cm · 첨두 대비 부엽 −32 ~ −35 dB · 시각 어긋남 0 |

## 2.5 자동 초점 견주기 — 그쪽 엔트로피 방식(`--af`)을 GPU 로 이식 (`sar_image/gpu.py` · `af_compare.py`)

가짜 CANSAR 비행, 실제 궤적이 기록(RTK)과 사인파로 옆 3 cm · 위 2 cm 어긋남(주기 8 s), 리플렉터 4개 중앙값:

| 방법 | 위치 오차 | 진행 해상도 | 옆 해상도 | PSLR |
|---|---|---|---|---|
| 초점 없음 | 0.154 m | 5.7 cm | 24 cm | −3.8 dB |
| 리플렉터(이어 붙이기) | 0.068 m | 3.5 cm | 16 cm | −2.3 dB |
| **엔트로피(리플렉터 좌표 안 씀)** | **0.042 m** | **3.4 cm** | 17 cm | **−15.6 dB** |
| (참고) 오차 없을 때 | 0.0 m | 3.3 cm | 15 cm | −32 ~ −35 dB |

- 그쪽 기본 학습률 0.05 m 는 파장(5.3 cm)만 해서 한 걸음에 최적점을 건너뛴다 → 0.003 m · 매듭 16 · 120 번으로 바꿨다.
- 창 하나 · 수평 보정만이라 높이 오차는 다 못 지운다 — 창 여러 개 · 높이 성분을 넣는 것이 다음 일(논문 ①).
- 리플렉터 4개가 동시에 빔에 드는 구간이 짧으면 3차원 리플렉터 방식은 오히려 나빠져서(0.16 → 0.81 m), 이어 붙이기로 내려가게 고쳤다.

## 3. 레이더 팀에 드리는 의견 · 질문

1. **quick 의 `--dec 8` 과 방위 앨리어싱.** 가짜 데이터(PRF 234 Hz, 4 m/s, 빔 30°)에서 `--dec 1` 은 리플렉터 4개가 깨끗하지만
   `--dec 2` 부터 유령 줄무늬, `--dec 8` 은 줄무늬에 묻힙니다(`screenshots/35_cansar_dec_비교.png`).
   진행 방향 표본 간격(= 속도 / (PRF / dec))이 벌어지면 생깁니다. 가짜에서 1.7 cm(dec 1)는 깨끗, 3.4 cm(dec 2)부터 유령 —
   3 dB 빔폭만 보면 5 cm 까지 될 것 같지만 빔 가장자리 · 넓은 영상 구역까지 받으니 λ/4 ≈ 1.4 cm 에 가까울수록 안전합니다.
   **실제 유효 PRF** 를 알려 주시면 그 값에 맞는 dec 를 같이 정하겠습니다(GPU 를 쓰면 dec 를 낮춰도 빠릅니다).
2. **빛의 속도 `c = 3e8`.** 실제 값(299 792 458)과 0.07 % 차이라, 25 m 에서 위상 기준이 수 rad 어긋나고 개구 안에서 0.3 rad 남짓
   흐려집니다. 드론 쪽 어댑터는 실제 값을 씁니다. 바꾸셔도 거리 축 · 위상이 같이 맞습니다.
3. **표시 행(0x5A5A)이 하나 빠지면.** 지금은 부대역마다 k 번째를 같은 스윕으로 짝지어 그 뒤 스윕이 전부 밀립니다.
   드론 쪽 어댑터는 순서(0→7)가 끊긴 곳을 세어 알려 줍니다. 스윕 번호(카운터)를 원시에 같이 적어 주시면 정확히 고칠 수 있습니다.
4. **궤적.** quick 은 FC 의 LOCAL_POSITION_NED(IMU 자리)를 씁니다. 안테나는 IMU 에서 떨어져 있어 기울면 위치가 바뀝니다(레버암).
   드론 쪽은 RTK 궤적 + 레버암으로 계산합니다. 안테나 위치(FC 기준 앞 · 오른쪽 · 아래 m)를 재 주시면 둘 다에 쓰겠습니다.
5. **확인할 것**
   - `roff` 0.4 m 는 장비 내부 지연 실측값인가요? (드론 쪽도 같은 값을 씁니다)
   - CAP_ON 으로 캡처를 켜고 끄나요? CAP_ACK 를 쓰나요? (드론 쪽이 패스 시작 · 끝에 CAP_ON 을 만들고 지웁니다)
   - Pi 에서 `cansar_quick.py` 를 둘 경로(`SAR_CANSAR_QUICK`)
   - ~~캡처 번호 N 이 시각(HHMMSS)이면 날이 바뀔 때 겹칠 수 있습니다~~ → 일련번호라 겹치지 않음(답변 받음)

## 4. 레이더 팀 답변 (2026-10-04) · 정한 것

| 항목 | 답 | 드론 쪽 반영 |
|---|---|---|
| 유효 PRF | **약 437 Hz** (부대역 8개 한 바퀴, 지상 12 s 캡처). 5 m/s 에서 스윕 간격 dec 1 = 1.1 cm · dec 2 = 2.3 cm · dec 8 = 9.2 cm (λ/4 = 1.3 cm) | `example_radar_cansar.json` prf_hz 437 |
| `--dec 8` | 첫 비행(0.34 m/s) 기준값이었다 → quick 이 속도 · PRF 로 dec 자동 선택하게 고침(그쪽) | 드론 쪽 파이프라인은 처음부터 솎지 않는다 |
| c = 3e8 · 보간 · 마커 묶기 | 셋 다 그쪽이 드론 쪽 방식으로 고침 | — |
| 스윕 카운터 | 다음 HDL 작업 때 마커 행 빈 열에 | 들어오면 어댑터에서 쓴다 |
| roff | 실내 CR 실측 0.4 m, 지금 케이블 구성은 약 0.24 m → **0.24~0.4 m, 비행 중 CR 로 다시 보정** | 리플렉터로 roff 를 추정하는 도구(아래 5) |
| CAP_ON | 드론 쪽 비행 스크립트가 만들고 지운다 — 그대로 | CAP_ON 안에 패스 번호 · 비행 이름 · 시각(JSON 한 줄)을 적기 시작 |
| CAP_ACK | 없음, 필요하면 그쪽 Pi 서비스에 넣는다 | **넣어 주세요** — 형식은 아래 |
| quick 경로 | `/home/physical/cansar_radar/` (cansar_quick.py · cansar_flight.py) | env 기본값으로 넣음 |
| 캡처 번호 N | SD 카드 최대 번호 + 1 일련번호 — 겹치지 않음 | — |
| 안테나 방향 · 레버암 | 비행 전에 재서 알려 줌 | 받으면 radar.json · SAR_CANSAR_SIDE |
| Pi 에서 dec 1 quick | 느리다 → 영역 줄이거나 드론 쪽 GPU 파이프라인에 맡김 | **드론 쪽 영상이 주 영상**, Pi quick-look 은 참고 |

### 레이더 팀에 부탁 (남은 것)

1. **CAP_ACK** (그 전까지는 드론 쪽이 events.csv 의 start · stop 줄로 대신 잰다 — `SAR_CAP_EVENTS`) — 기록을 실제로 시작한 직후 `/home/physical/CAP_ACK` 에 그 순간 `time.time()` 을 한 줄로 쓰고, 멈춘 직후 지운다.
   드론 쪽은 이것으로 레이더 지연을 재서 다음 패스부터 그만큼 미리 켠다(이미 들어 있음).
2. **CAP_ON 내용 같이 적기** — CAP_ON 파일 안의 JSON(`pass` · `flight`)을 passes.csv 나 meta_N.txt 에 한 칸 더 적어 주면
   드론 패스와 캡처를 정확히 짝짓는다.
3. **시계 짝을 1 초마다** — 기록 중 1 초마다 events.csv 에 `clock,<pi_epoch>,<sdr_uptime>` 한 줄. 지금은 캡처마다 start 한 줄뿐이다.
   (PPS 없이도 시각 어긋남을 ms 안으로 잡는 가장 싼 방법)

## 5. 레이더 팀 처리 코드 v2 (2026-10-04 오후) — 받아서 붙임

`tests/data/cansar/` 를 v2 로 바꿨다(`CHANGES_v2.md`). 명령 형식 · 결과 이름 · 표준 출력의 `[판정]` · `영상 첨두` 줄이 그대로라
드론 쪽 quick-look 실행(`sar_data/quick.py`)은 손대지 않고 돈다(시험 통과). Pi 에는 `/home/physical/cansar_radar/` 에 v2 두 파일을 둔다.

| v2 변경 | 드론 쪽 |
|---|---|
| c 정확값 · 온전한 묶음만 · 행 위치로 시각 · 보간 없는 거리 압축 · 학습률 0.003 | 드론 쪽 어댑터와 같은 방식이 됐다 — 두 영상이 같은 원리로 비교된다 |
| dec 자동(속도 · PRF 437 Hz → 3~5 m/s 에서 dec 1) | Pi CPU 에서 느려질 수 있다 — 드론 쪽은 캡처 중엔 미루고 nice 19 로 돌린다(시한 15 분) |
| `--lever F R D` | **드론 쪽 radar.json 의 antenna_offset_m 을 그대로 넘긴다**(`sar-data` 가 `--radar-json` 을 읽음) — 실측하면 radar.json 하나만 고친다 |
| `--roi`, npz 에 h0 · cN · cE · lever · breaks | 화면은 지금처럼 quick.png · 판정 · 첨두만 보인다 |

## 6. 레이더 브리지(cansar_pi.py · cansar.service) — 받아서 본 것 · 제안 (`radar_team/`)

Pi 에서 도는 레이더 팀 프로그램: CAP_ON 을 보고 **SSH 로 SDR 에 캡처를 켜고 끔**, SDR SD → `~/flight` 복사, events · passes · mav 기록,
패스 판정, **RTK 보정 중계(UDP 14660)**.

| 찾은 것 | 영향 | 제안 |
|---|---|---|
| RTK 중계가 드론 쪽 `sar-rtk` 와 같은 UDP 14660 | 포트 다툼 · 보정 두 번 | **지금은 레이더 브리지 것**(레이더 팀 실험 중) — 드론 쪽은 `SAR_RTK_RELAY=auto` 로 비켜 있고 화면에 「레이더 브리지가 넣는 중」. 통합 비행 때 합의 후 드론 쪽으로(`--rtcm-port 0` · `SAR_RTK_RELAY=on`) |
| events `pi_epoch` = SSH **보내기 전** 시각, `sdr_uptime` = 접속 **뒤** | 접속 시간(수백 ms)만큼 시각 어긋남(4 m/s 에서 1 m 안팎) — 지금은 리플렉터로 찾아 고친다 | 응답 시각으로 + ControlMaster + 1 초 clock 행 |
| `/proc/uptime` 은 0.01 s 눈금 | 한 번 읽으면 ±5 ms | clock 행 여러 개로 직선 맞춤(드론 쪽 어댑터가 함) |
| CAP_ACK 없음 · pass 번호 없음 | 레이더 지연 · 짝짓기를 짐작 | `--ack` · passes.csv 에 pass · flight |

제안 판 `radar_team/cansar_pi.py` · `cansar.service` · 차이 `cansar_pi.diff` · 설명 `radar_team/README.md`. 가짜 SDR 로 원본 · 제안 둘 다 시험.
제안 판을 쓰면 드론 쪽 `/etc/sar-drone.env` 에 `SAR_CAP_ACK=/home/physical/CAP_ACK`.
