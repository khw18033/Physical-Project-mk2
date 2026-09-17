# Kubernetes RBAC

## 메타데이터
- categories: Role/ClusterRole, RoleBinding/ClusterRoleBinding, Additive-only 권한 모델, API Authorization
- domain: [[관측·보안]]
- source: Kubernetes 프로젝트. "Using RBAC Authorization." Kubernetes Documentation, 확인 시점 2026-09.
- url: https://kubernetes.io/docs/reference/access-authn-authz/rbac/
- year: 확인 필요 (지속 갱신 문서)
- authors: Kubernetes 프로젝트
- venue: Kubernetes Documentation

## 1. 핵심 요약
- RBAC은 "a method of regulating access to computer or network resources based on the roles of individual users within your organization"로 정의된다.
- Role/ClusterRole은 permission 집합을 나타내며 "Permissions are purely additive (there are no "deny" rules)."라는 원칙이 명시된다.
- Role은 namespace 범위, ClusterRole은 비-namespace(클러스터 전역) 범위로 구분된다.
- RoleBinding은 namespace 범위, ClusterRoleBinding은 클러스터 전역 범위로 권한을 subject(user/group/service account)에 부여한다.

## 2. 문서 목적
- 해결하려는 문제: 클러스터의 여러 사용자·서비스 계정이 필요 이상의 API 권한을 갖는 것을 방지해야 하는 문제.
- 기술적 목표: 역할(permission 집합)과 역할 부여(binding)를 분리해 namespace/cluster 범위별로 세밀하게 API 접근을 통제하는 것.
- 다루는 범위: Role/ClusterRole/RoleBinding/ClusterRoleBinding 오브젝트 구조, RBAC 활성화 방법(`--authorization-mode=RBAC` 또는 `AuthorizationConfiguration`의 `type: RBAC`), Role 규칙 구성(`apiGroups`/`resources`/`verbs`), 권한 상승 방지 관련 안내.

## 3. 핵심 개념 상세
### RBAC (역할 기반 접근 제어)
- 원문 표현: "Role-based access control (RBAC) is a method of regulating access to computer or network resources based on the roles of individual users within your organization."
- 정의: 개별 주체가 아니라 역할(role) 단위로 권한을 정의하고 부여하는 접근 제어 방식.
- 역할: 서로 다른 성격의 워크로드(예: 하드웨어 제어 어댑터, 추론 파드, 모델 관리 컴포넌트, 배포 컨트롤러)에 동일한 광범위 권한(예: `cluster-admin`)을 주지 않고 각자 필요한 최소 권한만 부여하고 싶을 때 쓰인다. 컨테이너·워크로드 수준의 접근 통제를 담당하는 핵심 메커니즘이다.

### Role과 ClusterRole
- 원문 표현: "An RBAC _Role_ or _ClusterRole_ contains rules that represent a set of permissions." / "A Role always sets permissions within a particular namespace" / "ClusterRole, by contrast, is a non-namespaced resource."
- 정의: Role은 특정 namespace 안에서만 유효한 permission 집합, ClusterRole은 namespace에 종속되지 않는 permission 집합.
- 역할: 서로 다른 성격의 컴포넌트(예: 벤더별 하드웨어 어댑터, 추론 파드, 배포 관리 컴포넌트)가 각기 다른 namespace의 다른 API 자원만 접근하도록 권한을 분리하는 근거가 된다. 이는 워크로드 배치 조건(필수/선호 자원 조건)과는 별개 축인 "권한 범위 구분" 문제를 다룬다.

### RoleBinding과 ClusterRoleBinding
- 원문 표현: "A role binding grants the permissions defined in a role to a user or set of users. It holds a list of _subjects_ (users, groups, or service accounts), and a reference to the role being granted. A RoleBinding grants permissions within a specific namespace whereas a ClusterRoleBinding grants that access cluster-wide."
- 정의: Role/ClusterRole이 정의한 permission을 실제 subject(사용자, 그룹, ServiceAccount)에 연결하는 오브젝트.
- 역할: 각 컴포넌트의 ServiceAccount에 실제로 필요한 최소 권한만 RoleBinding으로 연결하는 것이 최소 권한(least privilege) 원칙을 적용하는 실질적인 지점이다(문서 자체는 이 용어를 직접 쓰지 않지만, permission의 additive-only 특성이 이를 뒷받침한다).

## 4. 구조 및 흐름
1. `rbac.authorization.k8s.io` API 그룹과 `--authorization-mode=RBAC`(또는 `AuthorizationConfiguration`의 `type: RBAC`) 설정으로 RBAC 인가 모드를 활성화한다.
2. namespace 범위 permission이 필요하면 Role을, 클러스터 전역이 필요하면 ClusterRole을 정의한다 — 각 규칙은 `apiGroups`/`resources`/`verbs`로 구성된다.
3. Role/ClusterRole을 실제 subject(User/Group/ServiceAccount)에 연결하기 위해 RoleBinding(namespace 범위) 또는 ClusterRoleBinding(클러스터 전역)을 생성한다.
4. permission은 순수 additive이므로("no deny rules"), 여러 Role/Binding이 겹치면 합집합으로 권한이 확장된다 — 따라서 최소 권한 설계는 필요한 Role만 만들고 불필요한 바인딩을 피하는 방식으로 이뤄져야 한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| RBAC 권한은 역할 단위로 정의되고 subject에 별도로 바인딩된다 | Role/ClusterRole("permission 집합") vs RoleBinding/ClusterRoleBinding("권한을 subject에 부여") 구조가 명시적으로 분리됨 |
| namespace 범위와 클러스터 전역 범위가 명확히 구분된다 | "A Role always sets permissions within a particular namespace" vs "ClusterRole ... is a non-namespaced resource"; RoleBinding(namespace) vs ClusterRoleBinding(cluster-wide) |
| RBAC 권한 모델에는 거부(deny) 규칙이 없다 | "Permissions are purely additive (there are no "deny" rules)." |

## 6. 한계 및 부족한 점
- 공식 문서가 명시하는 한계: "Permissions are purely additive (there are no "deny" rules)."라는 구조적 제약으로 인해, 특정 권한을 명시적으로 차단하는 설계는 RBAC만으로 불가능하며 애초에 권한을 부여하지 않는 방식으로만 통제해야 한다. 또한 "If you are making changes to a cluster as you learn, see privilege escalation prevention and bootstrapping to understand how those restrictions can prevent you making some changes"라는 주의 문구가 있어, RBAC 자체가 관리자의 권한 설정 작업을 제약할 수 있음을 경고한다.
- 일반적인 주의점: RBAC은 "Pod가 어떤 Kubernetes API/device를 쓸 수 있는가"만 통제하는 워크로드 계층 메커니즘이다. 메시징 계층(누가 특정 토픽을 publish/consume할 수 있는가)이나 애플리케이션 수준의 실행 권한(누가 특정 물리 장치에 명령을 낼 수 있는가)은 RBAC이 다루는 범위가 아니다. 즉 Kubernetes API 접근 권한과 애플리케이션 수준의 명령 발행 권한은 별개의 인가 체계이며, RBAC을 적용했다고 해서 메시징 토픽 권한이 자동으로 통제되는 것은 아니다.

## 7. 원문 기반 핵심 문장
> "Role-based access control (RBAC) is a method of regulating access to computer or network resources based on the roles of individual users within your organization."
