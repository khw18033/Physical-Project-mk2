# 피지컬팀 프로젝트 mk2 — 하드웨어(HW) 파트

재난 대응 IoT 텔레메트리 시스템의 **말단↔엣지 구간** 구현. 담당: 조병현
목표 시연: **안동 하천실험센터 UN 발표**

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/SRS.md`](./docs/SRS.md) | **소프트웨어 요구사항 명세서.** xlsx 30건을 검증 가능한 형태로 재기술, 타 파트 파생 제약, 타당성 검토 결과, 검증 매트릭스 |
| [`docs/SDD.md`](./docs/SDD.md) | **소프트웨어 설계 기술서.** 설계 원칙, 노드 3종 분할, 공통 코어, 주기 전환 3층, K3s 2층 배치, 장애 모드 |
| [`하드웨어_구현_착수순서_계획.md`](./하드웨어_구현_착수순서_계획.md) | Phase 계획 + 진행 기록 |
| `피지컬팀 프로젝트 mk2.xlsx` | 요구사항 정의서 (전 파트 공유) |

## 구조

```
┌─ 말단 (Raspberry Pi 5) ───────────────┐        ┌─ 구역 엣지노드 ──────────┐
│  systemd 층 — 안전 필수, 항상 상주      │        │  Mosquitto (MQTT 5.0)    │
│   ├ sensor-node   센서노드 wl-001      │─업무──►│  K3s server (제어평면)    │
│   ├ robot-node    로봇 온보드 rb-01    │─관측──►│  OTel Collector (Agent)  │
│   └ actuator-node 액추에이터 gate-01   │        │  미디어 게이트웨이 (예정)   │
│  k3s agent 층 — 증강 기능(AI·영상)     │◄─배포──│  ※ 전용 장비 확보 전        │
└────────────────────────────────────────┘        └──────────────────────────┘
```

**한 노드에 두 층이 공존한다.** 안전 루프(계측·임계 판정·자율 주기 전환·버퍼링)는
systemd 로 상주시키고, 증강 기능만 k3s 로 배포한다. k3s agent 는 제어평면에 연결되지
못하면 컨테이너를 기동조차 못 하므로, 안전 루프를 거기 넣으면 그 실패 모드를 상속한다
(근거: `docs/SRS.md` §9.2).

## 구현 현황 (2026-08-31, 라즈베리파이 pi7 실기 검증)

| 계열 | ID | 내용 | 상태 |
|---|---|---|---|
| 공통 | HW-C-01 | 전송 인터페이스 — MQTT 5.0 적용 | ◐ TLS 대기 |
| 공통 | HW-C-02 | 표준 메시지 규격 — BE-C-01/C-02 필드 정렬 | ◐ 백엔드 확정 대기 |
| 공통 | HW-C-03 | K3s 컨테이너 배포·제거·셀프힐링 | ✅ 검증 완료 (임시 엣지, 검증 후 철수 — `docs/EDGE_SETUP.md`) |
| 공통 | HW-C-04 | Birth/Death + 상태 요약 10초 | ✅ |
| 공통 | HW-C-05 | 관측 metric 5종 OTLP | ✅ 실 export 검증 (Collector 실물 대기) |
| 공통 | HW-C-06 | 명령 ACK + 결과 4단계 승격 | ✅ |
| 공통 | HW-C-07 | device_id 식별 + 변경 시 재등록 | ✅ |
| 센서 | HW-S-01 | 계측값 수집 | ⛔ 센서 조달 대기 (`read_sensor()`만 교체) |
| 센서 | HW-S-02 | 평시 60초 + 임계·해제·급변 즉시 | ✅ (가짜 센서) |
| 센서 | HW-S-03 | 이벤트 모드 1 Hz | ✅ |
| 센서 | HW-S-04 | 적응형 주기 전환 명령 | ✅ |
| 센서 | HW-S-05 | 하트비트 1 Hz | ✅ |
| 센서 | HW-S-06 | 고정 CCTV 15 fps | ⛔ 카메라·게이트웨이 부재 |
| 센서 | HW-S-07 | 오프라인 판정 (LWT + 4초) | ✅ |
| 센서 | HW-S-08 | 시각 동기 + 타임스탬프 | ✅ (오차 77µs) |
| 로봇 | HW-R-01 | 제어기→온보드 50 Hz 수집 | ◐ SimLink 로 검증, 실물 대기 |
| 로봇 | HW-R-02 | 하트비트 — 대기 중에만 | ✅ (임무 중 0 Hz 실측) |
| 로봇 | HW-R-03 | 상태 전달 임무 20 Hz / 대기 1 Hz | ✅ (실측 19.9 / 1.0 Hz) |
| 로봇 | HW-R-05 | 임무 수신·검증 | ✅ (4단계 + 거부 조건) |
| 로봇 | HW-R-06 | 제어 명령 내부 전달 | ◐ SimLink |
| 로봇 | HW-R-07 | 관제 영상 온디맨드 | ⛔ 제어 경로만, 미디어 부재 |
| 로봇 | HW-R-09 | 두절 버퍼링·재전송 | ✅ (이산/연속 정책 분리) |
| 로봇 | HW-R-04, R-08, R-10 | 온디바이스 AI·맵·모델 배포 | ⛔ AI 파트·K3s 의존 |
| 액추 | HW-A-01 | 상태 5종 구분(대기/동작중/완료/오류/**확인불가**) | ✅ SimActuator |
| 액추 | HW-A-02 | 사전 정의 물리 제어(수문·차수벽·펌프) | ✅ SimActuator |
| 액추 | HW-A-03 | 즉시 ACK + **ACK 이전** 거부 4종 | ✅ |
| 액추 | HW-A-04 | ACK와 물리 도달 구분, 20Hz 진행 보고 | ✅ SimActuator |
| 액추 | HW-A-05 | 안전 잠금 + 복구 후 실제 상태 재확인 | ✅ SimActuator |

## 파일 구성

```
pi/
├─ common/                 공통 코어 (HW-C) — 세 노드가 상속
│   ├─ config.py           주기·임계값·접속정보 단일 지점 (HW_* 환경변수)
│   ├─ schema.py           메시지 봉투 어댑터 + Identity 3계층  ← 백엔드 확정 시 여기만
│   ├─ spool.py            두절 버퍼 (이산 전량 / 연속 다운샘플)
│   ├─ otel_metrics.py     자기 관측 metric 5종
│   ├─ commands.py         명령 엔진 (검증·중복억제·4단계 승격)
│   └─ node.py             BaseNode (접속·Birth·하트비트·상태요약·식별자감시)
├─ sensor/sensor_node.py   센서노드 (HW-S)
├─ robot/
│   ├─ robot_node.py       로봇 온보드 (HW-R)
│   └─ controller_link.py  제어기 내부 링크 (SimLink / CAN / Ethernet)
├─ actuator/
│   ├─ actuator_node.py    액추에이터 제어노드 (HW-A) — 4단계·안전 잠금
│   └─ actuator_link.py    액추에이터 링크. 상태 5종 (unknown 을 close 와 뭉치지 않는다)
├─ edge/monitor.py         엣지 대역 감시 (HW-S-07 + 상태 3층)
├─ deploy/                 systemd unit + 현장 설정 + k8s 증강 워크로드 매니페스트
└─ pi_base_setup.sh        멱등 프로비저닝 (--role sensor|robot|actuator)
```

## 채널(토픽) 구조

`{zone}/{type}/{entity}/{channel}` — 예: `zoneA/sensor/wl-001`, `zoneA/robot/rb-01`,
`zoneA/actuator/gate-01`

| 채널 | QoS | retained | 내용 |
|---|---|---|---|
| `status` | 1 | ○ | birth / summary(10초) / rebirth / shutdown / death |
| `heartbeat` | 0 | | 1 Hz. 로봇은 임무 중 정지 |
| `state` | 센서·액추에이터 1 · 로봇 0 | | 계측·로봇 상태·액추에이터 상태 |
| `cmd` → `cmd/ack` → `cmd/result` | 1 | | 명령 4단계 |

**QoS가 갈리는 이유**: 센서 계측은 유실 불가라 QoS 1. 로봇 20 Hz 상태는 다음 표본이
50 ms 뒤 오므로 유실이 상쇄되고, QoS 1 왕복(무선 실측 ~150 ms)이 주기보다 길어 QoS 0.
**이산 사건**(모드 전환·배터리 경보·명령 결과)은 종류를 불문하고 QoS 1.

## 실행 방법

```bash
# 1) 말단 프로비저닝 (멱등)
cd pi && ./pi_base_setup.sh --entity wl-001 --node pi7 --zone zoneA \
                            --role sensor --broker <엣지IP>

# 2) 서비스 기동
sudo systemctl enable --now sensor-node
journalctl -u sensor-node -f

# 3) 엣지 대역 감시 (엣지노드 구축 후 그쪽으로 이전)
cd pi && python3 -m edge.monitor
```

한 대에서 여러 역할을 함께 검증할 때는 `/etc/hw-robot.env`·`/etc/hw-actuator.env` 에
`HW_ENTITY_ID` 를 넣고 각 서비스를 함께 띄운다(pi7 에서 3종 동시 가동 확인).
설정은 코드가 아니라 `/etc/hw-node.env` 또는 `HW_*` 환경변수로 바꾼다.

### 검증 시나리오 (전부 pi7 실기 통과)

```bash
S=zoneA/sensor/wl-001/cmd ; R=zoneA/robot/rb-01/cmd
# 명령 4단계 (물리): accepted → executing → state_changed → completed
mosquitto_pub -h <IP> -t $S -q 1 -m '{"command_id":"c1","action":"levee","params":{"position":"open"}}'
# 주기 전환 (HW-S-04)
mosquitto_pub -h <IP> -t $S -q 1 -m '{"command_id":"c2","action":"set_mode","params":{"mode":"event"}}'
# 임무 하달 (HW-R-05) — 하달 후 하트비트가 멈추고 상태가 20Hz로 오른다
mosquitto_pub -h <IP> -t $R -q 1 -m '{"command_id":"m1","action":"assign_mission","params":{"mission_id":"MSN-1","subtask":"patrol"}}'
# 진단
mosquitto_pub -h <IP> -t $S -q 1 -m '{"command_id":"d1","action":"diag"}'
```

| 시나리오 | 조작 | 기대 결과 | 실측 |
|---|---|---|---|
| 급변·임계 | `touch /tmp/rain` | 임계 도달 **전에** `rapid_change`, 3.0m 돌파 시 `threshold_exceeded` + 자동 1Hz 전환 | 2.852m 에서 급변 발행 ✅ |
| 해제 | `rm /tmp/rain` | 2.9m 미만에서 `threshold_cleared` + 60초 복귀 | ✅ |
| 로봇 주기 | 임무 하달/중단 | 임무 20Hz·하트비트 0 / 대기 1Hz·하트비트 1Hz | 19.9 / 0 · 1.0 / 1.0 Hz ✅ |
| 계획 종료 | `systemctl stop` | `event=shutdown, reason=graceful_shutdown, ds=ok` | ✅ |
| 급사 | `pkill -9` | `event=death, reason=lwt, ds=fault` → systemd 3초 내 재기동 | ✅ |
| 오프라인 판정 | 브로커 종료 | 하트비트 4회(4초) 미수신 → OFFLINE | ✅ |
| 두절 버퍼링 | 브로커 종료 후 복구 | 순서 보존 재전송, 잔량 0 | 센서 31건 전량 ✅ |
| 버퍼 정책 분리 | 20Hz 임무 중 63초 두절 | 연속값은 1Hz로 솎고 이산 사건은 전량 | **1257건 → 64건**(95% 감축) ✅ |
| device_id 중복 | 같은 ID 두 노드 | 20초 내 3회 재접속 시 `[치명]` 경보 | ✅ 양방향 |
| 액추에이터 4단계 | `actuate gate open` | ACK→수행중→**물리 도달 확인**→완료 | ✅ |
| 액추에이터 안전 잠금 | `touch /tmp/feedback_loss` 또는 브로커 종료 | 잠금 + 안전 상태 복귀, 명령 거부. 복구 시 실제 상태 재확인 후 해제 | ✅ 두 경로 |
| K3s 증강 배포 | `kubectl apply/delete` | pi7 에 배포·셀프힐링(Exit 137)·제거. **MQTT 무영향** | ✅ |
| 명령 중복 배달 | 같은 command_id 재전송 | 재실행 없이 이전 ACK 재송신 | ✅ |

## 임시값 (협의 후 교체)

| 항목 | 현재값 | 확정 방법 |
|---|---|---|
| 토픽 prefix | `zoneA` | 백엔드 도메인 체계 확정 |
| 하트비트 주기 | 1초 (정의서 HW-S-05) | 아키텍처 v4의 5초와 상충 — 협의 안건 |
| 로봇 상태 20 Hz | 설정값 | 근거인 Nav2 값은 내부 제어 루프 주기 — 무선망 실측 재산정 필요 (SRS O-11) |
| OTel export | 60초 (정의서 HW-C-05) | 계획서 초안 15초와 상충 — 정의서 채택 |
| 스키마 필드 | `source_id`+`device_id` 병기 | 확정 시 `schema.LEGACY_DEVICE_ID=False` |
| 브로커·인증 | 노트북, 익명 | 엣지노드 이전 + TLS |

## 다음 할 일

| 항목 | 막고 있는 것 |
|---|---|
| 현장용 엣지 전용 장비 | 현재 제어평면·브로커가 개발 PC 에 있다. PC 가 꺼지면 구역이 멈춘다 |
| 백엔드 협의 | 토픽 체계·스키마 필드·하트비트 주기·[G2]/[G3]·frame_ref 형식 |
| 센서·로봇·액추에이터 실물 | `read_sensor()` / `ControllerLink` / `ActuatorLink` 교체만 남았다 |
| Pi 5 영상 인코딩 벤치마크 | 하드웨어 H.264 인코더가 없어 CPU 예산이 영상 설계를 지배한다 (SRS §9.3) |
| 증강 컨테이너 이미지 빌드 | 현재는 매니페스트만. arm64 이미지 빌드·레지스트리 필요 |
