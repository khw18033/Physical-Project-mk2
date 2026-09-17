# Node Feature Discovery (NFD) 0.19

## 메타데이터
- categories: nfd-master/nfd-worker 아키텍처, Node Label 기반 Feature 광고, Node-level Facts vs Execution Profile
- domain: [[배포·오케스트레이션]]
- source: Kubernetes SIGs. "Introduction." Node Feature Discovery Documentation, v0.19.
- url: https://kubernetes-sigs.github.io/node-feature-discovery/v0.19/get-started/introduction.html
- year: 확인 필요 (이 페이지에서 v0.19 릴리스 연도는 직접 확인되지 않음; "Compatible with any recent version of Kubernetes (v1.24+)"만 확인)
- authors: Kubernetes SIGs (node-feature-discovery 프로젝트)
- venue: Node Feature Discovery Documentation (v0.19)

## 1. 핵심 요약
- NFD는 "This software enables node feature discovery for Kubernetes. It detects hardware features available on each node in a Kubernetes cluster, and advertises those features using node labels and optionally node extended resources, annotations and node taints."로 스스로를 정의한다.
- v0.19 문서는 "Compatible with any recent version of Kubernetes (v1.24+)"라고 호환성을 명시한다.
- 아키텍처는 nfd-master(API 통신·라벨링), nfd-worker(각 노드에서 feature 검출), nfd-topology-updater(자원 할당 토폴로지 추적), nfd-gc(오래된 커스텀 리소스 정리) 네 개 데몬으로 구성된다.
- 검출 대상은 CPU, Kernel, Memory, Network, PCI, Storage, System, USB와 사용자 정의 rule 기반(Custom)/파일 기반(Local) feature까지 포함한다.

## 2. 문서 목적
- 해결하려는 문제: Kubernetes 스케줄러가 노드별 실제 하드웨어 특성(가속기 존재, CPU 세대 등)을 알지 못해 워크로드를 적합한 노드에 배치하기 어려운 문제.
- 기술적 목표: 각 노드의 하드웨어 feature를 자동 검출해 label/annotation/taint/extended resource로 노출함으로써 스케줄링 조건(nodeSelector, node affinity 등)에 활용할 수 있게 하는 것.
- 다루는 범위: feature 검출기 종류(CPU/Kernel/Memory/Network/PCI/Storage/System/USB/Custom/Local), nfd-master/worker/topology-updater/gc의 역할 분담, label(`feature.node.kubernetes.io/`)·annotation(`nfd.node.kubernetes.io/`)으로의 노출 방식. 검출된 feature를 이용한 스케줄링 정책 자체나 AI 실측 성능 지표는 범위 밖이다.

## 3. 핵심 개념 상세
### Node Feature Discovery (하드웨어 feature 검출·광고)
- 원문 표현: "It detects hardware features available on each node in a Kubernetes cluster, and advertises those features using node labels and optionally node extended resources, annotations and node taints."
- 정의: 각 노드에서 실행되는 검출기가 CPU/Kernel/Memory/Network/PCI/Storage/System/USB 등의 하드웨어 특성을 스캔해 Kubernetes 오브젝트 메타데이터로 변환하는 소프트웨어.
- 역할: 이기종 클러스터에서 노드별 실제 하드웨어(가속기 존재, CPU 아키텍처 등) 정보를 자동으로 파악해 워크로드 배치 조건에 활용하고 싶을 때 쓰인다. 다만 NFD가 제공하는 정보는 정적 하드웨어 사실(예: ARM64/x86, accelerator 존재)에 한정되며, 실측 FPS·latency·accuracy·memory·failure characteristics 같은 실행 성능 데이터는 별도의 실행 프로파일링 계층이 채워야 한다.

### nfd-master / nfd-worker 아키텍처
- 원문 표현: "nfd-master (Kubernetes API communication and node labeling)" / "nfd-worker (feature detection; runs on each node)"
- 정의: nfd-worker가 각 노드에서 로컬로 feature를 검출해 nfd-master에 보고하고, nfd-master가 Kubernetes API를 통해 실제 노드 오브젝트에 label/annotation을 기록하는 master-worker 구조. 추가로 nfd-topology-updater(자원 할당 토폴로지 추적)와 nfd-gc(오래된 커스텀 리소스 정리)가 있다.
- 역할: 이 master-worker 구조는 nfd-master/worker가 Kubernetes API 존재를 전제한다는 것을 보여준다. 따라서 Kubernetes API가 없는 경량 노드(예: 저사양 엣지 디바이스)에서 하드웨어 자원을 등록하려면 NFD 대신 로컬에서 직접 정보를 수집·등록하는 방식으로 대체해야 한다.

### Label/Annotation/Taint/Extended Resource 노출
- 원문 표현: "advertises those features using node labels and optionally node extended resources, annotations and node taints" (feature label은 `feature.node.kubernetes.io/` 접두어, 관리 feature 추적 annotation은 `nfd.node.kubernetes.io/` 접두어를 씀)
- 정의: 검출된 feature를 Kubernetes 표준 오브젝트 메타데이터(label 등)로 표현해 스케줄러나 다른 controller가 조회·필터링할 수 있게 하는 방식.
- 역할: required/preferred 같은 배치 조건(하드웨어 아키텍처, 가속기 존재 등)을 스케줄러 수준에서 표현하는 구체적인 메커니즘 후보다. 다만 상위 애플리케이션 로직이 label 문자열 형식에 직접 의존하게 하기보다는, 자유 문자열 태그 같은 별도의 호환성 프로파일 추상화 계층을 두어 NFD의 구체 구현으로부터 분리하는 것이 유지보수에 유리하다.

## 4. 구조 및 흐름
1. nfd-worker가 각 노드에서 실행되며 CPU/Kernel/Memory/Network/PCI/Storage/System/USB 등 하드웨어 feature를 검출한다.
2. nfd-worker가 검출 결과를 nfd-master에 보고한다.
3. nfd-master가 Kubernetes API를 통해 해당 노드 오브젝트에 label(`feature.node.kubernetes.io/...`)과 필요 시 annotation/taint/extended resource를 기록한다.
4. nfd-topology-updater가 클러스터 전체에서 자원 할당 토폴로지 정보를 추적한다.
5. nfd-gc가 오래되거나 참조되지 않는 커스텀 리소스 오브젝트를 정기적으로 정리한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| NFD는 노드 하드웨어 feature를 자동 검출해 Kubernetes 표준 메타데이터로 노출한다 | 정의 문장 자체가 "detects hardware features... advertises... using node labels and optionally node extended resources, annotations and node taints" |
| v0.19는 비교적 넓은 범위의 Kubernetes 버전과 호환된다 | "Compatible with any recent version of Kubernetes (v1.24+)" |
| feature 검출과 클러스터 반영 책임이 분리된 4-데몬 구조다 | nfd-worker(검출)/nfd-master(API 반영)/nfd-topology-updater(토폴로지)/nfd-gc(정리)로 역할이 명시적으로 나뉨 |

## 6. 한계 및 부족한 점
- 공식 문서가 스스로 명시하는 한계: 이번에 확인한 소개 페이지 범위에서는 NFD가 명시적으로 "하지 않는 것"을 별도로 나열하지 않았다(확인 안 됨). 다만 정의 자체가 "하드웨어 feature 검출·광고"로 범위를 한정하고 있어, 워크로드 배치 정책이나 스케줄링 결정 자체는 NFD의 책임이 아님을 암시한다.
- 일반적인 주의점: NFD는 정적 하드웨어 사실만 제공하며 실행 성능을 판단하지 않는다. NFD label만으로 실행 가능성이나 배치 우선순위를 결정하면, 실제 처리 성능(실측 FPS, latency 등)을 반영하지 못한 배치 오류가 발생할 수 있다. 따라서 하드웨어 존재 여부(NFD가 제공)와 실측 실행 성능(별도의 프로파일링 계층이 제공)은 구분해서 관리해야 한다.
- NFD는 Kubernetes API 존재를 전제하므로, Kubernetes가 배치되지 않는 경량 말단 실행 환경에서는 그대로 사용할 수 없고 로컬 방식의 대체 구현이 필요하다.

## 7. 원문 기반 핵심 문장
> "This software enables node feature discovery for Kubernetes. It detects hardware features available on each node in a Kubernetes cluster, and advertises those features using node labels and optionally node extended resources, annotations and node taints."
