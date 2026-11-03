"""등록된 장치 하나로 가는 제어 채널을 access_method로 고른다.

implements: AI-C-04, AI-B-03, AI-B-11, AI-C-10, AI-B-02

`registry/device_registry.py`는 장치를 "주소 + 사용자 + 자격증명 참조 + 태그"로만
적어 두고 그 경로가 SSH인지 시리얼인지 모른다(그 모듈의 docstring이 그렇게
못박고 있다). 그 "모른다"를 실제로 지키려면 **어딘가 한 곳**이 access_method를
구체 provider로 옮겨야 하고, 이 모듈이 그 한 곳이다.

여기 있는 것과 없는 것:

* 있는 것 — `access_method` 문자열 → provider 생성자 표. 표에 등록하는 것이
  새 접속 방식을 더하는 유일한 방법이며 핵심 코드는 고치지 않는다
  (절대 준수 원칙 #7, AI-B-09).
* 없는 것 — 장치·도메인·역할에 대한 분기. 표는 접속 **방식**으로만 갈린다
  (절대 준수 원칙 #3).

상위(`runtime/device_deployment.py`, `tools/status_ui/serve.py`)는 이 모듈이
돌려주는 `DeviceChannel`만 보고 `ssh`라는 단어를 한 번도 쓰지 않는다. 그래서
말단 제어를 MQTT 명령 경로나 다른 전송으로 바꿔도 그쪽 코드는 그대로다
(AI-C-04).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mission_runtime.registry.device_registry import DeviceCredential, DeviceRegistration

#: `ControlProvider.request("start", ...)`의 params에 실행 아티팩트를 싣는 키.
#: 제어 계약의 일부이므로 상수로 두고, 상위는 이 이름만 알면 된다.
ARTIFACT_PARAM = "artifact"

ACCESS_METHOD_SSH = "ssh"

REASON_UNSUPPORTED_ACCESS_METHOD = "unsupported_access_method"


@dataclass(frozen=True)
class DeviceChannel:
    """한 장치로 가는 제어·배포·패키징 묶음.

    `control`은 `ControlProvider` 모양이고 `deployment`는
    `ModelDeploymentProvider` 모양이다(둘 다 `providers/adapters.py`의 Protocol).
    `pack_unit`은 "소스 디렉터리를 이 채널이 보낼 수 있는 아티팩트로 만든다"는
    의미만 가진다 — tar든 OCI 이미지든 그 선택은 provider의 몫이다(AI-B-02).

    `health`/`rollback`/`versions`는 `Optional`이다. AI-C-18: "모든 항목이 항상
    존재한다고 가정해서는 안 된다" — 세 갈래 health를 내놓지 못하는 채널도
    정상이며 그때는 `get_status`의 거친 시야로 축소 운용한다(AI-C-05).
    """

    device_id: str
    access_method: str
    control: Any
    deployment: Any | None = None
    pack_unit: Callable[..., Any] | None = None

    def health(self, unit_id: str):
        fn = getattr(self.control, "health", None)
        return fn(unit_id) if callable(fn) else None

    def versions(self, unit_id: str) -> tuple[str | None, str | None, tuple[str, ...]]:
        fn = getattr(self.control, "versions", None)
        return fn(unit_id) if callable(fn) else (None, None, ())

    def rollback(self, unit_id: str):
        fn = getattr(self.control, "rollback", None)
        return fn(unit_id) if callable(fn) else None

    def remove(self, unit_id: str) -> None:
        fn = getattr(self.control, "delete", None)
        if callable(fn):
            fn(unit_id)

    def is_available(self) -> bool:
        fn = getattr(self.control, "is_available", None)
        return bool(fn()) if callable(fn) else True


class DeviceChannelError(ValueError):
    """열 수 없는 채널. 장치 장애가 아니라 **설정**의 문제일 때만 던진다."""


_FACTORIES: dict[str, Callable[..., DeviceChannel]] = {}


def register_access_method(name: str, factory: Callable[..., DeviceChannel]) -> None:
    """새 접속 방식을 표에 더한다. 핵심 코드 수정이 아니라 등록이다(AI-B-09)."""
    _FACTORIES[name] = factory


def supported_access_methods() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def open_channel(
    device: DeviceRegistration,
    credential: DeviceCredential | None = None,
    **kwargs: Any,
) -> DeviceChannel:
    """등록 정보 하나 → 제어 채널 하나.

    모르는 `access_method`는 조용히 기본값으로 떨어지지 않고 거절한다 — 오타를
    "SSH로 해석"해 버리면 어떤 장치에 무엇이 붙었는지가 설정과 달라진다.
    """
    factory = _FACTORIES.get(device.access_method)
    if factory is None:
        raise DeviceChannelError(f"{REASON_UNSUPPORTED_ACCESS_METHOD}:{device.access_method}")
    return factory(device, credential, **kwargs)


# --- 현재 배포의 구현 하나 ---------------------------------------------------
# 말단은 오케스트레이터 제어면을 두지 않으므로(절대 준수 원칙 #11) 요청 단위
# SSH가 현재 배포의 말단 제어 경로다. 이 import가 이 파일 안에만 있다는 점이
# 이 모듈의 존재 이유다.


def _ssh_channel(
    device: DeviceRegistration,
    credential: DeviceCredential | None = None,
    *,
    observability: Any = None,
    root: str | None = None,
    command_timeout_s: int = 60,
    transfer_timeout_s: int = 300,
    **_ignored: Any,
) -> DeviceChannel:
    from mission_runtime.providers.ondevice_ssh import (
        DEFAULT_ROOT,
        OnDeviceArtifactDeployment,
        OnDeviceSshControlProvider,
        pack_unit_artifact,
    )

    control = OnDeviceSshControlProvider(
        device,
        credential,
        root=root or DEFAULT_ROOT,
        command_timeout_s=command_timeout_s,
        transfer_timeout_s=transfer_timeout_s,
        observability=observability,
    )
    return DeviceChannel(
        device_id=device.device_id,
        access_method=ACCESS_METHOD_SSH,
        control=control,
        deployment=OnDeviceArtifactDeployment(control),
        pack_unit=pack_unit_artifact,
    )


register_access_method(ACCESS_METHOD_SSH, _ssh_channel)
