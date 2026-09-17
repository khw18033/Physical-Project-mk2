# Kubernetes Pod Security Standards

## 메타데이터
- categories: Privileged 정책, Baseline 정책, Restricted 정책, Pod Security Admission
- domain: [[관측·보안]], [[배포·오케스트레이션]]
- source: Kubernetes 프로젝트. "Pod Security Standards." Kubernetes Documentation, 확인 시점 2026-09.
- url: https://kubernetes.io/docs/concepts/security/pod-security-standards/
- year: 확인 필요 (지속 갱신 문서)
- authors: Kubernetes 프로젝트
- venue: Kubernetes Documentation

## 1. 핵심 요약
- Pod Security Standards는 Privileged/Baseline/Restricted 세 정책을 정의하며 "These policies are _cumulative_ and range from highly-permissive to highly-restrictive."라고 명시한다.
- Privileged는 "purposely-open, and entirely unrestricted"이고, Baseline은 "aimed at ease of adoption for common containerized workloads while preventing known privilege escalations"이며, Restricted는 요약 표 기준 "Heavily restricted policy, following current Pod hardening best practices."이다.
- Baseline은 hostNetwork/hostPID/hostIPC, privileged container, 제한된 Linux capability 목록 외 사용 금지, hostPath volume 금지, 임의 hostPort 제한 등을 구체 필드·허용값(Allowed Values) 단위로 명시한다.
- 실제 적용은 Pod Security Admission controller를 통해 이뤄지며, 일부 항목(예: Host Ports의 "Known list")은 built-in admission controller가 지원하지 않는다는 구현 한계가 문서에 직접 명시되어 있다.

## 2. 문서 목적
- 해결하려는 문제: 이전 PodSecurityPolicy를 대체하면서, 서로 다른 신뢰 수준의 워크로드(시스템 인프라 vs 일반 애플리케이션 vs 보안 민감 애플리케이션)에 서로 다른 보안 기준을 표준화해서 적용해야 하는 문제.
- 기술적 목표: 세 단계의 누적적(cumulative) 정책으로 privileged container, host namespace 공유, 위험한 capability, hostPath 등 알려진 권한 상승 경로를 정책 수준에서 차단하는 것.
- 다루는 범위: Privileged/Baseline/Restricted 세 정책의 구체 제어 항목(허용값 목록), 적용 메커니즘(Pod Security Admission), 일부 항목의 구현 미지원 한계.

## 3. 핵심 개념 상세
### Privileged 정책
- 원문 표현: "The _Privileged_ policy is purposely-open, and entirely unrestricted. This type of policy is typically aimed at system- and infrastructure-level workloads managed by privileged, trusted users."
- 정의: 컨테이너 격리를 우회할 수 있는, 제약 없는 정책.
- 역할: 하드웨어 제어 어댑터나 추론 파드처럼 물리 장치·센서에 접근해야 하는 워크로드라도, 정말 필요한 경우가 아니면 일반 워크로드의 기본값으로 쓰지 않아야 하는 정책이다. `privileged: true`, `hostPID: true`, `hostNetwork: true`, 루트(`/`) 전체를 마운트하는 `hostPath` 같은 설정을 특수 워크로드의 기본 설정으로 습관적으로 쓰면 컨테이너 격리의 이점이 사실상 사라진다.

### Baseline 정책
- 원문 표현: "The _Baseline_ policy is aimed at ease of adoption for common containerized workloads while preventing known privilege escalations. This policy is targeted at application operators and developers of non-critical applications."
- 정의: hostNetwork/hostPID/hostIPC, privileged container, 제한된 Linux capability 목록(`AUDIT_WRITE`, `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `FSETID`, `KILL`, `MKNOD`, `NET_BIND_SERVICE`, `SETFCAP`, `SETGID`, `SETPCAP`, `SETUID`, `SYS_CHROOT` 외 금지), hostPath volume 금지 등을 제어하는 중간 수준 정책.
- 역할: 특수한 하드웨어 접근 권한이 필요 없는 일반 애플리케이션 컴포넌트(예: 관리·배포 컨트롤러류)에 적용 가능한 최소 기준으로 검토할 수 있다.

### Restricted 정책
- 원문 표현: "Heavily restricted policy, following current Pod hardening best practices." (요약 표 기준)
- 정의: Baseline의 모든 제약에 더해 non-root 실행, seccomp 프로파일 강제 등 추가로 엄격한 요구를 부과하는 가장 강한 정책. 이번 fetch에서는 Restricted의 세부 필드·허용값 전체 표는 확인하지 못했다(확인 필요).
- 역할: non-root 실행이나 seccomp 프로파일 강제 같은 강한 보안 요구가 필요한 워크로드에 적용하는 수준이다. 벤더 SDK 제약으로 예외가 필요한 컴포넌트가 있다면, "정확히 어떤 device/permission이 필요한가"를 별도로 명시적으로 기록해 예외 범위를 최소화하는 것이 바람직하다.

### Pod Security Admission (적용 메커니즘)
- 원문 표현: "Known list (not supported by the built-in [Pod Security Admission controller](/docs/concepts/security/pod-security-admission/))"
- 정의: Pod 생성 시 해당 namespace/label에 지정된 정책 수준을 검사해 위반 시 거부(또는 감사/경고)하는 admission controller.
- 역할: 정책 문서 자체(허용값 정의)와 실제 강제 메커니즘(admission controller)이 분리되어 있다는 점에 유의해야 한다. 정책을 "문서로 정의했다"는 것과 "실제로 적용되고 있다"는 것은 다르며, 후자를 확인하려면 admission controller가 해당 namespace에 실제로 활성화되어 있는지까지 점검해야 한다.

## 4. 구조 및 흐름
1. 세 정책(Privileged/Baseline/Restricted)이 "highly-permissive"에서 "highly-restrictive"까지 누적적으로 정의된다.
2. 각 정책은 control(예: Privileged Containers, HostPath Volumes, Host Namespaces, Capabilities, AppArmor, SELinux, Seccomp, Sysctls 등)별로 허용값(Allowed Values)을 표로 명시한다.
3. namespace 또는 Pod에 정책 수준을 지정하면 Pod Security Admission controller가 Pod 생성 시점에 해당 정책의 허용값을 검사한다.
4. built-in controller가 지원하지 못하는 세부 항목(예: Host Ports의 "Known list")은 별도 도구나 정책 확장이 필요하다는 구현 한계가 문서에 명시된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| 세 정책은 누적적이며 허용-제한 스펙트럼을 이룬다 | "These policies are _cumulative_ and range from highly-permissive to highly-restrictive." |
| Baseline은 알려진 권한 상승 경로를 구체 필드 단위로 차단한다 | Privileged Containers/Host Namespaces/HostPath Volumes/Capabilities 등에 대해 Allowed Values가 "Undefined/nil, false" 또는 금지된 값 목록으로 명시됨 |
| 정책 정의와 실제 강제 메커니즘은 별개이며 일부 항목은 built-in controller가 지원하지 않는다 | "Known list (not supported by the built-in Pod Security Admission controller)" |

## 6. 한계 및 부족한 점
- 공식 문서가 명시하는 한계: Host Ports 제어의 "Known list" 옵션이 "not supported by the built-in Pod Security Admission controller"라고 명시되어, 정책 스펙과 실제 구현 사이에 간극이 있음을 문서 스스로 인정한다. 또한 AppArmor 적용은 "On supported hosts"라는 조건이 붙어 호스트 지원 여부에 따라 실제 적용 결과가 달라질 수 있음을 명시한다.
- 일반적인 주의점: Pod Security Standards는 Pod 스펙 필드(`securityContext` 등)를 검사하는 워크로드 계층 통제일 뿐이며, 네트워크 계층(예: VPN/오버레이 네트워크 연결 통제), 메시징 계층(누가 특정 토픽을 publish/consume할 수 있는가), 아티팩트 계층(이미지 무결성·서명 검증) 같은 다른 보안 계층의 위험은 다루지 않는다. 즉 Restricted 정책을 통과한 Pod라도 메시징 토픽을 무단으로 publish하거나 서명되지 않은 이미지를 실행하는 것을 막지는 못하므로, 다른 보안 계층과 함께 적용해야 한다.
- 이번 fetch로는 Restricted 정책의 전체 control 목록(구체 필드·허용값)을 확인하지 못했다(확인 필요, Baseline 대비 추가되는 항목만 요약 수준으로 확인됨).

## 7. 원문 기반 핵심 문장
> "The Pod Security Standards define three different _policies_ to broadly cover the security spectrum. These policies are _cumulative_ and range from highly-permissive to highly-restrictive."
