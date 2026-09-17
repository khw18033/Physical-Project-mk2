# KubeEdge Mapper Architecture

## 메타데이터
- categories: Mapper, Device Twin, Device Controller, Mapper Framework
- domain: [[배포·오케스트레이션]]
- source: KubeEdge Authors (CNCF 프로젝트). "Mapper." KubeEdge Documentation, Concept > Device, 최종 갱신 2025-06-14.
- url: https://kubeedge.io/docs/concept/device/mapper/
- year: 확인 필요 (문서 최종 갱신일 2025-06-14는 확인되었으나, Mapper 개념 최초 발행 연도는 확인하지 못함)
- authors: KubeEdge 프로젝트 (CNCF)
- venue: KubeEdge 공식 문서

## 1. 핵심 요약
- Mapper는 KubeEdge와 물리 장치 사이의 manager로, 장치 데이터를 set/get하고 장치 상태를 얻어 보고하는 역할을 한다.
- KubeEdge는 cloud측 Device Controller(CRD 기반 장치 정의·제어), edge측 Device Twin(값/상태 저장 및 메시지 중계), device측 Mapper(프로토콜별 실제 통신)의 3계층 구조로 동작한다.
- DMI(Device Management Interface)가 Device Twin 안에서 Mapper 등록과 Device Instance/Model 전달을 담당한다.
- 현재는 하나의 Mapper가 하나의 프로토콜을 담당하는 장치들만 관리하며, 동일 프로토콜에 대한 복수 Mapper의 동시 운용은 공식적으로 향후 과제(future work)로 명시되어 있다.
- Mapper Framework라는 코드 생성 도구를 제공해 사용자가 새 프로토콜용 Mapper를 쉽게 만들 수 있도록 지원한다.

## 2. 문서 목적
- 해결하려는 문제: 서로 다른 프로토콜을 쓰는 다양한 edge 장치를 KubeEdge의 cloud/edge 제어면과 통일된 방식으로 연결·관측·제어해야 하는 문제.
- 기술적 목표: 장치별 프로토콜 종속 로직을 Mapper라는 독립 구성요소로 격리하고, Device Twin이 그 값을 저장·중계해 Device Controller(cloud)와 연결하는 구조를 표준화하는 것.
- 다루는 범위: Mapper의 역할 정의, Device Controller/Device Twin/Mapper 3자 관계, DMI를 통한 Mapper 등록과 Device Instance/Model 전달, Mapper Framework 코드 생성 도구의 존재.

## 3. 핵심 개념 상세
### Mapper
- 원문 표현: "Mapper is a manager between KubeEdge and devices. It could set/get device data, get and report the device status."
- 정의: 장치측(edge의 device 계층)에 위치하며, 특정 프로토콜을 사용하는 장치들과 통신해 데이터를 읽고 쓰고 상태를 보고하는 구성요소.
- 역할: 벤더·프로토콜별 통신 로직을 상위 제어면과 분리된 독립 구성요소로 격리하는 어댑터 패턴의 대표적 선례다. 장치마다 다른 프로토콜(Modbus, OPC UA, BLE 등)을 다뤄야 하는 IoT/엣지 시스템에서, 이 계층을 분리해 두면 새 프로토콜 지원을 추가할 때 상위 제어 로직을 건드리지 않아도 된다.

### Device Controller / Device Twin
- 원문 표현: "Device Controller is on the cloud side, it uses CRD to define and control devices. The Device Twin is on the edge side, it stores the value/status from the Mapper and transfers the messages with Device Controller and Mapper."
- 정의: cloud측에서 Kubernetes CRD로 장치를 정의·제어하는 Device Controller와, edge측에서 Mapper가 보고한 값/상태를 저장하고 Device Controller와의 메시지를 중계하는 Device Twin으로 구성된 계층 구조.
- 역할: KubeEdge 런타임 자체를 채택하지 않더라도, "device-edge-cloud 3계층으로 책임을 분리한다"는 아키텍처 패턴은 다른 엣지 컴퓨팅 시스템에서도 참고할 수 있는 일반적인 구조다 — cloud는 선언적 정의와 제어를, edge는 상태 저장과 중계를, device 계층은 실제 프로토콜 통신을 담당하는 방식으로 책임을 나눈다.

### DMI(Device Management Interface)와 Mapper 등록
- 원문 표현: "Meanwhile, DMI in the Device Twin is used for registering Mapper and transfer Device Instance and Device Model to user Mapper." / "DMI will package the device and model using the same protocol into lists and send them to the Mapper of this protocol."
- 정의: Device Twin 내부에서 Mapper를 등록하고, 동일 프로토콜을 쓰는 Device Instance/Model 정보를 해당 Mapper에 목록 형태로 전달하는 인터페이스.
- 역할: 새 장치나 프로토콜이 추가될 때 상위 제어면 코드를 수정하지 않고 등록 정보만으로 연결할 수 있어야 한다는 확장성 원칙의 참고 사례다. 이런 등록 기반 확장 구조는 플러그인 아키텍처 전반에서 반복적으로 나타나는 패턴이다.

### Mapper Framework
- 원문 표현: "Users can easily generate their own Mapper through Mapper Framework."
- 정의: 사용자가 새 프로토콜용 Mapper 코드를 처음부터 작성하지 않고, 코드 생성 방식으로 만들 수 있도록 지원하는 KubeEdge 전용 도구.
- 역할: 특정 플랫폼 전용 코드 생성 도구의 예시로, Mapper라는 역할 분리 개념 자체와 그 개념을 구현하는 특정 프레임워크·생성 도구는 구분해서 참고할 필요가 있음을 보여준다. 개념(프로토콜별 어댑터 분리)은 재사용 가능하지만 특정 도구에 대한 종속성까지 함께 가져올 필요는 없다.

## 4. 구조 및 흐름
1. Cloud측 Device Controller가 Kubernetes CRD로 장치(Device Instance/Model)를 정의한다.
2. Edge측 Device Twin이 DMI를 통해 해당 프로토콜을 다루는 Mapper를 등록시키고, Device Instance/Model 정보를 그 Mapper에 전달한다.
3. Mapper가 실제 물리 장치와 프로토콜 수준에서 통신하며 데이터를 set/get하고 장치 상태를 얻는다.
4. Mapper가 얻은 값/상태를 Device Twin이 저장하고, Device Controller와 메시지를 주고받아 cloud측에서 최신 상태를 유지한다.
5. 새 프로토콜이 필요하면 Mapper Framework로 새 Mapper를 생성해 등록하는 방식으로 확장하며, 기존 Device Controller/Device Twin 코드는 수정하지 않는다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Mapper는 KubeEdge와 장치 사이의 매니저로서 프로토콜 종속 로직을 격리한다 | "Mapper is a manager between KubeEdge and devices. It could set/get device data, get and report the device status." |
| Device Controller/Device Twin/Mapper는 각각 cloud/edge/device 계층 책임을 분리한다 | "Device Controller is on the cloud side... The Device Twin is on the edge side, it stores the value/status from the Mapper and transfers the messages with Device Controller and Mapper." |
| 새 프로토콜은 기존 코드 수정 없이 Mapper 등록만으로 확장할 수 있다 | DMI가 "package the device and model using the same protocol into lists and send them to the Mapper of this protocol"이며, Mapper Framework로 신규 Mapper를 생성할 수 있음 |

## 6. 한계 및 부족한 점
- 공식 문서가 명시하는 한계: 현재는 하나의 프로토콜을 하나의 Mapper가 담당하는 구조이며, 동일 프로토콜에 대해 같은 노드에서 여러 Mapper를 동시에 운용하는 것은 아직 지원되지 않는다 — "In the future we will explore the possibility of two or more Mappers with same protocol running on same node."
- 이미 다른 오케스트레이션 런타임(예: 범용 Kubernetes 기반 클러스터 관리)을 채택한 시스템이라면, KubeEdge의 Device Controller(CRD)·Device Twin·EdgeCore를 통째로 설치하는 것은 기능이 중복되고 별도의 오케스트레이션 런타임 종속성만 추가하는 결과를 낳을 수 있다. 이런 경우 KubeEdge 런타임 자체는 도입하지 않고 "Mapper를 통한 프로토콜별 로직 격리"라는 설계 패턴만 선별적으로 채택하는 것이 실용적인 절충안이 된다.
- 이번 조사에서는 telemetry 수집 주기, 프로토콜별 Mapper 구현 세부(DMI의 구체적 gRPC 인터페이스 정의 등)까지는 원문으로 깊이 확인하지 못했다 — 필요하면 KubeEdge Mapper Framework 관련 별도 문서를 추가로 조회해 보강해야 한다.

## 7. 원문 기반 핵심 문장
> "Mapper is a manager between KubeEdge and devices. It could set/get device data, get and report the device status."
