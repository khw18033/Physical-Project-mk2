# Helm

## 메타데이터
- categories: Helm Chart, Release/Revision 관리, helm rollback
- domain: [[배포·오케스트레이션]]
- source: Helm 프로젝트. "Helm Docs" / "Charts" / "helm rollback." Helm Documentation, 확인 시점 2026-09.
- url: https://helm.sh/docs/
- year: 확인 필요 (지속 갱신 문서라 발행년도 특정 불가; 확인된 버전 계열은 Helm 4.2.4(current)/3.21.4/2.17.0(legacy))
- authors: Helm 프로젝트
- venue: Helm Documentation

## 1. 핵심 요약
- Helm은 "the package manager for Kubernetes"로 스스로를 정의한다.
- Chart는 "a collection of files that describe a related set of Kubernetes resources"로 정의되며, `Chart.yaml`(필수 메타데이터, Semantic Versioning 2.0을 따르는 `version` 필드 포함), `values.yaml`, `templates/` 등으로 구성된다.
- 문서에 병기된 버전 계열은 Helm 4.2.4(current), 3.21.4, 2.17.0(legacy) 세 갈래다.
- `helm rollback`은 "roll back a release to a previous revision"으로 정의되며, `helm rollback <RELEASE> [REVISION]` 형식으로 release 이름과 revision 번호(생략 시 직전 revision)를 인자로 받는다.

## 2. 문서 목적
- 해결하려는 문제: 여러 Kubernetes manifest로 구성된 애플리케이션을 개별 리소스 단위가 아니라 하나의 버전화된 단위로 설치·업그레이드·롤백해야 하는 문제.
- 기술적 목표: Chart(패키징 형식)와 release(배포 인스턴스, revision 단위 이력)라는 두 개념으로 관련 Kubernetes 리소스 집합을 버전 관리하는 것.
- 다루는 범위: Chart 구조(`Chart.yaml`/`values.yaml`/`templates/` 등), release 생명주기(install/upgrade/rollback), `helm rollback`의 인자·플래그(`--cleanup-on-fail`, `--dry-run`, `--wait`, `--timeout` 등).

## 3. 핵심 개념 상세
### Helm (Kubernetes 패키지 매니저)
- 원문 표현: "the package manager for Kubernetes"
- 정의: Kubernetes 리소스 집합을 패키징·버전관리·배포하는 도구.
- 역할: 여러 개의 개별 Kubernetes manifest를 리소스 단위가 아니라 하나의 버전화된 배포 단위로 다루고 싶을 때 쓰인다. 오케스트레이터(K3s 등) 위에서 선택적으로 사용하는 패키징·배포 도구이며, 애플리케이션의 핵심 로직이 Helm CLI/API에 직접 의존할 필요는 없다.

### Chart
- 원문 표현: "A chart is a collection of files that describe a related set of Kubernetes resources."
- 정의: `Chart.yaml`(필수 메타데이터, Semantic Versioning 2.0의 `version` 필드 포함), `values.yaml`(기본 설정값), `templates/`(매니페스트 템플릿) 등으로 구성된 디렉터리 패키지.
- 역할: 컨테이너 워크로드와 그 설정을 하나의 버전 단위로 배포·관리하고 싶을 때 쓰는 패키징 형식의 후보다. 다만 Chart 버전은 어디까지나 컨테이너·설정의 버전일 뿐이며, 물리 장치나 로봇 동작 자체의 버전을 의미하지는 않는다.

### Release와 helm rollback
- 원문 표현: "This command rolls back a release to a previous revision." / "The first argument of the rollback command is the name of a release, and the second is a revision (version) number. If this argument is omitted or set to 0, it will roll back to the previous release."
- 정의: Chart를 클러스터에 설치한 하나의 인스턴스가 release이며, 각 install/upgrade는 새 revision을 남긴다(`helm history RELEASE`로 조회 가능). `helm rollback <RELEASE> [REVISION]`은 release를 과거 revision 상태로 되돌린다.
- 역할: 배포 실패나 설정 오류가 발생했을 때 이전에 검증된 상태로 되돌리는 표준적인 방법을 제공한다. 다만 helm rollback이 되돌리는 대상은 클러스터에 배포된 워크로드의 설정·이미지 버전이며, 로봇이나 물리 장치가 이미 수행한 이동·회전·파지 같은 동작이나 그 결과 상태를 되돌리는 기능은 아니다.

## 4. 구조 및 흐름
1. 개발자가 `Chart.yaml`, `values.yaml`, `templates/`를 포함하는 Chart 디렉터리를 작성한다.
2. `helm install`로 Chart를 클러스터에 설치하면 release가 생성되고 revision 1이 기록된다.
3. `helm upgrade`로 값을 변경해 재배포하면 새 revision이 누적된다.
4. 문제가 발생하면 `helm rollback <RELEASE> [REVISION]`으로 특정 revision(생략 시 직전 revision)으로 되돌린다. `--cleanup-on-fail`(롤백 실패 시 새로 생성된 리소스 삭제), `--dry-run`(시뮬레이션), `--wait`/`--wait-for-jobs`(리소스 준비 대기), `--timeout`(기본 5m0s) 등의 플래그로 동작을 제어한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Helm은 Kubernetes 리소스 집합을 하나의 패키지로 다룬다 | Chart = "a collection of files that describe a related set of Kubernetes resources" |
| release는 revision 단위로 이력 관리되어 특정 시점으로 되돌릴 수 있다 | `helm rollback`은 release 이름 + revision 번호를 인자로 받아 과거 상태로 되돌리며, 미지정 시 직전 revision으로 롤백 |
| 롤백은 즉시 완료를 보장하지 않아 대기·검증 옵션이 필요하다 | `--wait`, `--timeout`(기본 5m0s), `--wait-for-jobs` 플래그가 리소스 준비 완료까지 대기하는 기능을 제공 |

## 6. 한계 및 부족한 점
- 공식 문서 자체가 명시하는 한계: 이번에 확인한 페이지 범위에서는 Helm 자체의 한계나 트레이드오프에 대한 명시적 서술을 확인하지 못했다(확인 필요, 추가 페이지 조사가 필요하다).
- 일반적으로 중요한 구분점: `helm rollback`이 되돌리는 대상은 Kubernetes 워크로드의 컨테이너 이미지·설정(release revision)이며, 로봇이나 물리 장치가 이미 수행한 이동·회전·파지 같은 동작이나 그 실행 결과 상태를 되돌리는 수단이 아니다. 물리 시스템을 제어하는 애플리케이션이라면, 물리 명령의 취소·안전 정지는 Helm rollback과는 완전히 별개의 계약으로 설계해야 한다.
- Chart의 Semantic Versioning과 애플리케이션이 별도로 정의하는 "실행 이미지 버전/설정 버전" 개념이 겉보기엔 겹쳐 보여도 동일한 계약은 아니므로, Helm chart version을 그대로 애플리케이션의 버전 계약으로 대체해서는 안 된다.

## 7. 원문 기반 핵심 문장
> "This command rolls back a release to a previous revision. The first argument of the rollback command is the name of a release, and the second is a revision (version) number. If this argument is omitted or set to 0, it will roll back to the previous release."
