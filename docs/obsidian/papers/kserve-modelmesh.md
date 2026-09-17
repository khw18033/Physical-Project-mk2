# KServe ModelMesh

## 메타데이터
- categories: LRU 기반 모델 캐싱, Multi-Model Serving, OCI 이미지 기반 모델 배포(Modelcars), 동적 모델 로드·언로드
- domain: [[배포·오케스트레이션]], [[엣지 실행·자원]]
- source: KServe 프로젝트. "ModelMesh." KServe Documentation, v0.16.
- url: https://kserve.github.io/website/docs/0.16/admin-guide/modelmesh
- year: 확인 안 됨 (KServe 0.16 버전 문서 기준)
- authors: KServe 프로젝트 기여자
- venue: 공식 문서 (KServe Documentation)

## 1. 핵심 요약
- ModelMesh는 모델 변경이 빈번하고 모델 수가 많은(수백~수천 개) 환경, 특히 predictive inference workload에 적합한 high-scale, high-density model serving을 제공한다.
- 자주 호출되는 모델은 메모리에 유지(caching)하고, 메모리가 가득 차면 가장 오래 사용되지 않은 모델부터 자동으로 내리는 LRU eviction 정책을 사용한다.
- 모델은 필요할 때 동적으로 로드·언로드되며, 사용 패턴을 근거로 향후 필요할 모델을 미리 적재하는 predictive pre-loading도 지원한다.
- 여러 모델이 동일 런타임 파드를 공유(resource sharing)하고, 가용 자원 전반에 걸쳐 모델을 최적 배치(efficient packing)한다.
- 대용량 모델은 OCI 컨테이너 이미지로 패키징해 `oci://` 스키마로 참조하는 Modelcars 방식을 지원하며, 컨테이너 이미지 캐싱을 재사용해 반복 다운로드로 인한 시작 지연과 디스크 중복 사용을 줄인다.

## 2. 문서 목적
- 해결하려는 문제: 모델 개수가 수백~수천 개로 늘어나고 변경이 빈번한 환경에서 모델마다 전용 서빙 인스턴스를 배정하면 자원 낭비가 크고 잦은 모델 교체를 감당하기 어렵다. 또한 대용량 모델을 매번 원격 저장소에서 새로 내려받으면 시작 지연과 저장 공간 중복이 발생한다.
- 기술적 목표: 다수의 모델이 소수의 런타임 파드를 공유하도록 배치하고, 자주 쓰는 모델은 메모리에 유지·자주 안 쓰는 모델은 자동으로 회수(LRU)하며, 대용량 모델은 OCI 이미지로 패키징해 컨테이너 이미지 캐싱 메커니즘을 재사용하는 것.
- 다루는 범위: ModelMesh의 다중 모델 관리(동적 로드·언로드, 캐싱·LRU eviction, predictive pre-loading, 배치)와, 별도 저장 방식인 OCI 이미지/Modelcars 기반 모델 패키징·전달 방식.

## 3. 핵심 개념 상세
### 고밀도 다중 모델 서빙 (High-Density Multi-Model Serving)
- 원문 표현: "ModelMesh installation provides high-scale, high-density model serving for scenarios with frequent model changes and large numbers of models, making it particularly well-suited for predictive inference workloads."
- 정의: 수백~수천 개 모델이 존재하고 변경이 빈번한 환경을 대상으로, 다수 모델이 동일 런타임 파드를 공유하도록 하는 서빙 방식.
- 역할: 모델 1개당 전용 파드를 배정하는 방식 대비 컴퓨팅·메모리 자원을 훨씬 적게 사용하면서 대규모 모델 집합을 서빙할 수 있게 한다.

### 모델 캐싱과 LRU Eviction
- 원문 표현: "Model Caching: Frequently accessed models stay in memory" / "LRU Eviction: Least recently used models are evicted when memory is full"
- 정의: 자주 호출되는 모델은 메모리에 유지하고, 메모리가 가득 차면 가장 오랫동안 사용되지 않은 모델부터 자동으로 내리는 캐시 정책.
- 역할: 제한된 메모리 자원 안에서 응답 지연이 중요한 모델은 상시 대기 상태로 유지하고, 자주 쓰이지 않는 모델은 자동으로 자원을 회수해 재배분한다.

### 동적 로드·언로드와 예측적 사전 로딩
- 원문 표현: "Models are loaded and unloaded as needed" / "Models can be pre-loaded based on usage patterns"
- 정의: 요청이 들어올 때 필요한 모델을 즉시 메모리에 적재하고 더 이상 필요 없을 때 내리며, 사용 패턴을 근거로 향후 필요할 모델을 미리 적재해두는 방식.
- 역할: 모든 모델을 상시 적재하지 않고 실제 요청 흐름에 맞춰 적재 상태를 유지함으로써 콜드 스타트 지연과 유휴 자원 점유를 함께 줄인다.

### 지능적 배치 (Intelligent Placement / Efficient Packing)
- 원문 표현: "Optimal placement of models across available resources" / "Efficient Packing"
- 정의: 여러 런타임 파드와 노드 자원 상황을 고려해 모델을 어디에 적재할지 최적으로 배치하는 정책.
- 역할: 특정 파드·노드에 부하가 몰리지 않도록 모델 배치를 분산·최적화해 전체 클러스터 자원 활용도를 높인다.

### OCI 이미지 기반 모델 패키징 (Modelcars)
- 원문 표현: "Enables modelcars for efficient model serving from OCI images" / "By avoiding repetitive downloads of large models, startup delays are significantly minimized." / "runs a `ln -sf /proc/$$/root/models /mnt/` command to create a symbolic link on a shared empty volume"
- 정의: 모델 데이터를 `/models` 디렉터리에 담은 컨테이너 이미지(OCI 이미지)로 빌드해 레지스트리에 push하고, `oci://` 스키마로 참조하면 modelcar 컨테이너가 공유 프로세스 네임스페이스를 통해 심볼릭 링크로 서빙 컨테이너에 모델 데이터를 직접 노출하는 방식.
- 역할: 원격 저장소(S3 등)에서 매번 모델을 새로 내려받는 대신, 컨테이너 이미지 레이어 캐싱과 `IfNotPresent` pull 정책을 재사용해 반복 다운로드를 피하고 시작 지연과 디스크 중복 사용을 줄인다.

## 4. 구조 및 흐름
1. 모델 서빙 요청이 들어오면 ModelMesh가 해당 모델이 이미 로드된 런타임 파드가 있는지 확인한다.
2. 로드되어 있지 않으면 자원·배치 조건에 맞는 런타임 파드를 선택해(Efficient Packing) 모델을 동적으로 로드한다.
3. 메모리가 가득 차면 LRU 정책에 따라 가장 오래 사용되지 않은 모델을 언로드해 공간을 확보한다.
4. 사용 패턴이 반복되면 향후 요청될 가능성이 높은 모델을 요청 전에 미리 적재해둔다(predictive pre-loading).
5. (선택) 모델이 OCI 이미지(Modelcars)로 패키징된 경우, `oci://` 참조를 통해 modelcar 컨테이너가 이미지를 pull하고 심볼릭 링크로 서빙 컨테이너와 모델 데이터를 공유해, 반복 다운로드 없이 컨테이너 이미지 캐시를 재사용한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| 다수 모델·빈번한 변경 환경에 적합하다 | "high-scale, high-density model serving for scenarios with frequent model changes and large numbers of models" |
| 메모리 자원을 자동으로 회수·재배분한다 | Model Caching + LRU Eviction 정책으로 자주 쓰는 모델은 유지, 안 쓰는 모델은 자동 제거 |
| 자원 활용을 최적화하는 배치를 제공한다 | Resource Sharing(다중 모델이 동일 런타임 파드 공유) + Efficient Packing(가용 자원 전반에 대한 최적 배치) |
| OCI 이미지 기반 배포가 시작 지연·중복 저장을 줄인다 | "By avoiding repetitive downloads of large models, startup delays are significantly minimized." / "decreases the need for duplicated local storage" |

## 6. 한계 및 부족한 점
- 확인한 admin-guide 문서 범위 내에서는 고가용성(HA)·장애 복구·rolling update 관련 명시적 설명은 확인되지 않는다.
- 확인한 문서에는 정량적 성능 수치(지연 시간, 처리량, 실제 스케일 벤치마크 등)가 포함되어 있지 않다.
- OCI/Modelcars 방식은 모델을 컨테이너 이미지로 빌드·push하는 별도 준비 단계(Dockerfile 작성, 레지스트리 관리)를 요구하며, 이미지 태그를 `latest`로 두면 `IfNotPresent` 캐시 재사용이 보장되지 않는다는 제약이 문서에 명시되어 있다.

## 7. 원문 기반 핵심 문장
> "ModelMesh installation provides high-scale, high-density model serving for scenarios with frequent model changes and large numbers of models, making it particularly well-suited for predictive inference workloads."
