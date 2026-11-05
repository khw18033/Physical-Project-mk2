# 새 하드웨어 확장 가이드

새 카메라·센서·가속기·로봇/액추에이터를 이 프레임워크에 추가할 때 밟는 절차다.
관련 요구사항: AI-B-04(실행 노드 자원 등록·배치), AI-B-09(신규 확장 등록·호환성 검증),
AI-C-04(외부 기술·제공자 어댑터), AI-C-10(기능·자원 등록·탐색), AI-C-18(구성요소 Capability
선언 규약). 원칙은 하나다 — **`perception/`, `risk/`, `execution/`, `selection/` 등 핵심 코드는
단 한 줄도 고치지 않는다.** 새 하드웨어는 항상 provider 구현 + 태그 선언 + registry 등록으로
끝나야 한다.

## 0. 먼저 정할 것 — 어떤 Protocol을 구현하는가

`mission_runtime/providers/adapters.py`가 경계다. 하드웨어 종류별로 구현할 Protocol이
정해져 있다(전부 `@runtime_checkable`이라 상속 없이 `isinstance()` 검사만으로 적합성을
확인할 수 있다).

| 새 하드웨어 종류 | 구현할 Protocol | 핵심 메서드 |
|---|---|---|
| 카메라·영상 입력 | `MediaSourceProvider` | `read_frame()`, `is_available()`, `source_id()` |
| 연산/가속기(GPU·NPU·OpenCL 등) | `AIRuntimeProvider` | `infer(capability_kind, inputs)`, `is_available()` |
| 로봇·액추에이터(물리 명령 실행) | `HardwareCommandProvider` | `execute(command)`, `cancel(command_id)`, `capabilities()` |
| 통신 채널(MQTT/Kafka 외 다른 것) | `TransportProvider` | `publish()`, `subscribe()`, `is_connected()` |
| 모델 배포 채널 | `ModelDeploymentProvider` | `download()`, `validate()`, `activate()`, `rollback()` |
| 관측 채널 | `ObservabilityProvider` | `record_metric()`, `record_event()` |
| 네트워크 오버레이 | `NetworkOverlayProvider` | `is_connected()`, `can_reach()`, `peers()` |
| 기능 프로세스 제어(시작/중지/재시작) | `ControlProvider` | `request()`, `get_status()` |

## 1. Protocol 구현

새 클래스가 해당 Protocol의 메서드 시그니처를 그대로 만족하면 된다. 예시(연산 provider,
`mission_runtime/providers/compute.py:119-167`):

```python
class CpuImageRuntimeProvider:
    capability_kinds = ("image.smooth",)
    provider_id = "cpu-image-runtime"

    def infer(self, capability_kind: str, inputs: Any) -> Any: ...
    def is_available(self) -> bool: ...
```

상속이 필요 없다 — `isinstance(CpuImageRuntimeProvider(), AIRuntimeProvider)`로 적합성을
검사한다(`tests/test_compute_providers.py:53-63` 참고). **로봇/액추에이터**는 별도로
`execution/hardware_adapter.py::HardwareAdapterHandler`가 `HardwareCommandProvider`를
주입받아 `CommandExecutionSupervisor`(AI-C-20 물리 명령 계약)와 연결하는 경계 역할을 한다 —
새 로봇 SDK는 이 provider 하나만 구현하면 되고 명령 lifecycle·idempotency 코드는 그대로
재사용된다.

## 2. 태그로 자신을 선언 — 벤더명이 아니라 자유 문자열

`contracts/profile.py::CompatibilityProfile`이 "이 provider가 언제 쓰일 수 있는가"를
표현한다.

```python
@dataclass(frozen=True)
class CompatibilityProfile:
    required_hw_tags: tuple[str, ...] = ()      # 없으면 후보에서 완전히 제외
    preferred_hw_tags: tuple[str, ...] = ()     # 없어도 배제하지 않음, 순위만 낮아짐
    required_runtime_tags: tuple[str, ...] = ()
    cost: ResourceCost = ResourceCost()          # compute_units, memory_mb, max_latency_ms
    priority: int = 100                          # 낮을수록 먼저 시도·오래 유지
```

태그는 `"compute.opencl"`, `"media.hw_decode"`, `"onboard_camera"` 같은 문자열일 뿐 벤더
enum이 아니다(`compute.py:24-27`). `compute.py::discover_node_tags()`처럼 런타임에 하드웨어를
탐지해 존재하는 태그만 반환하는 함수를 만들면 되고, 탐지 실패는 에러가 아니라 그냥 그 태그가
없는 것으로 처리한다.

`required_*`는 하드 필터(없으면 selector가 아예 고려하지 않음), `preferred_*`는 소프트
가산점(있으면 우선순위가 오르지만 없어도 후보에서 빠지지 않음)이라는 구분을 반드시 지킨다 —
필수와 선호를 섞으면 AI-C-05(핵심·선택 기능 격리)가 깨진다.

## 3. Registry에 등록

```python
from mission_runtime.registry.capability_registry import ProviderRegistration
from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.contracts.profile import CompatibilityProfile, ResourceCost

registry.register_local(ProviderRegistration(
    capability_kind="image.smooth",          # 이 provider가 제공하는 기능 종류
    provider_id="my-new-camera-runtime",
    version="1",
    compatibility=CompatibilityProfile(
        required_hw_tags=("my_new_accelerator",),
        priority=10,
        cost=ResourceCost(compute_units=2),
    ),
    requirement=CapabilityRequirement(),      # 이 provider 자신이 의존하는 다른 capability
))
```

### 선언은 **적은 만큼만** 선언이다 (AI-C-18)

위 등록에 `declaration=` 을 함께 주면 그 구성요소가 자기 성질을 말할 수 있다. 적지
않은 칸은 **기본값이 아니라 미선언**이고, 그 둘을 섞지 않는 것이 이 계약의 요점이다.

```python
from mission_runtime.contracts.capability_contract import Capability, DeclarationBasis

declaration = Capability(
    kind="image.smooth",
    input_schema="schema://frame/1", output_schema="schema://frame/1",
    preconditions=("media.video_input",),      # 없으면 DISABLED
    optional_preconditions=("accel.npu",),     # 없으면 DEGRADED 까지만
    cancellable=True,                          # True / False / 적지 않으면 None(모름)
    idempotent=True,                           # 같은 입력을 다시 넣어도 같은 결과인가
    invocation="synchronous",                  # synchronous / asynchronous
    basis=DeclarationBasis(units={"blur_sigma_px": "px"},
                           reference_frame="image", time_basis="backend_ntp"),
    scope_tags=(),                             # () = "범위 제약 없음" 선언 / None = 미선언
)
```

**모르는 것은 적지 않는다.** `cancellable=False` 는 "취소할 수 없다"는 **선언**이고
생략은 "아무도 말하지 않았다"다 — 두 값이 다르다. 생략을 `False` 로 메우면 상위
기능이 당신의 장치를 "취소를 거부하는 장치"로 읽고 취소를 **보내 보지도 않는다**.
무엇을 적지 않았는지는 `declaration.undeclared_items()` 로 나오고, 선택하는 쪽은
`registry.providers_declaring(kind, "cancellable")` 로 "그렇다고 선언한 것"과 "아무도
선언하지 않은 것"을 **따로** 받는다. 품질·지연·자원 실측값은 이 선언에 적지 않는다 —
그 숫자의 주인은 `ExecutionProfile`(AI-B-01)이고 여기 베끼면 둘이 갈린다.

`registry/capability_registry.py`는 `_local`(항상 authoritative)과 `_remote`(중앙 레지스트리
마지막 스냅샷)를 분리 관리한다 — 중앙이 끊겨도 로컬 등록은 그대로 유효하다(AI-C-10).

## 4. 배치 프로파일에 노드 태그 반영

`simulator/scenarios/domain-*.json`의 `profile.node_tags`가 "이 물리 노드가 실제로 무엇을
갖고 있는가"를 선언하는 곳이다(과거 `profiles/*.json` 디렉터리 대체). 예:
`domain-robot.json`의 `profile.node_tags`:

```json
{
  "domain_id": "robot_autonomy_support",
  "node_tags": ["cpu", "mobile", "onboard_camera"]
}
```

새 하드웨어가 실제로 붙은 노드라면 이 배열에 태그 하나를 추가하는 것으로 끝난다 — 로더
(`contracts/profile_loader.py`)가 알 수 없는 최상위 키는 예외를 던지므로 오타는 조용히
무시되지 않는다.

## 5. Selector가 자동으로 골라간다 — 호출부는 안 바뀐다

```python
selector.select("image.smooth", node_tags={"cpu"}, budget=budget)          # 기존 CPU provider
selector.select("image.smooth", node_tags={"cpu", "my_new_accelerator"}, budget=budget)  # 새 provider
```

두 호출은 코드가 완전히 동일하다 — 노드 태그 한 줄만 다르다. `CapabilitySelector.select()`는
`(priority, preference_penalty, cost.compute_units)` 순으로 정렬해 최소값을 고르고, 호환
후보가 없으면 예외 대신 `SelectionResult(provider=None, reason=...)`을 반환한다(`selection/selector.py`).
이게 새 하드웨어를 추가해도 상위 인지·판단 코드가 바뀌지 않는 이유다.

## 6. (선택) 새 데이터 필드가 필요하면 사전에 등록

새 하드웨어가 기존에 없던 종류의 값(예: 새 센서 판독값)을 만들어낸다면 `contracts/data_dictionary.py`의
`_ENTRIES`에 `FieldSpec` 하나를 추가한다 — 여기서 정하는 건 이름의 의미이지 전송 형식이 아니다
(AI-C-01). producer/consumer 코드가 각자 필드명을 임의로 짓지 않게 하는 유일한 장치다.

## 7. 검증 — 등록 전에 반드시 돌려볼 것

```python
from mission_runtime.execution.conformance import check_provider_conformance

report = check_provider_conformance(my_registration, registry)
assert report.passed, report.failures
```

`conformance.py`가 확인하는 건 모델 정확도가 아니라 **격리**다: 이 provider를 등록·해제해도
다른 capability_kind의 후보 수가 그대로인지(AI-B-09, AI-C-11 계열 원칙). 여기에 더해
`tests/test_compute_providers.py`의 벤더명 정적 검사(`test_no_vendor_name_appears_in_executable_package_source`,
L76-95)를 그대로 재사용하면 새 provider 코드에 `nvidia`/`cuda`/특정 SDK 이름이 실수로
섞여 들어가는 것도 잡는다.

## 8. 참고할 기존 예시와 테스트 템플릿

| 무엇을 추가하는가 | 참고 코드 | 참고 테스트 |
|---|---|---|
| 연산/가속기 provider | `providers/compute.py` (CPU/OpenCL 두 구현이 같은 capability_kind를 다른 우선순위로 등록) | `tests/test_compute_providers.py` |
| 카메라/미디어 provider | `providers/fakes.py::SyntheticMediaSourceProvider` | `tests/test_provider_fakes.py` |
| 로봇/액추에이터 provider | `execution/hardware_adapter.py::HardwareAdapterHandler` | `tests/test_physical_command_contract.py`, `tests/test_external_contract_application.py` |
| selector 등록·태그 기본 패턴 | — | `tests/test_selector.py`(`reg_of()` 헬퍼가 가장 단순한 골격) |

## 요약 절차

```text
1. adapters.py의 Protocol 중 하나를 구현한다 (상속 불필요, 시그니처만 맞추면 됨)
2. CompatibilityProfile로 required/preferred 태그·cost·priority를 선언한다
3. registry.register_local(ProviderRegistration(...))로 등록한다
4. 실제 노드라면 simulator/scenarios/domain-*.json의 profile.node_tags에 태그를 추가한다
5. (필요시) data_dictionary.py에 새 필드 이름을 등록한다
6. check_provider_conformance()로 격리 검증 + 벤더명 정적 검사 테스트를 돌린다
7. selector.select(...)를 그대로 호출한다 — 호출부는 이미 완성되어 있다
```

이 7단계를 벗어나 `perception/`·`risk/`·`execution/control.py` 같은 핵심 모듈에 조건문을
추가해야 한다면, 그건 하드웨어 확장이 아니라 요구사항 누락이다 — 먼저
각 모듈 docstring 의 `implements:` 에서 대응하는 ID를 찾고(`grep -rn 'implements: AI-' .`), 없으면
CLAUDE.md 원칙대로 "추가 요구사항 필요"로 보고한다.

## 배경 그림 놓기 — 캠퍼스 조감도와 층 도면

지도는 기본적으로 **선언된 좌표만으로** 그려진다. 배경 그림은 선택 계층이고, 없어도
구역·로봇·경로는 그대로 보인다(AI-C-05). 그림을 깔면 같은 좌표가 실제 건물 위에
놓인다.

놓는 순서는 셋이다.

1. **그림 파일을 공개 트리 밖에 둔다.** 자리는 `$MISSION_RUNTIME_ASSETS`(기본 `../local/`)
   아래이고, 저장소에는 **참조만** 들어간다. 남의 지도를 캡처한 그림이 저장소에 실려
   나가지 않게 하려는 것이다.

   ```text
   $MISSION_RUNTIME_ASSETS/maps/hanbat-campus.png
   $MISSION_RUNTIME_ASSETS/maps/n4-1f.png
   ```

2. **`config/map_tiles.example.json` 에 한 줄을 더한다.** 코드는 고치지 않는다.

   ```json
   {
     "layer_id": "college-n4-1f",
     "kind": "static_image",
     "requires_external_connection": false,
     "enabled": true,
     "scope": {"domain_id": "college", "level_id": "n4-1f"},
     "image": {"ref": "maps/n4-1f.png", "width_px": 1038, "height_px": 536},
     "anchors": [
       {"pixel": {"x": 120, "y":  60}, "local": {"x":  0.0, "y":  0.0}},
       {"pixel": {"x": 980, "y": 500}, "local": {"x": 60.0, "y": 30.0}}
     ],
     "source": {"name": "…", "license": "…", "redistributable": false}
   }
   ```

   **앵커 두 점**이 전부다. 그림 위에서 자리를 아는 점 둘을 골라 그 픽셀과 현장 로컬
   좌표를 적으면, 축척과 원점은 거기서 역산된다. 두 점이 같은 가로줄이나 세로줄 위에
   있으면 그 축의 축척이 나오지 않으므로 **선언을 읽을 때 거절한다** — 현장에서 발견할
   잘못이 아니다.

   `source.name` 과 `source.license` 는 **비워 둘 수 없다.** 모르면 `"unknown"` 이라고
   적는다. 캡처한 지도에는 이용 약관이 따라붙고, 그 사실이 선언에 없으면 조용히 함께
   배포된다.

3. **층 그림이 있으면 그것이 이긴다.** 같은 도메인에 조감도와 층 도면이 둘 다 선언돼
   있으면 층을 보고 있을 때는 층 도면이 깔린다. 조감도를 층 화면에 깔면 로봇이 건물
   지붕 위에 선다.

확인할 자리는 둘이다. 선언과 변환 계수는 `GET /api/background?domain=…&level=…`,
그림 바이트는 `GET /api/media?kind=map&file=<layer_id>`. 그림이 아직 없는 노드에서는
`available: false` 와 `image_missing` 이 나가고 화면은 좌표 도면으로 돌아간다.

픽셀 크기와 그림 참조가 `/api/scene`·`/api/domain`·`/api/zone` 에 **섞이지 않는** 것이
이 설계의 요점이다 — 상태 계약에는 색도 픽셀도 들어가지 않는다(AI-C-08). 그래서 배경은
자기 경로로만 나가고, `tests/test_view_contract.py` 가 그 경계를 지킨다.
