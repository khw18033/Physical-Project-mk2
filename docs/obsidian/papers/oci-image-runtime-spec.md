# OCI Image Specification & OCI Runtime Specification

## 메타데이터
- categories: Image Manifest, Content-addressable Layer, Image Config, Image Index / Multi-arch, Runtime Configuration, Container Lifecycle
- domain: [[배포·오케스트레이션]]
- source: Open Container Initiative. "OCI Image Format Specification" and "OCI Runtime Specification." specs.opencontainers.org, n.d.
- url: https://specs.opencontainers.org/image-spec/ , https://specs.opencontainers.org/runtime-spec/
- year: 확인 필요 (image-spec 최신 태그 v1.1.1, runtime-spec 최신 태그 v1.3.0 — GitHub 저장소 참조 기준. 공식 발행 연도는 landing 페이지에서 확인되지 않음)
- authors: Open Container Initiative (OCI)
- venue: OCI spec (industry specification, IETF/W3C RFC 아님)

## 1. 핵심 요약
- OCI Image Specification의 목표는 "container image를 빌드·전송·실행 준비하기 위한 상호운용 가능한 도구를 만들 수 있게 하는 것"이다.
- image manifest는 하나 이상의 filesystem layer changeset의 content-addressable identity를 포함해 이미지의 내용과 의존성에 대한 메타데이터를 담는다.
- layer는 컨테이너 파일시스템을 기술하는 changeset(변경 집합)이며, config는 layer 순서와 이미지 구성을 결정해 runtime bundle로 변환 가능하게 하는 문서다.
- image index는 여러 manifest를 가리키는 상위 레벨 manifest로, 플랫폼별로 다른 이미지 구현을 제공하는 데 쓰인다(멀티 아키텍처 지원).
- OCI Runtime Specification의 목표는 컨테이너의 configuration, execution environment, lifecycle을 명세하는 것이며, `config.json`으로 컨테이너 구성을 정의하고 create/start/kill/delete 표준 오퍼레이션과 creating/created/running/stopped 상태로 lifecycle을 정의한다.

## 2. 문서 목적
- 해결하려는 문제: 컨테이너 이미지 포맷과 컨테이너 실행 방식이 특정 벤더·런타임 구현에 종속되면, 이미지를 빌드하는 도구와 실행하는 런타임이 서로 다른 생태계에서 상호운용되지 못하는 문제.
- 기술적 목표: (image-spec) 이미지의 내용·레이어·설정·플랫폼 정보를 content-addressable하고 표준화된 방식으로 표현하는 것. (runtime-spec) 컨테이너의 설정 파일 포맷, 실행 환경, 표준 lifecycle 오퍼레이션을 런타임 구현체와 무관하게 정의하는 것.
- 다루는 범위: image-spec은 manifest, layer, config, image index(멀티 플랫폼) 포맷을 다루고 실제 빌드 도구(Docker 등)나 레지스트리 프로토콜 자체는 별도 규격(distribution-spec)으로 분리한다. runtime-spec은 `config.json` 스키마와 create/start/kill/delete 표준 오퍼레이션, 컨테이너 상태 전이를 다루며 특정 컨테이너 엔진(containerd, runc 등)의 구현 세부사항은 다루지 않는다.

## 3. 핵심 개념 상세
### Image Manifest
- 원문 표현: "the image manifest contains metadata about the contents and dependencies of the image including the content-addressable identity of one or more filesystem layer changeset archives that will be unpacked to make up the final runnable filesystem"
- 정의: 이미지의 내용·의존성 메타데이터와 layer들의 content-addressable identity(digest)를 담는 문서.
- 역할: 실행 단위(마이크로서비스, 배치 작업 등) 이미지가 "어떤 layer들로 구성되어 있는가"를 검증 가능한 방식으로 기술한다. 배포 감사나 장애 재현 시 애플리케이션 버전 태그만으로는 "정확히 어떤 바이트가 실행되었는가"를 보장할 수 없는데, manifest의 digest는 이를 검증 가능하게 만드는 근거가 된다.

### Filesystem Layer
- 원문 표현: "a changeset that describes a container's filesystem"
- 정의: 컨테이너 파일시스템에 대한 변경 집합(추가/삭제된 파일 등)을 나타내는 아카이브.
- 역할: 이미지 빌드 시 Dockerfile의 각 명령이 새 layer를 만들고(§ docker.md 참고), 여러 layer가 순서대로 겹쳐 최종 실행 가능한 파일시스템을 구성한다. layer가 content-addressable하므로 동일 layer를 여러 이미지가 공유·재사용할 수 있다.

### Image Config
- 원문 표현: "a document determining layer ordering and configuration of the image suitable for translation into a runtime bundle"
- 정의: layer 순서와 이미지 실행 설정(엔트리포인트, 환경변수 등)을 담아 runtime bundle로 변환 가능하게 만드는 문서.
- 역할: image-spec의 config가 runtime-spec의 `config.json`(runtime bundle)으로 변환되는 연결고리다. 즉 "빌드 시점의 이미지 설정"과 "실행 시점의 컨테이너 설정"을 잇는 표준 경계이며, Kubernetes 계열 오케스트레이터가 컨테이너 런타임(containerd 등)을 통해 이미지를 pull한 뒤 실제 컨테이너를 띄우는 과정이 이 변환에 해당한다.

### Content-addressable Identity / Digest
- 원문 표현: "content-addressable identity of one or more filesystem layer changeset archives"
- 정의: 콘텐츠 자체의 해시값(digest)으로 layer·manifest를 식별하는 방식.
- 역할: 이미지나 layer의 내용이 조금이라도 바뀌면 digest가 달라지므로, "정확히 어떤 바이트가 실행되었는가"를 검증할 수 있는 근거가 된다. Sigstore Cosign 같은 서명 도구가 이 digest에 서명을 붙여 공급망 보안(supply chain security)의 기반으로 삼는 것이 업계의 일반적인 활용 방식이다.

### Image Index / Multi-architecture 지원
- 원문 표현: "The image index is a higher-level manifest which points to a list of manifests and descriptors. Typically, these manifests may provide different implementations of the image, possibly varying by platform or other attributes."
- 정의: 여러 개의 manifest(예: linux/amd64용, linux/arm64용)를 가리키는 상위 레벨 manifest.
- 역할: 소형 ARM 기반 장치와 x86 서버처럼 서로 다른 아키텍처의 노드가 섞여 있는 환경에서, 동일한 논리적 이미지 이름으로 배포하더라도 각 노드가 자신의 플랫폼에 맞는 manifest를 자동으로 선택하게 하는 표준 메커니즘이다.

### Runtime Configuration(`config.json`)
- 원문 표현: "A container's configuration is specified as the `config.json` for the supported platforms and details the fields that enable the creation of a container."
- 정의: 컨테이너를 생성하는 데 필요한 필드(마운트, 프로세스, 네임스페이스 등)를 담은 설정 문서.
- 역할: image-spec의 image config가 변환되어 만들어지는 실행 시점의 컨테이너 명세이며, "특권 모드(privileged)나 호스트 네임스페이스 공유(hostPID 등)를 기본값으로 두지 않는다"는 최소 권한 원칙 같은 보안 정책이 실제로 강제되는 지점이다.

### Container Lifecycle / 표준 오퍼레이션
- 원문 표현(목적): "The Open Container Initiative Runtime Specification aims to specify the configuration, execution environment, and lifecycle of a container." / (오퍼레이션) Create: "This operation MUST create a new container"; Start: "This operation MUST run the user-specified program as specified by process"; Kill: "This operation MUST send the specified signal to the container process"; Delete: "Deleting a container MUST delete the resources that were created during the create step".
- 정의: 컨테이너는 creating → created → running → stopped 상태를 거치며, create/start/kill/delete라는 표준화된 오퍼레이션으로 이 상태를 전이시킨다.
- 역할: OCI runtime lifecycle(create/start/kill/delete)은 어디까지나 컨테이너 프로세스의 생명주기를 다루는 계약이며, 그 컨테이너가 수행하는 업무 로직의 상태(예: 작업 진행 중/취소 요청됨/완료됨 같은 애플리케이션 수준 상태 전이)와는 별개의 계약이다. 오케스트레이터가 컨테이너를 kill하는 것과 애플리케이션이 자신의 작업을 안전하게 취소·정지하는 것은 서로 다른 책임이므로 혼동해서는 안 된다.

## 4. 구조 및 흐름
1. (image-spec) 빌드 도구(Docker 등)가 소스 코드와 의존성으로 하나 이상의 filesystem layer를 만든다.
2. layer들의 digest와 순서를 담은 image config를 생성하고, config와 layer들의 digest를 묶어 image manifest를 만든다.
3. 여러 아키텍처를 지원해야 하면 각 아키텍처별 manifest를 만들고 이를 가리키는 image index를 최상위에 둔다.
4. 이미지는 digest 기반으로 레지스트리에 저장·배포되며, 실행 노드는 자신의 플랫폼에 맞는 manifest를 image index에서 선택해 pull한다.
5. (runtime-spec) 컨테이너 엔진(containerd 등)이 pull한 이미지의 config를 `config.json` 형태의 runtime configuration으로 변환한다.
6. 표준 오퍼레이션 create가 `config.json`을 적용해 컨테이너를 creating 상태로 만들고, create가 끝나면 created 상태가 된다.
7. start 오퍼레이션이 사용자 지정 프로그램을 실행해 running 상태로 전이시키고, kill 오퍼레이션이 시그널을 보내 종료를 유도하며, 프로세스가 종료되면 stopped 상태가 된다.
8. delete 오퍼레이션이 stopped 상태의 컨테이너가 create 단계에서 만든 자원을 정리한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| OCI Image spec의 목표는 상호운용 가능한 빌드·전송·실행 준비 도구 생태계를 만드는 것이다 | "The goal of this specification is to enable the creation of interoperable tools for building, transporting, and preparing a container image to run." |
| 이미지는 content-addressable한 layer의 집합으로 구성되며 image index로 멀티플랫폼을 지원한다 | manifest 정의 인용("content-addressable identity of one or more filesystem layer changeset archives"), image index 정의 인용("may provide different implementations of the image, possibly varying by platform") |
| OCI Runtime spec은 컨테이너의 설정·실행 환경·lifecycle을 명세하며, 이는 create/start/kill/delete라는 명시적 오퍼레이션으로 구현된다 | "aims to specify the configuration, execution environment, and lifecycle of a container." + 각 오퍼레이션의 MUST 문장 |

## 6. 한계 및 부족한 점
- OCI 스펙 landing 페이지 자체는 목차·메타데이터 위주였고, 세부 정의는 GitHub의 `spec.md`/`runtime.md` 하위 문서에서 확인해야 했다 — 이번 조사에서 image-index.md, config.md, bundle.md 등 더 세부적인 하위 문서까지 전수 확인하지는 못했다.
- image-spec의 정확한 발행 연도(버전별 릴리스 날짜)는 landing 페이지에서 명시적으로 확인되지 않았다 — GitHub 저장소의 태그(v1.1.1, v1.3.0)만 확인했으며 "확인 필요"로 남긴다.
- OCI 스펙은 이미지 포맷(image-spec)과 이를 만드는 빌드 도구, 그리고 이를 실행하는 런타임(runtime-spec)을 서로 다른 문서로 분리해 정의한다. 이 구조적 분리 자체는 스펙 목차와 범위 서술에서 확인되지만, "따라서 특정 빌드 도구(예: Docker)가 실행 환경에 설치되어 있을 필요가 없다"는 결론은 이 구조에서 유추한 것이며 스펙이 이를 직접 문장으로 명시하는지는 이번 조사에서 확인하지 못했다.
- runtime-spec의 상세 lifecycle 문서(`runtime.md`)에서 상태 전이 시 발생 가능한 오류 조건, hook 실행 시점 등 세부 규칙은 이번 조사 범위에서 깊이 있게 다루지 않았다.

## 7. 원문 기반 핵심 문장
> "The Open Container Initiative Runtime Specification aims to specify the configuration, execution environment, and lifecycle of a container."
