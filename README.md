# 피지컬팀 프로젝트 mk2 — 하드웨어(HW) 파트

재난 대응 IoT 텔레메트리 시스템의 **말단↔엣지 구간** 구현. 담당: 조병현

## 시스템 구조 (현재 구현 범위)

```
[말단 = 라즈베리파이(wl-001)]        [엣지 대역 = 노트북]              [엣지 로직 대역]
 pi/sensor_node.py    ──MQTT 5.0──►   Mosquitto 브로커     ──────►     pi/monitor.py
 (수위센서 노드)         └─OTLP──►    (발행/구독 중계)                  (생사 판정·상태 3층)
                                      Collector(예정)
```

전체 아키텍처는 3계층(말단 → 엣지 → 서버)이며, 말단↔엣지는 MQTT(업무·명령·하트비트) +
OpenTelemetry OTLP(관측), 엣지↔서버는 Kafka. 근거 문서: `피지컬팀 프로젝트 mk2.xlsx`
(요구사항 정의서), `데이터 전송 및 아키텍처 v4`, `캡스톤MK2 요구사항 통합정립본 v3`.
상세 계획·진행 기록은
[`하드웨어_구현_착수순서_계획.md`](./하드웨어_구현_착수순서_계획.md) 참조.

## 구현 현황 (2026-08-31 기준)

요구사항 정의서 기준 HW 30건 중 말단 노드 단독으로 가능한 범위는 모두 구현·검증했다.

| Phase | ID | 내용 | 상태 |
|---|---|---|---|
| 0 | HW-S-08 | NTP 시각 동기화 (chrony) + 전 메시지 타임스탬프 | ✅ |
| 0 | HW-C-07 | device_id 채번 + **네트워크·구역 변경 시 재등록** | ✅ |
| 0 | HW-C-01 | 전송 인터페이스 — **MQTT 5.0 적용**, TLS는 설정 자리만 | ◐ TLS 대기 |
| 0 | HW-C-02 | 표준 메시지 규격 — **BE-C-01/C-02 필드로 정렬**(`schema.py`) | ◐ 백엔드 확정 대기 |
| 1 | HW-C-04 | Birth/Death + **상태 요약 10초 주기** | ✅ |
| 1 | HW-S-05 | 하트비트 **1 Hz** | ✅ |
| 1 | HW-C-06 | 명령 수신·ACK + **결과 4단계 승격**(BE-X-03) | ✅ |
| 1 | HW-S-07 | 오프라인 판정 — LWT + 4회 미수신(**4초**) 이중 감지 | ✅ |
| 2 | HW-S-02 | 평시 60초 + 임계 초과·해제·**급변** 즉시 발행 | ✅ (가짜 센서) |
| 2 | HW-S-01 | 실센서 계측값 수집 | ⏳ 조달 대기 — `read_water_level()`만 교체 |
| 4 | HW-S-03 | 이벤트 모드 1 Hz 고주기 보고 | ✅ (컨테이너 연계는 Phase 4) |
| 4 | HW-S-04 | 적응형 주기 전환 명령 수신 | ✅ |
| 6 | HW-R-09 | 두절 시 버퍼링·재전송 (`spool.py`) | ✅ |
| 6 | HW-C-05 | 관측 metric 5종 OTLP 발신 (`otel_metrics.py`) | ◐ 엣지 Collector 대기 |

미착수: HW-R-01~R-08·R-10(로봇 장비), HW-A-01~A-05(액추에이터), HW-S-06(CCTV),
HW-C-03(K3s) — 전부 장비·인프라 확보가 선행 조건.

## 파일 구성

- `pi/sensor_node.py` — 말단 노드 본체. 등록·하트비트·명령 4단계·계측 보고·주기 전환
- `pi/config.py` — **주기·임계값·브로커 주소 단일 지점.** 전부 `HW_*` 환경변수로 덮어쓰기 가능
- `pi/schema.py` — 메시지 봉투 어댑터. 백엔드 스키마 확정 시 **이 파일만** 고치면 됨
- `pi/spool.py` — 두절 시 디스크 버퍼링·순서 보존 재전송 (HW-R-09)
- `pi/otel_metrics.py` — 노드 자기 관측 metric 5종 (HW-C-05). SDK·엔드포인트 없으면 no-op
- `pi/monitor.py` — 엣지 대역 감시. 오프라인 판정 + 상태 3층 관찰
- `pi/sensor-node.service` — systemd unit (부팅 자동 시작)
- `pi/hw-node.env.example` — 현장 설정 템플릿. `/etc/hw-node.env` 로 복사해 값만 채운다
  (브로커 IP·구역 같은 현장값을 저장소에 박아두면 현장마다 서로를 덮어쓴다)
- `pi/pi_base_setup.sh` — 라즈베리파이 공통 베이스 셋업
- `하드웨어_구현_착수순서_계획.md` — Phase 계획 + 결정사항 + 진행 기록 (기준 문서)

## 채널(토픽) 구조

`{zone}/{type}/{entity}/{channel}` — 통합정립본 v3의 `{domain}/{type}/{id}/{channel}` 정렬

| 채널 | QoS | retained | 내용 |
|---|---|---|---|
| `.../status` | 1 | ○ | 등록(birth)·10초 요약(summary)·재등록(rebirth)·종료(shutdown/death) |
| `.../heartbeat` | 0 | | 1 Hz 생존 신호 |
| `.../state` | 1 | | 계측 보고 (periodic / threshold_exceeded / threshold_cleared / rapid_change) |
| `.../cmd` | 1 | | 명령 수신 |
| `.../cmd/ack` | 1 | | 1단계: accepted / rejected |
| `.../cmd/result` | 1 | | 2~4단계: executing → state_changed → completed / failed |

QoS 근거: 계측·명령 결과는 유실 불가라 QoS 1, 하트비트는 다음 신호가 곧 오므로 QoS 0.
status·heartbeat는 "지금"의 값이라 두절 시 버퍼에 넣지 않는다(낡은 상태로 retained를
덮어쓰면 오히려 해롭다). state·cmd 결과만 버퍼링 대상.

## 실행 방법

말단 사전조건: `pi_base_setup.sh` 완료(chrony, `/etc/device_id`, cgroup,
venv에 paho-mqtt·opentelemetry-sdk·psutil).

1. 브로커 (임시: 노트북, 최종: 엣지노드)

   ```
   mosquitto -c test.conf -v      # test.conf: listener 1883 0.0.0.0 / allow_anonymous true
   ```

2. 노드 실행 — `pi/` 디렉터리에서 실행해야 한다(형제 모듈을 import 한다)

   ```
   cd pi && python3 sensor_node.py
   cd pi && python3 monitor.py          # 별도 세션 (엣지 대역)
   ```

3. 부팅 자동 시작 (실제 운용 형태)

   ```
   sudo cp pi/sensor-node.service /etc/systemd/system/
   sudo cp pi/hw-node.env.example /etc/hw-node.env   # 현장값 기입
   sudo systemctl daemon-reload && sudo systemctl enable --now sensor-node
   journalctl -u sensor-node -f
   ```

설정은 코드가 아니라 `/etc/hw-node.env` 또는 환경변수로 바꾼다 — 예:
`HW_BROKER_HOST=10.0.0.5 HW_HB_INTERVAL=5 HW_OTEL_ENDPOINT=http://10.0.0.5:4317 python3 sensor_node.py`

### 테스트 시나리오 (2026-08-31 라즈베리파이 pi7 실기 검증 완료)

```bash
T=zoneA/sensor/wl-001/cmd
# 명령 4단계 (물리 명령): accepted → executing → state_changed → completed
mosquitto_pub -h <IP> -t $T -q 1 -m '{"command_id":"c1","action":"levee","params":{"position":"open"}}'
# 설정 명령 (물리 단계 없음, physical:false): accepted → executing → completed
mosquitto_pub -h <IP> -t $T -q 1 -m '{"command_id":"c2","action":"set_mode","params":{"mode":"event"}}'
# 거부 경로: command_id 누락 / 미지원 action / 만료 / 잘못된 파라미터
mosquitto_pub -h <IP> -t $T -q 1 -m '{"action":"ping"}'
mosquitto_pub -h <IP> -t $T -q 1 -m '{"command_id":"c3","action":"self_destruct"}'
# 중복 배달: 같은 command_id 재전송 → 재실행 없이 이전 ACK만 재송신
mosquitto_pub -h <IP> -t $T -q 1 -m '{"command_id":"c1","action":"levee","params":{"position":"open"}}'
```

- **강우(임계·급변)**: `touch /tmp/rain` → 임계 3.0m 도달 **전에** `rapid_change` 먼저
  발행되고, 3.0m 돌파 시 `threshold_exceeded` + 자동으로 event 모드(1 Hz) 전환.
  `rm /tmp/rain` → 2.9m 미만에서 `threshold_cleared` + normal 복귀
- **급사(LWT)**: `sudo pkill -9 -f '[s]ensor_node'` → 즉시 LWT
  `event:death, reason:lwt, device_status:fault` → systemd가 3초 내 자동 재기동
- **계획된 종료**: `sudo systemctl stop sensor-node`(SIGTERM) 또는 `Ctrl+C` →
  `event:shutdown, reason:graceful_shutdown` (장애와 의도적 종료를 구분해야
  가시화가 VZ-U-01 상태 4종을 나눌 수 있다)
- **device_id 중복**: 같은 `device_id`로 두 노드를 띄우면 서로를 밀어내며 초당 재접속한다.
  20초 내 3회 이상 재접속하면 `[치명] ... 채번 대장 확인 필요` 경보
- **하트비트 타임아웃**: 브로커 종료 → monitor가 4초 내 `OFFLINE` 판정
- **두절 버퍼링**: 브로커 종료 15초 → 미전송분이 `spool.jsonl`에 적재 → 브로커 복구 시
  seq·타임스탬프 순서 그대로 재전송(`replayed: true` 표식)

## 임시값 (협의 후 교체 예정)

| 항목 | 현재값 | 확정 방법 |
|---|---|---|
| 토픽 prefix | `zoneA` | 백엔드와 `{domain}/{type}/{id}/{channel}` 도메인 체계 확정 |
| 하트비트 주기 | **1초** (요구사항 정의서 HW-S-05 기준) | 아키텍처 v4의 5초와 상충 — 협의 안건. `HW_HB_INTERVAL`로 즉시 변경 가능 |
| OTel export | **60초** (HW-C-05 기준) | 계획서 초안 15초와 상충 — 정의서 채택 |
| 스키마 필드 | `source_id`+`device_id` 병기 | BE-C-01 확정 시 `schema.LEGACY_DEVICE_ID=False` |
| 브로커 위치 | 노트북 | 엣지노드 구축 후 이전 |
| 인증·TLS | 없음(allow_anonymous) | 엣지 인증서 준비 시 `HW_TLS_CA` 등만 설정 |

## 다음 할 일

백엔드 협의(토픽 체계·스키마 필드 확정 + 하트비트 주기 + G2/G3 회신), 엣지노드 구축
후 브로커·OTel Collector 이전, K3s 클러스터 구축(HW-C-03), 장비 입고 후 로봇(HW-R)·
액추에이터(HW-A)·CCTV(HW-S-06).
