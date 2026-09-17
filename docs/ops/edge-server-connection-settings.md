# 엣지·서버 측 연결 설정 (운영자 검토용 — 아직 미적용)

이 문서는 파트 간 통신 규약을 모아둔 `interface-spec/`와 분리된, **이 PC(엣지+서버
역할 겸용)를 관리하는 사람만 보는 문서**다. 하드웨어 파트는 이 파일의 존재를 알 필요가
없다 — 그들은 연결 정보(주소·계정)만 별도로 전달받는다.

**상태: 검토 대기. 아래 변경 중 어느 것도 아직 코드/설정 파일에 적용하지 않았다.**
검토 후 승인하면 그때 `deploy/integration/mosquitto.conf` 등 실제 파일을 수정한다.

## 1. 지금 상태 (2026-09-03 확인)

```bash
docker ps
# aif-test-mqtt   127.0.0.1:1883->1883   (익명 접속 허용)
# aif-test-kafka  127.0.0.1:9092->9092
# aif-test-otel   127.0.0.1:4317-4318->4317-4318
```

전부 loopback 바인딩이라 이 PC 밖에서는 물리적으로 접속이 불가능하다. 실제 로봇을 붙이려면
최소 MQTT는 LAN에 노출해야 한다.

## 2. 결정할 것 — 수정 전에 답을 먼저 정한다

| 질문 | 옵션 | 권장 |
|---|---|---|
| MQTT를 어디에 바인딩할까 | (a) 특정 LAN IP만 (b) `0.0.0.0` 전체 | (a) — 개발실 네트워크만 |
| 인증 수준 | (a) 최소(username/password) (b) 전체 mTLS(`06-production-transport-security-migration.md`) | 하드웨어 bring-up 단계는 (a), 운영 전환 시 (b) |
| 장치별 계정 발급 방식 | (a) 수동(`mosquitto_passwd`) (b) Dynamic Security plugin | 장치 수 적으면 (a) |
| Kafka/OTel도 LAN 노출할까 | 로봇은 MQTT까지만 필요 — 기본은 그대로 loopback 유지 | 노출 안 함 |

## 3. 적용 시 변경할 파일과 내용 (초안 — 검토용)

### 3.1 `perception-framework/deploy/integration/mosquitto.conf`

```conf
# 기존 (loopback, 익명)
listener 1883

# 변경안 (LAN IP 예시, 실제 IP로 교체 필요)
listener 1883 <이-PC의-LAN-IP>
allow_anonymous false
password_file /mosquitto/config/passwords
acl_file /mosquitto/config/acl
```

### 3.2 `docker-compose.yml`의 MQTT 포트 매핑

```yaml
# 기존
ports:
  - "127.0.0.1:1883:1883"
# 변경안
ports:
  - "1883:1883"    # 또는 특정 LAN IP만: "<LAN-IP>:1883:1883"
```

### 3.3 계정·ACL (장치 등록 시마다 반복)

```bash
mosquitto_passwd -b passwords terminal-<device-id> <임의-비밀번호>
```

`acl` 파일에 장치별로 자기 topic만 허용:

```text
user terminal-<device-id>
topic write task/<device-id>/#
topic write heartbeat/<device-id>
topic read command/<device-id>/#
```

### 3.4 방화벽

- 1883/tcp를 LAN 인터페이스에서만 허용 (외부/인터넷 노출 금지 — CLAUDE.md 원칙 #18 폐쇄망 전제)

## 4. 장치에 보낼 연결 정보 (킷과 별도로, 장치별 1회 전달)

하드웨어 파트에는 코드(킷)만 보내고, 아래 값은 이 문서를 검토·확정한 뒤 **장치별로 개별
전달**한다(같은 채널로 섞어 보내지 않는다 — 계정 정보이므로).

```json
{
  "mqtt_host": "<이-PC-LAN-IP>",
  "mqtt_port": 1883,
  "username": "terminal-<device-id>",
  "password": "<발급한 비밀번호>",
  "topic_prefix": "<device-id>"
}
```

## 5. 말단 배포 번들 — 무엇을 보낼지 (구현 필요, 아직 없음)

`interface-spec/`는 **통신 규약 문서**(무엇을 어떤 형식으로 주고받는가)일 뿐이고, 실제
장치에 설치되는 것은 아래 경량 세트뿐이어야 한다(AI-B-10). 이 번들을 만드는 스크립트는
아직 없다 — 승인 시 작성.

```text
device-bundle/<device-id>/
├── connection.json     # 위 4번 내용
├── provider.py          # 하드웨어 파트가 skeleton/에서 완성해 돌려준 파일
├── requirements.txt     # paho-mqtt, opentelemetry-sdk 등 최소 의존성만
└── VERSION
```

## 6. 최초 부트스트랩 방식 — 결정 필요

| 방식 | 장점 | 단점 |
|---|---|---|
| scp/USB로 최초 1회 수동 배치 | 가장 간단, 지금 바로 가능 | 장치 수 많아지면 반복 작업 |
| 이 PC에서 HTTP로 bundle 서빙(`python -m http.server` 등) | 장치가 스스로 pull, 스크립트화 가능 | 최초 인증(누가 받아가도 되는지) 별도 필요 |

## 7. 적용 후 검증 체크리스트

- [ ] 새 계정으로 MQTT 연결 성공, 익명 접속은 거부됨
- [ ] 장치 A가 장치 B의 topic에 publish 시도 시 ACL로 거부됨
- [ ] LWT(유언 메시지) 등록 확인 — 장치 kill 시 즉시 오프라인 감지(AI-O-04)
- [ ] `capabilities()` 선언이 엣지 registry에 실제로 등록됨(AI-C-10/18)
- [ ] 물리 명령 왕복: `Command → ACCEPTED → EXECUTING → SUCCEEDED/CANCELED` 실제 도달 확인
- [ ] Kafka/OTel은 여전히 loopback으로 남아 의도치 않게 노출되지 않았는지 확인

## 8. 다음 단계

이 문서를 검토하고 §2의 선택지를 확정하면, 그다음에:
1. `mosquitto.conf`/`docker-compose.yml` 실제 수정
2. 계정 발급
3. `device-bundle/` 빌드 스크립트 작성
4. 장치 1대로 §7 체크리스트 통과 확인

순서로 실행한다. 지금은 준비만 되어 있고 실행은 승인 후 진행한다.
