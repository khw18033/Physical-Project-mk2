# 피지컬팀 프로젝트 mk2 — 하드웨어(HW) 파트

재난 대응 IoT 텔레메트리 시스템의 **말단↔엣지 구간** 구현. 담당: 조병현

## 시스템 구조 (현재 구현 범위)

```
[말단 = 라즈베리파이(wl-001)]        [엣지 대역 = 노트북]              [엣지 로직 대역]
 pi/sensor_node.py    ──MQTT──►      Mosquitto 브로커     ──────►     pi/monitor.py
 (수위센서 노드)                      (발행/구독 중계)                  (생사 판정)
```

전체 아키텍처는 3계층(말단 → 엣지 → 서버)이며, 말단↔엣지는 MQTT(업무·명령·하트비트) +
OpenTelemetry OTLP(관측), 엣지↔서버는 Kafka. 근거 문서: `데이터 전송 및 아키텍처 v4`,
`캡스톤MK2 요구사항 통합정립본 v3`. 상세 계획·진행 기록은
[`하드웨어_구현_착수순서_계획.md`](./하드웨어_구현_착수순서_계획.md) 참조.

## 구현 완료 (2026-08-25 기준)

| Phase | 요구사항 ID | 내용 | 상태 |
|---|---|---|---|
| 0 | HW-S-08 | NTP 시각 동기화 (chrony, 파이 셋업) | ✅ |
| 0 | HW-C-07 | device_id 채번 (`type-serial`, `/etc/device_id`) | ✅ |
| 1 | HW-C-04 | Birth/Death 등록 (retained status + LWT) | ✅ |
| 1 | HW-S-05 | 하트비트 5초 주기 | ✅ |
| 1 | HW-C-06 | 명령 수신·ACK (command_id 상관키) | ✅ |
| 1 | HW-S-07 | 오프라인 판정 (LWT + 4회 미수신 이중 감지) | ✅ |
| 2 | HW-S-02 | 평시 60초 보고 + 임계값 즉시 발행 (report-by-exception) | ✅ (가짜 센서) |
| 2 | HW-S-01 | 실센서 계측값 수집 | ⏳ 센서 조달 대기 — `read_water_level()`만 교체 |

## 파일 구성

- `pi/sensor_node.py` — 말단 노드 최종본. 등록·하트비트·명령/ACK·계측 보고 전부 포함
- `pi/monitor.py` — 엣지 오프라인 판정(HW-S-07) 대역. 엣지노드 구축 후 이전 예정
- `pi/pi_base_setup.sh` — 라즈베리파이 공통 베이스 셋업(chrony·device_id·cgroup·라이브러리)
- `하드웨어_구현_착수순서_계획.md` — 전체 Phase 계획 + 결정사항 + 진행 기록 (기준 문서)

## 실행 방법

말단(라즈베리파이) 사전조건: `pi_base_setup.sh` 실행 완료(chrony, `/etc/device_id`,
cgroup, venv에 paho-mqtt·opentelemetry-sdk·psutil).

1. 브로커 (임시: Windows 노트북, 최종: 엣지노드)

   ```
   mosquitto -c test.conf -v      # test.conf: listener 1883 0.0.0.0 / allow_anonymous true
   ```

2. 관찰용 구독 (선택)

   ```
   mosquitto_sub -h <브로커IP> -t "zoneA/#" -v
   ```

3. 파이에서 노드 실행: `python3 sensor_node.py` / 별도 세션에서 `python3 monitor.py`

### 테스트 시나리오

- 명령→ACK: `mosquitto_pub -h <브로커IP> -t "zoneA/sensor/wl-001/cmd" -m "{\"command_id\":\"cmd-test-001\",\"levee\":\"open\"}" -q 1`
- 강우(임계값 즉시 발행): 파이에서 `touch /tmp/rain` → 수위 상승 → `threshold_exceeded` 즉시 발행. `rm /tmp/rain` → 2.9m 미만에서 `threshold_cleared`
- 급사(LWT+타임아웃): sensor_node.py를 Ctrl+C → 즉시 LWT `offline` + 20초 후 monitor의 OFFLINE 판정

## 임시값 (협의 후 교체 예정)

| 항목 | 현재 임시값 | 확정 방법 |
|---|---|---|
| 토픽 prefix | `zoneA` | 백엔드와 `{domain}/{type}/{id}/{channel}` 도메인 체계 확정 |
| 하트비트 주기 | 5초 | 계획서 1Hz vs 아키텍처 v4 5초 — 협의 안건 |
| 브로커 위치 | 노트북 | 엣지노드 구축 후 이전 (Mosquitto, 최종 MQTT 5.0/TLS) |
| 인증 | 없음(allow_anonymous) | 최종 TLS + 인증 |

## 다음 할 일

sensor_node.py systemd 서비스 등록(부팅 자동 시작), OTLP metric 5종 발신
(CPU·메모리·디스크·발행 성공/실패·지연, 15초 export), 백엔드 협의(토픽·QoS·LWT·스키마
+ OTel 발신 방식 상충 해소 + G2/G3 회신), Phase 3 명령·임무 체계.
