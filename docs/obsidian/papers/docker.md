# Docker / Dockerfile

## 메타데이터
- categories: Dockerfile 빌드 명령, 이미지 Layer, Layer Caching
- domain: [[배포·오케스트레이션]]
- source: Docker Inc. "Dockerfiles." Docker Docs, Build concepts, n.d.
- url: https://docs.docker.com/build/concepts/dockerfile/
- year: 확인 필요 (Docker 공식 문서 페이지에 발행/개정 연도가 명시적으로 표기되지 않음)
- authors: Docker Inc.
- venue: Docker 공식 문서 (Docker Docs)

## 1. 핵심 요약
- Dockerfile은 소스 코드를 빌드하기 위한 명령어들을 담은 텍스트 파일이다.
- Docker는 Dockerfile에 적힌 명령을 순서대로 읽어 실행함으로써 이미지를 빌드한다.
- Docker 이미지는 layer들로 구성되며, Dockerfile의 각 빌드 명령이 하나의 layer(이전 layer 대비 변경분, delta)를 만든다.
- 어떤 layer가 바뀌면 그 layer는 다시 빌드되어야 하고, 그 뒤에 오는 모든 layer도 함께 영향을 받아 재빌드된다(layer caching의 무효화 규칙).
- Docker는 OCI 호환 이미지를 만들 수 있는 여러 빌드 도구(Docker, Buildah, Kaniko, BuildKit 등) 중 하나이며, 실행 환경이 최종적으로 요구하는 것은 특정 빌드 도구가 아니라 OCI 호환 이미지 그 자체다.

## 2. 문서 목적
- 해결하려는 문제: 애플리케이션을 특정 실행 환경에 맞춰 수동으로 설치·설정하면 노드마다 환경이 달라져 "내 컴퓨터에서는 되는데" 류의 재현성 문제가 발생하는 문제.
- 기술적 목표: 소스 코드와 의존성 설치·설정 절차를 텍스트 명령어(Dockerfile)로 선언하고, 이를 결정적으로 재현 가능한 이미지 빌드 절차로 자동화하는 것.
- 다루는 범위: Dockerfile 명령 문법과 빌드 절차, 이미지가 layer로 구성되는 방식, 빌드 캐시가 layer 단위로 재사용·무효화되는 규칙. 이미지가 실행되는 런타임(컨테이너 엔진)이나 이미지 포맷 표준 자체(OCI Image Spec)의 세부 규격은 별도 문서에서 다룬다.

## 3. 핵심 개념 상세
### Dockerfile
- 원문 표현: "A Dockerfile is a text file containing instructions for building your source code."
- 정의: 이미지를 빌드하기 위한 명령어들을 담은 텍스트 파일.
- 역할: 애플리케이션의 의존성 설치, 환경 설정, 실행 명령을 코드로 선언해 버전 관리 시스템에 함께 저장할 수 있게 하는 소스이며, "실행 환경을 컨테이너로 패키징해 재현성을 확보한다"는 일반적인 배포 관행을 구현하는 대표적인 수단이다.

### 이미지 빌드(Building)
- 원문 표현: "Docker builds images by reading the instructions from a Dockerfile."
- 정의: Docker가 Dockerfile의 명령을 순서대로 읽어 실행하며 이미지를 생성하는 절차.
- 역할: 개발자가 작성한 Dockerfile을 실제 실행 가능한 OCI 호환 이미지(image manifest + layer + config)로 변환하는 빌드 도구의 동작이다. 실행 환경이 실제로 요구하는 것은 OCI 호환 이미지라는 결과물이며, Docker는 그 결과물을 만드는 여러 가능한 구현 중 하나다.

### 이미지의 Layer 구성
- 원문 표현: "Docker images consist of layers. Each layer is the result of a build instruction in the Dockerfile. Layers are stacked sequentially, and each one is a delta representing the changes applied to the previous layer."
- 정의: 이미지는 순차적으로 쌓이는 layer들로 구성되며, 각 layer는 Dockerfile의 한 빌드 명령이 만들어낸, 이전 layer 대비 변경분(delta)이다.
- 역할: OCI Image Specification이 정의하는 "filesystem layer changeset"(`oci-image-runtime-spec.md` 참고)을 Docker가 Dockerfile 명령 단위로 실제로 생성하는 방식이다. 즉 Dockerfile의 각 줄이 OCI 표준이 정의하는 layer 하나에 대응한다.

### Layer Caching
- 원문 표현: "Whenever a layer changes, that layer will need to be re-built. If a layer changes, all other layers that come after it are also affected."
- 정의: 특정 layer의 입력(명령, 파일 등)이 바뀌면 그 layer는 다시 빌드되어야 하며, 그보다 뒤에 위치한 모든 layer도 캐시를 재사용하지 못하고 함께 재빌드되는 규칙.
- 역할: Dockerfile 안에서 자주 바뀌지 않는 명령(의존성 설치 등)을 앞쪽에, 자주 바뀌는 명령(소스 코드 복사 등)을 뒤쪽에 배치하는 순서 설계가 빌드 속도에 직접 영향을 준다는 근거를 제공한다. CI/CD 파이프라인처럼 이미지를 빈번하게 재빌드·재배포하는 환경일수록 이 순서 설계가 반복 빌드 시간과 배포 주기에 직접적인 영향을 준다.

## 4. 구조 및 흐름
1. 개발자가 Dockerfile에 베이스 이미지 선택, 의존성 설치, 소스 코드 복사, 실행 명령 등을 순서대로 명령어로 작성한다.
2. Docker가 Dockerfile을 위에서 아래로 읽으며 각 명령을 실행하고, 명령마다 새 layer를 생성한다.
3. 이전 빌드에서 특정 명령의 입력이 바뀌지 않았다면 Docker는 캐시된 layer를 재사용하고, 바뀐 시점부터는 그 이후 모든 명령을 다시 실행해 새 layer를 만든다.
4. 최종적으로 쌓인 layer들과 실행 설정이 OCI Image Specification이 정의하는 manifest/config 형태로 패키징되어 image가 완성된다.
5. 완성된 이미지는 레지스트리에 저장되고, 실행 노드(Kubernetes/containerd 등 오케스트레이터와 컨테이너 런타임)가 이를 pull해 OCI Runtime Specification에 따라 컨테이너로 실행한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Dockerfile은 소스 코드 빌드 절차를 명령어로 선언하는 텍스트 파일이다 | "A Dockerfile is a text file containing instructions for building your source code." |
| 이미지는 여러 layer가 순차적으로 쌓여 구성되며 각 layer는 하나의 빌드 명령 결과다 | "Docker images consist of layers. Each layer is the result of a build instruction in the Dockerfile." |
| layer 변경은 그 이후 모든 layer의 재빌드를 유발한다 | "Whenever a layer changes, that layer will need to be re-built. If a layer changes, all other layers that come after it are also affected." |

## 6. 한계 및 부족한 점
- 이번 조사에서는 Docker 공식 문서가 Dockerfile 접근 방식 자체의 한계(예: 대형 멀티스테이지 빌드의 복잡도, 캐시 무효화의 예측 어려움)를 스스로 명시하는 문장은 확보하지 못했다 — 원문 확인 안 됨.
- 빌드 시점 도구(Docker)와 실행 시점 컨테이너 런타임(containerd, CRI-O 등)은 별개의 구성요소다. Kubernetes 계열 오케스트레이터는 CRI(Container Runtime Interface)를 통해 containerd/CRI-O 같은 런타임으로 OCI 이미지를 직접 소비하므로, 이미지를 빌드할 때 Docker를 사용했더라도 그 이미지를 실행하는 노드에 Docker 데몬 자체가 설치되어 있을 필요는 없다 — 다만 이는 OCI/CRI 생태계의 일반적인 구조에서 도출되는 결론이며, Docker 공식 문서가 이 지점을 직접 언급하지는 않는다.
- Docker 공식 문서 페이지 자체에서 발행/최종 개정 날짜를 확인하지 못해 `year` 필드를 "확인 필요"로 남겼다.
- 이 문서는 Dockerfile 개념 페이지와 빌드 캐시 페이지 일부만 확인했으며, BuildKit, multi-stage build, `.dockerignore` 등 Dockerfile 생태계의 다른 세부 기능은 이번 조사 범위에 포함하지 않았다.

## 7. 원문 기반 핵심 문장
> "Docker images consist of layers. Each layer is the result of a build instruction in the Dockerfile. Layers are stacked sequentially, and each one is a delta representing the changes applied to the previous layer."
