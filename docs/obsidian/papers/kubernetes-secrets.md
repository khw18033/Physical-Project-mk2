# Kubernetes Secrets

## 메타데이터
- categories: Secret Object, etcd 평문 저장 경고, Encryption at Rest, Least-privilege RBAC 권고
- domain: [[관측·보안]]
- source: Kubernetes 프로젝트. "Secrets." Kubernetes Documentation, 확인 시점 2026-09.
- url: https://kubernetes.io/docs/concepts/configuration/secret/
- year: 확인 필요 (지속 갱신 문서)
- authors: Kubernetes 프로젝트
- venue: Kubernetes Documentation

## 1. 핵심 요약
- Secret은 "an object that contains a small amount of sensitive data such as a password, a token, or a key"로 정의된다.
- 공식 문서는 "Kubernetes Secrets are, by default, stored unencrypted in the API server's underlying data store (etcd)"라고 명시적으로 경고한다.
- API 접근 권한이 있는 누구나, 그리고 해당 namespace에 Pod를 생성할 수 있는 누구나 간접적으로 Secret을 읽을 수 있다고 문서가 명시한다.
- 권고 대응책으로 "Enable Encryption at Rest for Secrets."와 "Enable or configure RBAC rules with least-privilege access to Secrets."가 제시된다.

## 2. 문서 목적
- 해결하려는 문제: 비밀번호·토큰·키 같은 민감 데이터를 Pod 스펙이나 컨테이너 이미지에 직접 넣으면 노출 위험이 커지는 문제.
- 기술적 목표: 민감 데이터를 별도 오브젝트로 분리해 애플리케이션 코드/이미지와 독립적으로 관리하되, 기본 저장 방식의 보안 한계를 명확히 경고하고 강화 옵션을 안내하는 것.
- 다루는 범위: Secret의 용도(환경변수, SSH 키/비밀번호 제공, private registry 인증 등), 기본 저장 방식의 보안 경고, encryption at rest 및 RBAC 권고, 외부 Secret store 언급.

## 3. 핵심 개념 상세
### Secret 오브젝트
- 원문 표현: "A Secret is an object that contains a small amount of sensitive data such as a password, a token, or a key. Such information might otherwise be put in a Pod specification or in a container image. Using a Secret means that you don't need to include confidential data in your application code."
- 정의: 민감 데이터를 Pod 스펙·이미지와 분리해 관리하는 Kubernetes API 오브젝트.
- 역할: 메시징 브로커 credential, API 키, private key, VPN/오버레이 네트워크 인증 키 같은 민감 정보를 컨테이너 이미지에 하드코딩하지 않고 별도로 관리하고 싶을 때 쓰는 후보 메커니즘이다.

### etcd 평문 저장 경고
- 원문 표현: "Kubernetes Secrets are, by default, stored unencrypted in the API server's underlying data store (etcd). Anyone with API access can retrieve or modify a Secret, and so can anyone with access to etcd. Additionally, anyone who is authorized to create a Pod in a namespace can use that access to read any Secret in that namespace; this includes indirect access such as the ability to create a Deployment."
- 정의: Secret 오브젝트 자체는 기본 설정에서 저장소(etcd) 수준 암호화가 적용되지 않으며, API 접근 권한 또는 Pod 생성 권한만으로도 Secret 내용을 읽을 수 있다는 공식 경고.
- 역할: Kubernetes Secret을 그 자체로 "안전한 저장소"로 과신하면 안 된다는 근거다. Secret을 쓰더라도 RBAC으로 Secret 읽기 권한을 최소화하고, 필요하면 encryption at rest를 별도로 활성화해야 credential 노출 위험을 실질적으로 낮출 수 있다.

### Encryption at Rest / Least-privilege RBAC 권고
- 원문 표현: "Enable Encryption at Rest for Secrets." / "Enable or configure RBAC rules with least-privilege access to Secrets." / "Restrict Secret access to specific containers." / "Consider using external Secret store providers."
- 정의: 기본 평문 저장의 한계를 보완하기 위해 공식 문서가 권고하는 네 가지 조치 — 저장소 암호화, 최소 권한 RBAC, 컨테이너 단위 접근 제한, 외부 Secret store 사용 검토.
- 역할: 각 컴포넌트별로 필요한 credential만 최소 범위로 마운트하는 설계의 근거가 된다. "외부 Secret store providers" 권고는 폐쇄망(air-gapped) 환경에서는 그대로 적용하기 어려울 수 있다 — 외부 SaaS Secret store에 대한 나가는 연결을 전제로 두지 않으려면, 내부망에서 운용 가능한 Secret store만 후보로 검토해야 한다.

## 4. 구조 및 흐름
1. 민감 데이터(비밀번호, 토큰, 키)를 Pod 스펙이나 이미지에 직접 넣는 대신 Secret 오브젝트로 분리해 생성한다.
2. Secret은 기본적으로 API 서버의 etcd에 평문으로 저장된다 — 이 상태로는 API 접근 권한자나 해당 namespace의 Pod 생성 권한자가 간접적으로도 읽을 수 있다.
3. 이 위험을 낮추기 위해 encryption at rest를 활성화하고, Secret에 대한 RBAC 규칙을 least-privilege로 구성한다.
4. 추가로 Secret 접근을 특정 컨테이너로 제한하거나, 필요하면 외부 Secret store provider 연동을 검토한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Secret은 민감 데이터를 코드/이미지에서 분리하는 목적으로 설계되었다 | "Using a Secret means that you don't need to include confidential data in your application code." |
| 기본 설정의 Secret은 실제로는 강한 보안을 제공하지 않는다 | "Kubernetes Secrets are, by default, stored unencrypted in the API server's underlying data store (etcd)." |
| Pod 생성 권한만으로도 간접적으로 Secret을 읽을 수 있다 | "anyone who is authorized to create a Pod in a namespace can use that access to read any Secret in that namespace; this includes indirect access such as the ability to create a Deployment." |

## 6. 한계 및 부족한 점
- 공식 문서가 스스로 명시하는 한계: 문서의 핵심 메시지 자체가 한계 경고다 — "Kubernetes Secrets are, by default, stored unencrypted"이며, API 접근자와 Pod 생성 권한자 모두 사실상 Secret에 접근 가능하다고 명시한다. 즉 Secret 오브젝트를 만드는 것 자체는 암호화나 접근 통제를 보장하지 않는다.
- 일반적인 주의점: Secret은 "container image에 credential을 넣지 않는다"는 최소 요구는 만족시키지만, RBAC(least-privilege)과 encryption at rest를 별도로 구성하지 않으면 실무에서 기대하는 수준의 워크로드 계층 보안에는 미달한다. 즉 Secret 사용 여부와 실제 credential 보호 수준은 별개이며, "Secret을 쓴다"는 사실만으로 보안 요구사항이 충족됐다고 판단하면 안 된다.
- 이 문서가 다루는 범위는 Kubernetes API 오브젝트로서의 Secret 저장·접근 통제이며, 메시징 브로커 자체의 인증(메시징 계층)이나 컨테이너 이미지 서명(아티팩트 계층)의 credential 관리와는 별개 계층임을 구분해야 한다.

## 7. 원문 기반 핵심 문장
> "Kubernetes Secrets are, by default, stored unencrypted in the API server's underlying data store (etcd). Anyone with API access can retrieve or modify a Secret, and so can anyone with access to etcd."
