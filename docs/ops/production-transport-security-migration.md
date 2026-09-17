# 운영 전송 보안 전환 가이드

## 1. 목적과 현재 상태

이 문서는 `perception-framework/deploy/integration/`의 로컬 검증 구성을 운영용
TLS·인증·ACL 구성으로 전환하는 절차다. 현재 Mosquitto `1883`, Kafka `9092`,
OTLP `4317/4318`은 loopback plaintext이며 Mosquitto는 익명 접속을 허용한다.
검증용 설정을 외부에 그대로 노출해서는 안 된다.

## 2. 인증서와 비밀 관리

사내 PKI, Vault PKI 또는 cert-manager에서 운영 CA와 서비스별 인증서를 발급한다.
서버 인증서 SAN에는 실제 내부 DNS 이름을 넣는다.

```text
운영 CA
├── mqtt-server.crt/key
├── kafka-server.crt/key
├── otel-server.crt/key
├── edge-client.crt/key
└── terminal-client.crt/key
```

개인키·비밀번호는 Git, Docker image, ConfigMap에 넣지 않는다. K3s Secret 또는 외부
secret store를 read-only volume으로 마운트하고 파일 권한을 제한한다.

## 3. MQTT 전환

Mosquitto에 TLS listener와 익명 접속 차단을 적용한다.

```conf
listener 8883 0.0.0.0
protocol mqtt
cafile /run/secrets/ca.crt
certfile /run/secrets/mqtt-server.crt
keyfile /run/secrets/mqtt-server.key
tls_version tlsv1.2
allow_anonymous false
password_file /mosquitto/config/passwords
acl_file /mosquitto/config/acl
```

`mosquitto_passwd`로 `terminal-<id>`, `edge-bridge`, `backend-command`처럼 역할별
계정을 만든다. 말단 계정은 자기 `task/heartbeat/result`만 발행하고 자기 `command`만
구독하도록 제한한다. 장치가 많거나 실행 중 권한 변경이 필요하면
[Dynamic Security plugin](https://mosquitto.org/documentation/dynamic-security/)을 사용한다.
mTLS가 필요하면 `require_certificate true`와 인증서 identity 기반 ACL을 적용한다.

애플리케이션은 `ssl.create_default_context()`와 `load_cert_chain()`으로 만든
`tls_context`, 전용 username/password를 `MqttTransportProvider`에 전달한다.

## 4. Kafka 전환

클라이언트 listener는 `SASL_SSL`, 인증은 `SCRAM-SHA-512`, 권한은 Kafka ACL을
사용한다. KRaft controller listener와 클라이언트 listener를 분리한다.

```properties
listeners=SASL_SSL://:9094,CONTROLLER://:9093
advertised.listeners=SASL_SSL://kafka.internal.example:9094
listener.security.protocol.map=SASL_SSL:SASL_SSL,CONTROLLER:PLAINTEXT
sasl.enabled.mechanisms=SCRAM-SHA-512
authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer
allow.everyone.if.no.acl.found=false
```

Broker keystore/truststore와 SCRAM 계정을 준비한 뒤 `edge-bridge`,
`backend-command`, `backend-consumer`, 운영 계정을 분리한다. 각 principal에는 필요한
topic의 Read/Write와 consumer group 권한만 허용한다. ACL 생성 전에
`allow.everyone.if.no.acl.found=false`를 활성화하면 기존 클라이언트가 즉시 차단될 수
있다. [Kafka Security Overview](https://kafka.apache.org/39/security/security-overview/)를
기준으로 broker와 client 설정을 함께 변경한다.

`KafkaTransportProvider`에는 `security_protocol="SASL_SSL"`, SCRAM 계정 정보와
CA를 읽는 `ssl_context`를 전달한다. 인증은 송신자와 권한을 검증하며, 명령 중복
실행 방지는 별도로 `command_id` dedupe가 담당한다.

## 5. OpenTelemetry 전환

Collector OTLP receiver에 서버 TLS와 client CA를 설정한다.

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        tls:
          cert_file: /run/secrets/otel-server.crt
          key_file: /run/secrets/otel-server.key
          client_ca_file: /run/secrets/ca.crt
```

중요: 현재 `providers/otel.py`는 exporter의 `insecure=True`가 고정되어 있다.
Collector를 먼저 TLS 전용으로 바꾸면 관측 전송이 중단된다. 전환 전에 `OtelConfig`에
CA·client certificate·client key 경로를 추가하고 metric/log exporter 양쪽에 gRPC
TLS credentials를 전달하는 구현과 테스트가 필요하다. Collector의 mTLS 설정은
[공식 TLS 구성](https://go.opentelemetry.io/collector/config/configtls)을 따른다.

## 6. K3s Secret과 최소 권한

```bash
kubectl -n ai-runtime create secret tls mqtt-client-tls \
  --cert=edge-client.crt --key=edge-client.key
kubectl -n ai-runtime create secret generic transport-credentials \
  --from-file=ca.crt --from-file=mqtt-password --from-file=kafka-password
```

애플리케이션별 ServiceAccount와 namespace 범위 Role/RoleBinding을 사용한다. Kubernetes
API가 필요 없는 workload는 `automountServiceAccountToken: false`로 설정한다. Secret의
`get/list/watch` 권한과 workload 생성 권한은 권한 상승 경로가 될 수 있으므로 일반
실행 계정에 부여하지 않는다. 관련 기준은 [ServiceAccount](https://kubernetes.io/docs/concepts/security/service-accounts/)와
[RBAC 권장사항](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)을 따른다.

## 7. 무중단 전환 및 검증

1. 운영 CA와 서비스·클라이언트 인증서를 발급한다.
2. 기존 plaintext와 별도로 MQTT `8883`, Kafka `9094`, TLS OTLP listener를 기동한다.
3. 역할별 계정과 최소 권한 ACL을 먼저 생성한다.
4. K3s Secret·ServiceAccount·volume mount를 배포한다.
5. provider endpoint와 credentials를 TLS 구성으로 변경한다.
6. 정상 계정으로 MQTT/Kafka/OTLP 왕복을 확인한다.
7. 익명 접속, 잘못된 비밀번호, 다른 장치 topic, 무권한 Kafka topic이 거부되는지 확인한다.
8. 폐기·만료 인증서, broker 재시작, 인증서 교체 중 복구를 확인한다.
9. 모든 workload 전환 후 plaintext listener를 제거한다.
10. image, 로그, Git history, 환경 출력에 secret이 없는지 최종 검사한다.

운영 완료 기준은 단순한 TLS 연결 성공이 아니다. 허용 요청의 성공과 금지 요청의 실패,
인증서 회전, 장애 후 재연결, 감사 로그에서 principal 식별까지 모두 증거로 남겨야 한다.
