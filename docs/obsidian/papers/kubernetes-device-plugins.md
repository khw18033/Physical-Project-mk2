# Kubernetes Device Plugins

## 메타데이터
- categories: Device Plugin gRPC 프레임워크, Vendor-specific Device 광고, Extended Resource 스케줄링, Exclusive Device 할당
- domain: [[배포·오케스트레이션]]
- source: Kubernetes 프로젝트. "Device Plugins." Kubernetes Documentation, 확인 시점 2026-09.
- url: https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/
- year: 확인 필요 (지속 갱신 문서; 기능 자체의 GA 시점은 "Stable since Kubernetes v1.26"으로 확인됨)
- authors: Kubernetes 프로젝트
- venue: Kubernetes Documentation

## 1. 핵심 요약
- Device Plugin 프레임워크는 kubelet에 vendor-specific 하드웨어 자원을 광고하는 공식 확장 메커니즘이며, "Feature state: Stable since Kubernetes v1.26"이다.
- 대상 장치로 GPU, high-performance NICs, FPGAs, InfiniBand adapters, non-volatile main memory 등이 명시된다.
- 장치는 gRPC 서비스(`GetDevicePluginOptions`, `ListAndWatch`, `Allocate`, `GetPreferredAllocation`, `PreStartContainer`)를 통해 등록·할당된다.
- "Extended resources are only supported as integer resources and cannot be overcommitted."와 "Devices cannot be shared between containers."라는 두 가지 제약이 명시된다.

## 2. 문서 목적
- 해결하려는 문제: GPU·FPGA 같이 벤더별 초기화·설정이 필요한 하드웨어를 스케줄링 가능한 자원으로 다루려면 Kubernetes 코어 코드를 벤더별로 수정해야 하는 문제.
- 기술적 목표: Kubernetes 코어를 수정하지 않고 벤더가 자신의 device plugin을 수동 배포 또는 DaemonSet으로 배포해 자원을 kubelet에 광고할 수 있는 표준 인터페이스를 제공하는 것.
- 다루는 범위: device plugin 등록 절차, gRPC API(`ListAndWatch`/`Allocate` 등), extended resource naming(`vendor-domain/resourcetype`), 자원 할당·공유 제약.

## 3. 핵심 개념 상세
### Device Plugin 프레임워크
- 원문 표현: "Device plugins let you configure your cluster with support for devices or resources that require vendor-specific setup, such as GPUs, NICs, FPGAs, or non-volatile main memory." / "Kubernetes provides a device plugin framework that you can use to advertise system hardware resources to the Kubelet."
- 정의: 벤더가 별도 초기화·설정이 필요한 하드웨어를 kubelet에 등록할 수 있게 하는 표준 확장 프레임워크.
- 역할: GPU/NPU/가속기/전용 USB 장치처럼 스케줄러가 배타적으로 할당해야 하는 특수 하드웨어에 적합하다. 다만 단순한 파일시스템 주변장치까지 전부 custom Device Plugin으로 만드는 것은 과도할 수 있어, 배타적 할당(exclusive-allocation)이 실제로 필요한 가속기류에 한정해 적용하는 것이 실용적이다.

### gRPC 등록·할당 API
- 원문 표현: "Following a successful registration, the device plugin sends the kubelet the list of devices it manages, and the kubelet is then in charge of advertising those resources to the API server as part of the kubelet node status update."
- 정의: device plugin이 gRPC로 kubelet에 자신이 관리하는 장치 목록을 스트리밍 보고(`ListAndWatch`)하고, 파드 스케줄링 시 kubelet이 `Allocate`를 호출해 실제 장치를 컨테이너에 연결하는 절차. `GetPreferredAllocation`으로 선호 장치 조합을 조회하고 `PreStartContainer`로 컨테이너 시작 전 초기화를 수행할 수 있다.
- 역할: Kubernetes가 담당하는 것은 "장치를 파드에 배정"하는 것까지이며, 배정된 가속기를 실제로 어떻게 초기화·사용하는지는 애플리케이션의 실행 런타임 추상화 계층의 책임이다 — Device Plugin API 자체를 상위 애플리케이션 로직이 직접 호출하지 않는 편이 계층 분리에 유리하다.

### Exclusive/Integer 자원 제약
- 원문 표현: "Extended resources are only supported as integer resources and cannot be overcommitted." / "Devices cannot be shared between containers."
- 정의: extended resource로 노출된 장치는 정수 단위로만 요청 가능하며, 한 번 컨테이너에 할당되면 파드 종료 전까지 다른 컨테이너와 공유되지 않는다.
- 역할: 가속기가 부족할 때 대체 후보를 재평가해야 하는 이유가 된다 — 정수·비공유 제약 때문에 가속기가 이미 할당된 상태에서는 우선순위 낮은 기능을 축소하는 것 외에 즉시 자원을 회수할 방법이 없다.

## 4. 구조 및 흐름
1. 벤더가 device plugin을 구현해 수동 배포 또는 DaemonSet으로 각 노드에 배포한다.
2. device plugin이 kubelet에 등록하고, `ListAndWatch` gRPC 스트림으로 관리 중인 장치 목록을 지속 보고한다.
3. kubelet이 보고받은 장치를 `vendor-domain/resourcetype` 형식의 extended resource로 API 서버에 노드 상태 업데이트의 일부로 반영한다.
4. 파드가 해당 extended resource를 요청하면 스케줄러가 노드를 선택하고, kubelet이 `Allocate`를 호출해 실제 장치 노드/환경변수/마운트를 컨테이너에 연결한다.
5. 필요 시 `GetPreferredAllocation`으로 선호 장치 조합을 조회하고, `PreStartContainer`로 컨테이너 시작 전 초기화를 수행한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Device Plugin은 Kubernetes 코어 수정 없이 벤더 하드웨어를 통합하는 공식 프레임워크다 | "Instead of customizing the code for Kubernetes itself, vendors can implement a device plugin that you deploy either manually or as a DaemonSet." |
| 이 프레임워크는 Kubernetes v1.26부터 안정화된 기능이다 | "Feature state: Stable since Kubernetes v1.26" |
| 장치 자원은 정수 단위로만 스케줄링되며 컨테이너 간 공유되지 않는다 | "Extended resources are only supported as integer resources and cannot be overcommitted." / "Devices cannot be shared between containers." |

## 6. 한계 및 부족한 점
- 공식 문서가 명시하는 제약: "Extended resources are only supported as integer resources and cannot be overcommitted."와 "Devices cannot be shared between containers."는 세밀한 fractional 공유(예: GPU time-slicing)가 이 프레임워크 기본 기능만으로는 지원되지 않음을 뜻한다.
- 일반적인 주의점: Device Plugin은 "장치를 파드에 배정"하는 스케줄링 계층까지만 책임진다. 상위 애플리케이션이 특정 모델 파일 형식, 추론 엔진, 가속기 API에 직접 의존하지 않도록 하는 것은 Device Plugin이 대신 보장해주지 않으며, 별도의 실행 런타임 추상화 계층이 필요하다. 즉 gRPC로 장치가 컨테이너에 노출된 이후에도, 그 장치를 어떻게 초기화·사용할지는 애플리케이션 쪽에서 별도로 추상화해야 한다.
- 실무적 판단: 모든 특수 장치를 custom Device Plugin으로 만드는 것은 과도할 수 있다. 이는 공식 문서 자체가 명시하는 한계라기보다, 배타적 할당이 실제로 필요한 가속기류에만 한정해 적용하는 것이 합리적이라는 적용 범위 판단에 가깝다.

## 7. 원문 기반 핵심 문장
> "Kubernetes provides a device plugin framework that you can use to advertise system hardware resources to the Kubelet."
