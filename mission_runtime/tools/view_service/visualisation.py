"""들인 장치를 **가시화 파트가 받을 수 있는 모양**으로 옮긴다.

＋ 로 장치를 들이는 일이 우리 화면 안에서만 끝나면 확장이 아니다. 가시화 쪽
계약(`upstream/khw_VZ` 의 `contracts/equipment.schema.json`)이 그 사실을 직접
적는다 — **"여기 없는 것은 `assigned_targets` 에 쓸 수 없다."** 즉 그쪽 장비 목록에
들어가지 않은 장치에는 임무를 걸 수 없다. 그래서 조인이 받아들여지는 순간 그
모양으로도 한 벌 내보낸다.

**번역만 한다.** 이름·별칭·종류는 조인 선언이 이미 가진 값이고 여기서 지어내지
않는다. 그쪽 계약이 "모르면 null 이다 — 지어내지 않는다" 를 `label` 주석에 적고
있고, 같은 규칙을 여기서도 지킨다.

`additionalProperties: false` 인 계약이라 **우리가 아는 것을 더 실어 보낼 수 없다.**
자원 예산도 공지 어휘도 그쪽 칸에 자리가 없다 — 그 값들은 우리 계약으로 따로
나가고, 두 계약을 섞지 않는 것이 이 모듈이 하는 일의 전부다.

implements: AI-C-01, AI-C-04, AI-C-15, AI-C-18, AI-B-09
"""
from __future__ import annotations

from typing import Any, Mapping

#: 그쪽 계약이 받는 칸. 하나라도 더 실으면 `additionalProperties: false` 에 걸린다.
EQUIPMENT_FIELDS = ("equipment_id", "label", "label_en", "aliases",
                    "aliases_en", "kind", "zone_id")

#: 우리 역할 이름 → 가시화 장비 종류. **표가 아니라 기본값**이다 — 모르는 역할은
#: 그 역할 이름을 그대로 보낸다. 표에 없다고 장치를 빠뜨리면, 새 역할의 로봇이
#: 그쪽 목록에 영영 들어가지 못해 임무를 걸 수 없게 된다(절대 준수 #3·#7).
ROLE_TO_KIND = {
    "ugv": "robot",
    "uav": "robot",
    "fixed_camera": "camera",
    "fixed_manipulator": "manipulator",
    "edge": "compute",
    "server": "compute",
}


def equipment_entry(manifest: Mapping[str, Any], *,
                    zone_id: str | None = None) -> dict:
    """조인 선언 한 건을 가시화 장비 한 칸으로.

    `label` 은 모르면 **null 이다.** 장치 id 를 이름 자리에 복사해 넣으면 그쪽
    화면이 사람이 지은 이름으로 읽고, 나중에 진짜 이름이 생겨도 그것이 이미
    이름인 줄 알고 덮지 않는다.
    """
    device_id = str(manifest.get("device_id") or "")
    if not device_id:
        raise ValueError("equipment_entry needs a device_id")
    label = manifest.get("label")
    role = str(manifest.get("role") or "")
    entry = {
        "equipment_id": device_id,
        # 선언에 사람이 부르는 이름이 없으면 null 이다. 지어내지 않는다.
        "label": label if isinstance(label, str) and label.strip() else None,
        "aliases": sorted({a for a in manifest.get("aliases", ()) if a}),
        "kind": ROLE_TO_KIND.get(role, role or None),
        "zone_id": zone_id,
    }
    return {k: v for k, v in entry.items() if k in EQUIPMENT_FIELDS}
