"""배치 결정(무엇이 이 장치 안에 있어야 하는가) → 실제 배포(그것을 거기 둔다).

implements: AI-B-05, AI-B-02, AI-B-03, AI-B-04, AI-B-11, AI-C-04, AI-C-05, AI-C-10, AI-C-15

이 모듈은 이미 있는 두 반쪽을 잇는 연결부일 뿐 제3의 기구가 아니다.

    목적 데이터            runtime/residency.py          이 모듈           provider
    device_purposes.json → decide_residency()      →  unit 소스 생성   →  DeviceChannel
                           ZoneApplication.resolve() →  PlacementReconciler →  control.request()

세 가지를 일부러 **만들지 않았다**.

1. **두 번째 축소 기구를 만들지 않는다.** 어떤 kind가 이 장치에서 실제로 돌 수
   있는지는 여전히 `ZoneApplication.resolve()`가 판정하고, 여기서는 그 결과를
   소비만 한다. 예산 초과·태그 결손·선택 의존 결손은 전부 기존 경로의 말이다
   (AI-C-05는 하나뿐이어야 한다).
2. **두 번째 배치 조정기를 만들지 않는다.** start/stop 차분은
   `runtime/placement.py::PlacementReconciler`가 그대로 한다. 덕분에 "링크가
   좋아져서 인지가 엣지로 갔다"가 *이 kind의 unit을 stop* 이라는 정확히 한 번의
   제어 호출로 나오고, 감사·이벤트 기록도 기존 `/api/placement`의 것과 같은
   모양으로 남는다(AI-B-03: 업무 책임 추적과 기술 추적의 분리도 그대로).
3. **전송 기술을 알지 않는다.** 이 파일에는 ssh·scp·tar라는 단어가 없다.
   `providers/device_control.py::DeviceChannel`이 주는 `pack_unit`과
   `ControlProvider`만 쓰므로 말단 제어를 다른 경로로 바꿔도 여기는 그대로다
   (AI-C-04).

**배포 단위는 capability kind 하나**다. AI-B-05가 요구하는 "각 기능을 독립 실행
단위로 배포·기동·중지·업데이트·상태 확인·복구"를 그대로 옮긴 것이고, 그래야 한
기능의 실패가 같은 장치의 다른 기능을 끌고 내려가지 않는다(AI-C-05). unit id는
그 kind를 실제로 맡은 provider_id다 — provider가 바뀌면(예: Coral이 빠져
rpn-edgetpu → rpn-ondevice) 낡은 unit을 멈추고 새 unit을 올리는 것이 맞는 동작이며,
`PlacementReconciler`의 차분이 이미 그렇게 움직인다.

**같은 코드, 다른 설정.** 모든 unit은 같은 소스(`deploy/ondevice_unit`)에서
나오고 `unit.config.json`만 다르다. 그 config는 목적 프로파일에서 온 선언
그대로다 — kind, core 여부, 단절 시 동작, 배치 사유. 그래서 "드론에 배포된
기능 집합과 고정 카메라에 배포된 기능 집합이 다른" 이유가 코드 분기가 아니라
데이터 차이라는 것이 아티팩트의 sha256 수준에서 확인된다(AI-B-02: 버전과
식별 가능한 무결성 정보).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mission_runtime.contracts.profile import DevicePurposeProfile
from mission_runtime.providers.device_control import ARTIFACT_PARAM, DeviceChannel
from mission_runtime.runtime.placement import PlacementAction, PlacementReconciler
from mission_runtime.runtime.residency import ResidencyPlan

#: 저장소가 들고 있는 기준 unit 소스. 배포 프로파일이 다른 것을 줄 수 있다.
DEFAULT_UNIT_SOURCE = Path(__file__).resolve().parents[1] / "deploy" / "ondevice_unit"

#: unit 소스에서 config 파일의 이름. unit.py가 자기 옆에서 읽는다.
UNIT_CONFIG_NAME = "unit.config.json"

REASON_NO_PROVIDER = "no_provider_for_ondevice_kind"
REASON_PACK_UNAVAILABLE = "channel_cannot_pack_units"
REASON_UNIT_SOURCE_MISSING = "unit_source_missing"


@dataclass(frozen=True)
class UnitPlan:
    """이 장치에 놓일 실행 단위 하나."""

    unit_id: str
    kind: str
    provider_id: str
    #: 이 unit의 `unit.config.json` 내용. 전부 선언에서 온 값이며 판정이 없다.
    config: dict
    #: 왜 이 kind가 이 장치에 있는가. 계획에만 남고 아티팩트에는 들어가지
    #: 않는다(위 `unit_config_for` 참고).
    residency_reason: str | None = None
    source_dir: Path | None = None
    artifact_version: str | None = None
    artifact_sha256: str | None = None

    def as_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "provider_id": self.provider_id,
            "residency_reason": self.residency_reason,
            "artifact_version": self.artifact_version,
            "artifact_sha256": self.artifact_sha256,
            "config": self.config,
        }


@dataclass(frozen=True)
class SkippedKind:
    """온디바이스로 결정됐지만 지금 이 장치에서 올릴 수 없는 kind.

    실패가 아니라 **축소 운용의 정상 결과**다(AI-C-05). 사유는 기존
    `CapabilityResolution.reason`을 그대로 옮기므로 화면에서 쓰던 통제 어휘가
    여기서도 같은 뜻으로 읽힌다.
    """

    kind: str
    reason: str


@dataclass(frozen=True)
class DeviceUnitPlan:
    """한 장치에 대한 배포 계획 전체."""

    device_id: str
    purpose_id: str
    units: tuple[UnitPlan, ...] = ()
    skipped: tuple[SkippedKind, ...] = ()
    edge_kinds: tuple[str, ...] = ()

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(u.kind for u in self.units)

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "purpose_id": self.purpose_id,
            "units": [u.as_dict() for u in self.units],
            "skipped": [{"kind": s.kind, "reason": s.reason} for s in self.skipped],
            "edge_kinds": list(self.edge_kinds),
        }


def unit_config_for(
    purpose: DevicePurposeProfile,
    plan: ResidencyPlan,
    kind: str,
    provider_id: str,
    base_config: Mapping[str, Any] | None = None,
) -> dict:
    """한 unit이 들고 갈 설정 — 전부 선언에서 옮겨 적은 값이다.

    여기에 판정이 들어가면 장치 안에 두 번째 판단 주체가 생긴다. unit은 자기가
    무엇을 맡았고 단절되면 어떻게 하기로 선언돼 있는지를 **읽을 뿐**이고,
    그 선언을 만든 것은 `decide_residency`다.

    배치 **사유**(`decision.reason`)는 일부러 여기 넣지 않는다. 사유에는 그때의
    링크 자세가 문자열로 박혀 있어서(`link_posture_requires_local:reducing` vs
    `...:local_only`) config에 넣으면 기능이 하나도 달라지지 않았는데 링크
    표현이 바뀌었다는 이유만으로 아티팩트 sha256이 바뀌고 재배포가 나간다.
    실제로 그렇게 만들어 보고 확인한 churn이다. 사유는 `UnitPlan.residency_reason`
    으로 계획에만 남기고 아티팩트 정체성에서는 뺀다 — AI-B-02의 "버전 = 코드 +
    구성"에서 구성은 *기능을 바꾸는* 구성이어야 한다.
    """
    decision = plan.decision_for(kind)
    spec = purpose.spec(kind)
    config = dict(base_config or {})
    config.update(
        {
            "unit_kind": kind,
            "provider_id": provider_id,
            "purpose_id": purpose.purpose_id,
            "residency": decision.placement.value if decision else None,
            "is_core": bool(spec and spec.is_core),
            "degrade_rank": spec.degrade_rank if spec else 0,
            "survives_outage": bool(decision and decision.survives_outage),
            "outage_behavior": decision.outage_behavior if decision else None,
            "quality_is_safety_affecting": bool(decision and decision.quality_is_safety_affecting),
        }
    )
    return config


def build_unit_source(
    base_dir: str | Path,
    dest_dir: str | Path,
    config: Mapping[str, Any],
) -> Path:
    """기준 unit 소스 + 이 unit의 config → 배포할 소스 디렉터리.

    config는 정렬해서 쓴다. `pack_unit_artifact`의 결정성(정렬·mtime 0)이
    의미를 가지려면 안에 들어가는 바이트도 결정적이어야 하고, 그래야 "같은
    선언은 같은 sha256"이 성립한다(AI-B-02).
    """
    base = Path(base_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"{REASON_UNIT_SOURCE_MISSING}:{base}")
    destination = Path(dest_dir)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(base, destination, symlinks=False)
    merged = dict(config)
    (destination / UNIT_CONFIG_NAME).write_text(
        json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def plan_device_units(
    device_id: str,
    purpose: DevicePurposeProfile,
    plan: ResidencyPlan,
    resolutions: Mapping[str, Any],
    *,
    unit_source: str | Path = DEFAULT_UNIT_SOURCE,
) -> DeviceUnitPlan:
    """배치 결정 + 해석 결과 → "이 장치에 무엇을 올릴 것인가".

    온디바이스로 결정된 kind만 후보이고, 그중 provider가 실제로 붙은 것만
    unit이 된다. provider가 붙지 않은 kind는 오류가 아니라 `skipped`이며
    사유가 그대로 남는다 — 선택 기능의 결손은 정상 축소다(AI-C-05).
    """
    base = Path(unit_source)
    base_config: dict = {}
    candidate = base / UNIT_CONFIG_NAME
    if candidate.is_file():
        try:
            base_config = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            base_config = {}

    units: list[UnitPlan] = []
    skipped: list[SkippedKind] = []
    for kind in plan.ondevice_kinds:
        resolution = resolutions.get(kind)
        provider = getattr(resolution, "provider", None) if resolution is not None else None
        if provider is None:
            reason = getattr(resolution, "reason", None) or REASON_NO_PROVIDER
            skipped.append(SkippedKind(kind, reason))
            continue
        provider_id = provider.provider_id
        units.append(
            UnitPlan(
                unit_id=provider_id,
                kind=kind,
                provider_id=provider_id,
                config=unit_config_for(purpose, plan, kind, provider_id, base_config),
                residency_reason=getattr(plan.decision_for(kind), "reason", None),
            )
        )
    return DeviceUnitPlan(
        device_id=device_id,
        purpose_id=purpose.purpose_id,
        units=tuple(units),
        skipped=tuple(skipped),
        edge_kinds=plan.edge_kinds,
    )


@dataclass
class DeviceDeployment:
    """한 장치의 배포 상태를 들고 있는 것. 판정은 하나도 하지 않는다.

    `PlacementReconciler`를 장치마다 하나씩 유지해 무엇이 이미 올라가 있는지를
    기억한다. 그래서 같은 계획을 두 번 적용하면 제어 호출이 0건이고(멱등),
    계획이 달라진 만큼만 start/stop이 나간다.
    """

    channel: DeviceChannel
    staging_dir: Path
    unit_source: Path = DEFAULT_UNIT_SOURCE
    observability: Any = None
    requested_by: str = "device_deployment"
    _reconciler: PlacementReconciler | None = field(default=None, init=False, repr=False)
    _units: dict[str, UnitPlan] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.staging_dir = Path(self.staging_dir)
        self.unit_source = Path(self.unit_source)

    @property
    def reconciler(self) -> PlacementReconciler:
        if self._reconciler is None:
            self._reconciler = PlacementReconciler(
                self.channel.control,
                observability=self.observability,
                requested_by=f"{self.requested_by}:{self.channel.device_id}",
            )
        return self._reconciler

    # --- 준비 ---------------------------------------------------------------
    def prepare(self, plan: DeviceUnitPlan) -> DeviceUnitPlan:
        """계획의 각 unit을 실제 아티팩트로 만들고 배포 가능으로 선언한다.

        패킹은 장치를 건드리지 않는다 — 여기서 실패하면 장치에는 아무 일도
        일어나지 않고, 이미 돌고 있는 unit은 그대로다(AI-B-05).
        """
        if self.channel.pack_unit is None:
            raise RuntimeError(REASON_PACK_UNAVAILABLE)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        prepared: list[UnitPlan] = []
        for unit in plan.units:
            source = build_unit_source(
                self.unit_source, self.staging_dir / "src" / unit.unit_id, unit.config
            )
            package = self.channel.pack_unit(source, self.staging_dir / "pkg")
            prepared.append(
                UnitPlan(
                    unit_id=unit.unit_id,
                    kind=unit.kind,
                    provider_id=unit.provider_id,
                    config=unit.config,
                    residency_reason=unit.residency_reason,
                    source_dir=source,
                    artifact_version=getattr(package, "version", None),
                    artifact_sha256=getattr(package, "sha256", None),
                )
            )
            self.reconciler.declare_deployable(unit.unit_id, {ARTIFACT_PARAM: package})
            self._units[unit.unit_id] = prepared[-1]
        from dataclasses import replace as _replace

        return _replace(plan, units=tuple(prepared))

    # --- 적용 ---------------------------------------------------------------
    def apply(
        self, plan: DeviceUnitPlan, resolutions: Mapping[str, Any]
    ) -> tuple[DeviceUnitPlan, tuple[PlacementAction, ...]]:
        """계획을 장치에 반영한다. 반환은 기존 placement 행동 목록과 같은 모양.

        `resolutions`에서 **온디바이스 unit이 된 kind만** 조정기에 넘긴다.
        빠진 kind는 "더 이상 여기 있으면 안 되는 것"이라 이미 올라가 있었다면
        stop이 나가고, 그것이 링크가 좋아져 기능이 엣지로 옮겨갈 때 필요한
        정확한 동작이다.
        """
        prepared = self.prepare(plan)
        desired = {u.kind: resolutions[u.kind] for u in prepared.units if u.kind in resolutions}
        actions = self.reconciler.apply(desired)
        return prepared, actions

    def stop_all(self) -> tuple[PlacementAction, ...]:
        """이 장치의 unit을 전부 내린다 — 빈 목표 상태를 적용하는 것과 같다."""
        return self.reconciler.apply({})

    def rollback(self, unit_id: str):
        """마지막 정상 버전으로 되돌린다(AI-B-05). 채널이 못 하면 `None`."""
        return self.channel.rollback(unit_id)

    def remove(self, unit_id: str) -> None:
        self.channel.remove(unit_id)
        self._units.pop(unit_id, None)

    # --- 상태 ---------------------------------------------------------------
    def bound_units(self) -> tuple[str, ...]:
        seen: list[str] = []
        for unit_id in self._units:
            if self.reconciler.bound_provider_kind(unit_id) is not None:
                seen.append(unit_id)
        return tuple(seen)

    def state(self) -> dict:
        """화면이 그릴 수 있는 상태 한 덩어리.

        liveness/readiness/device_state는 세 개의 독립된 읽기로 그대로 싣는다.
        하나로 합치면 AI-B-05가 금지하는 "하나를 다른 상태의 근거로 대체"가
        화면 단에서 일어난다 — 주파수가 묶인 보드 위에서 멀쩡히 도는 프로세스가
        그 구분을 잃는 대표적인 경우다.
        """
        units = []
        for unit_id, unit in self._units.items():
            kind = self.reconciler.bound_provider_kind(unit_id)
            health = self.channel.health(unit_id)
            active, previous, staged = self.channel.versions(unit_id)
            units.append(
                {
                    "unit_id": unit_id,
                    "kind": kind or unit.kind,
                    "provider_id": unit.provider_id,
                    "bound": kind is not None,
                    "artifact_version": unit.artifact_version,
                    "artifact_sha256": unit.artifact_sha256,
                    "active_version": active,
                    "previous_version": previous,
                    "staged_versions": list(staged),
                    "health": _health_dict(health),
                }
            )
        return {
            "device_id": self.channel.device_id,
            "access_method": self.channel.access_method,
            "units": units,
            "audit_log": [
                {"command": e.command, "target_id": e.target_id, "requested_by": e.requested_by, "at": e.at}
                for e in list(getattr(self.channel.control, "audit_log", ()))[-20:]
            ],
        }


def _health_dict(health) -> dict | None:
    """세 갈래 health를 JSON으로. 채널이 내놓지 못하면 `None`(= 모름)."""
    if health is None:
        return None
    return {
        "reachable": getattr(health, "reachable", None),
        "liveness": _value_of(getattr(health, "liveness", None)),
        "readiness": _value_of(getattr(health, "readiness", None)),
        "device_state": _value_of(getattr(health, "device_state", None)),
        "active_version": getattr(health, "active_version", None),
        "backend": getattr(health, "backend", None),
        "temperature_c": getattr(health, "temperature_c", None),
        "throttle_raw": getattr(health, "throttle_raw", None),
        "throttle_flags": list(getattr(health, "throttle_flags", ()) or ()),
        "ready_age_s": getattr(health, "ready_age_s", None),
        "load1": getattr(health, "load1", None),
        "mem_available_kb": getattr(health, "mem_available_kb", None),
        "reason": getattr(health, "reason", None),
    }


def _value_of(item):
    return getattr(item, "value", item)
