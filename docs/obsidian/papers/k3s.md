# K3s (Lightweight Kubernetes)

## 메타데이터
- categories: Lightweight Kubernetes Distribution, Edge/IoT/Air-gapped 대상 환경, Containerd 내장 런타임
- domain: [[배포·오케스트레이션]]
- source: K3s 프로젝트. "What is K3s?" K3s Documentation, 확인 시점 2026-09.
- url: https://docs.k3s.io/
- year: 확인 필요 (지속 갱신 문서라 발행년도 특정 불가; 페이지 자체는 "Last updated on Aug 14, 2026"로 표기, 이는 발행년도가 아니라 최근 갱신일)
- authors: K3s 프로젝트 (docs.k3s.io 운영)
- venue: K3s Documentation

## 1. 핵심 요약
- K3s는 "a fully compliant Kubernetes distribution"이며 "Lightweight Kubernetes. Easy to install, half the memory, all in a binary of less than 100 MB."로 스스로를 설명한다.
- 공식 문서가 명시하는 적합 대상("Great for:")은 Edge, Homelab, Internet of Things(IoT), Continuous Integration(CI), Development, 단일보드컴퓨터(ARM), Air-gapped environments, Embedded K8s다.
- containerd/cri-dockerd 컨테이너 런타임(CRI)이 패키징된 의존성으로 포함되어 있어 별도 설치 없이 단일 바이너리 또는 최소 컨테이너 이미지로 배포된다.
- 확인된 최신 릴리스 계열은 v1.36.X(Release Notes 링크 기준)이며, 문서는 Installation/Architecture/Upgrades 세 섹션으로 운영 문서를 구성한다.

## 2. 문서 목적
- 해결하려는 문제: 표준 Kubernetes는 리소스 사용량과 설치 복잡도가 edge·IoT·ARM 단일보드컴퓨터·air-gapped 같은 제약된 환경에는 부적합하다.
- 기술적 목표: 완전히 호환되는 Kubernetes distribution을 유지하면서 메모리 사용량을 절반으로 줄이고, 100MB 미만 단일 바이너리로 설치·운영을 단순화하는 것.
- 다루는 범위: 설치(Installation), 아키텍처(Architecture), 업그레이드(Upgrades) 등 K3s 배포·운영 전반. 애플리케이션 워크로드 자체의 업무 의미론(예: 로봇 물리 동작)은 다루지 않으며 이는 명시적으로 범위 밖이다.

## 3. 핵심 개념 상세
### Lightweight Kubernetes Distribution
- 원문 표현: "K3s is a fully compliant Kubernetes distribution with the following enhancements... Lightweight Kubernetes. Easy to install, half the memory, all in a binary of less than 100 MB."
- 정의: 표준 Kubernetes와 완전히 호환되면서 설치 용이성과 낮은 리소스 사용량을 목표로 재패키징된 배포판.
- 역할: 오케스트레이션 범위를 배포/기동·재시작/노드 배치/health/resource allocation/rollout/rollback 같은 워크로드 생애주기 관리로 한정하고 싶을 때 쓰인다. 표준 Kubernetes API와 완전히 호환되므로, 여러 지리적 위치(예: 중앙 서버와 각 현장의 엣지 노드)에 개별 클러스터를 두고도 동일한 배포·헬스체크·롤백 인터페이스로 운영할 수 있다.

### Edge/IoT/Air-gapped 대상 환경
- 원문 표현: "Great for: ... Edge ... Internet of Things (IoT) ... Single board computers (ARM) ... Air-gapped environments"
- 정의: 공식 문서가 K3s의 주요 적용 대상으로 명시하는 제약된 배포 환경 목록.
- 역할: 폐쇄망(air-gapped) 환경에서 외부 인터넷 연결 없이 기동·복구해야 하는 시스템을 구축할 때 유용하다. K3s가 이런 환경을 공식 지원 대상으로 명시한다는 점은 제약된 네트워크 조건의 엣지·현장 배포에서 오케스트레이터를 선택하는 근거가 될 수 있다.

### Containerd 내장 런타임
- 원문 표현: "containerd / cri-dockerd container runtime (CRI)"
- 정의: K3s가 별도 설치 절차 없이 containerd(또는 cri-dockerd)를 패키징된 컨테이너 런타임으로 포함하는 것.
- 역할: 별도의 컨테이너 런타임 설치 단계 없이 즉시 컨테이너를 실행하고 싶을 때 유용하다. 다만 상위 애플리케이션이 요구하는 것은 "OCI 호환 이미지"이지 "K3s가 내부적으로 containerd를 쓴다"는 사실 자체가 아니므로, 이 둘을 구분해두면 향후 런타임이 교체되어도 상위 요구사항에는 영향이 없다.

## 4. 구조 및 흐름
1. 단일 바이너리(또는 최소 컨테이너 이미지)로 배포판을 노드에 설치한다.
2. containerd/cri-dockerd가 별도 설치 없이 패키징되어 즉시 컨테이너 런타임으로 동작한다.
3. 운영 문서는 Installation → Architecture → Upgrades 순서로 구성되어, 설치 이후 아키텍처 이해, 이후 버전 업그레이드까지 생애주기를 안내한다.
4. Release Notes(확인된 최신 계열 v1.36.X)를 통해 버전별 변경사항을 추적하며 K3s 자체의 업그레이드가 이루어진다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| K3s는 완전히 호환되는 Kubernetes distribution이면서 표준 K8s보다 가볍다 | "K3s is a fully compliant Kubernetes distribution" + "half the memory, all in a binary of less than 100 MB." |
| K3s는 edge/IoT/ARM/air-gapped 환경을 공식 대상으로 명시한다 | "Great for:" 목록에 Edge, IoT, Single board computers (ARM), Air-gapped environments가 포함됨 |
| 별도 컨테이너 런타임 설치 없이 즉시 사용 가능하다 | containerd/cri-dockerd(CRI)가 패키징된 의존성으로 포함됨 |

## 6. 한계 및 부족한 점
- 공식 문서 자체가 명시하는 한계: 이번에 확인한 소개 페이지 범위에서는 표준 Kubernetes 대비 어떤 구성요소가 제거·축소되었는지를 명시적으로 나열하지 않았다("배터리 포함" 관점에서 포함된 것만 강조) — 확인 안 됨, 별도 아키텍처 페이지 조사가 필요하다.
- 일반적으로 중요한 구분점: K3s가 제공하는 rollout/rollback/health/resource allocation은 컨테이너·워크로드 단위의 배포 상태를 다루는 것이지, 로봇 팔의 이동이나 액추에이터 동작처럼 이미 물리 세계에서 발생한 행동을 되돌리는 수단이 아니다. 물리 장치를 제어하는 시스템을 K3s로 운영하더라도, Pod 재시작이나 워크로드 rollback을 실제 물리 장치의 동작 상태나 하드웨어 제어 결과의 취소·복구로 오인해서는 안 된다 — Kubernetes 워크로드 lifecycle과 물리적 행동의 lifecycle은 완전히 다른 계약이다.
- 이번 fetch 범위에서는 K3s의 embedded datastore(예: etcd/sqlite 선택)나 server/agent 노드 역할 분리에 대한 구체 서술을 확인하지 못했다(확인 필요, Architecture 페이지 별도 조사 필요).

## 7. 원문 기반 핵심 문장
> "K3s is a fully compliant Kubernetes distribution with the following enhancements... Lightweight Kubernetes. Easy to install, half the memory, all in a binary of less than 100 MB."
