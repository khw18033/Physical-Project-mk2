"""What the operator corrected, kept apart from what was declared.

implements: AI-L-03 (사용자 확인·의미 정보 반영), AI-S-08 (사전정보와 관측의 분리)
관련: AI-N-02 (last-known-good), AI-C-19, AI-L-08 (계보 추적)
tests: tests/test_fms_overlay.py

## 왜 선언 파일을 고치지 않는가

운영자가 관제 웹에서 고정 장치 자리를 옮기거나 실측값을 입력하면, 그 값을
`profiles/domains.example.json` 에 덮어쓰는 것이 가장 쉬운 길이다. 그러면 **원래
선언이 무엇이었는지 사라진다**. 사라지면 두 가지를 더는 말할 수 없다 — 선언과 실측이
얼마나 어긋났는지, 그리고 누가 언제 왜 고쳤는지. 전자는 현장 조사가 필요한지 판단하는
근거이고, 후자는 잘못된 수정을 되짚는 유일한 길이다.

그래서 선언은 읽기 전용으로 두고 수정분만 **덧대어 누적**한다. 지우는 것도 삭제가
아니라 "되돌렸다"는 항목을 하나 더 쌓는 것이다 — append-only 라서 이력이 끊기지 않고,
`continual/lineage.py` 의 append-only 계보와 같은 이유로 같은 모양을 쓴다.

## 설치 트리 밖, 그러나 사용자 상태 디렉터리 안에 둔다

현장에서 고친 값은 그 현장의 것이고 공개 저장소에 올릴 것이 아니다. 그런데 "저장소
밖"을 **저장소에 상대적으로** 적으면(`../local/...`) 자리가 두 가지 방식으로 어긋난다 —
상대 경로는 프로세스의 작업 디렉터리를 따라가고, 설치된 패키지에서 `..` 는
`site-packages/` 다. 즉 패키지 하나를 `pip install` 한 사람이 운영자 수정을 남기면
그것이 **설치 트리 안에** 떨어진다. 설치물은 패키지 관리자의 것이고 런타임이 쓸 자리가
아니다(AI-B-02: 실행 단위는 재현 가능해야 하고 런타임 상태가 섞이면 재현이 깨진다).

그래서 기본 자리는 사용자 상태 디렉터리다 — `$MISSION_RUNTIME_STATE`, 없으면
XDG 규약의 `$XDG_STATE_HOME/mission_runtime`, 그것도 없으면
`~/.local/state/mission_runtime`. 셋 다 쓰기 가능하고, 재설치해도 남고, 설치 트리와
저장소 양쪽 바깥이다. 자리를 명시하고 싶으면 `--overlay PATH` 로 준다.

파일이 없는 것은 오류가 아니라 "아직 아무도 고치지 않았다"는 정상 상태다(AI-C-05).

## 쓰기는 원자적으로

관제 웹에서 끌어다 놓는 동작은 초당 여러 번 들어올 수 있다. 같은 파일을 반쯤 쓴
상태로 읽으면 수정 이력 전체를 잃는다. 임시 파일에 쓰고 `os.replace` 로 바꿔
반쯤 쓰인 파일이 관측되지 않게 한다.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

#: 수정의 종류. 새 종류는 이 집합에 더하는 데이터이고 분기문이 아니다.
KIND_PLACEMENT = "placement"            # 고정 장치의 설치 자리
KIND_SURVEY = "survey"                  # 사람이 입력한 공간 실측값
KIND_CUE_CORRECTION = "cue_correction"  # 추론 단서 값의 정정
KIND_OBJECT_POSITION = "object_position"  # 융합된 객체를 옮긴 것
KIND_PERMISSION = "permission"            # 계정의 권한을 부여·회수한 것
KIND_GROUND_TRUTH = "ground_truth"        # 사람이 만든 정답을 제출한 것
KIND_NODE_JOIN = "node_join"              # 새 장치를 함대에 들인 것
KIND_CALIBRATION = "calibration"          # 카메라 정보 선언·보정 실행
KIND_TRAINING = "training"                # 학습·검증·승인 요청
KIND_MODEL_ASSIGNMENT = "model_assignment"  # 기기별 적용 모델을 바꾼 것

KNOWN_KINDS: frozenset[str] = frozenset({
    KIND_PLACEMENT, KIND_SURVEY, KIND_CUE_CORRECTION, KIND_OBJECT_POSITION,
    KIND_PERMISSION, KIND_GROUND_TRUTH, KIND_NODE_JOIN, KIND_CALIBRATION,
    KIND_TRAINING, KIND_MODEL_ASSIGNMENT,
})

#: 되돌림을 나타내는 항목. 삭제가 아니라 **되돌렸다는 사실의 기록**이다.
ACTION_SET = "set"
ACTION_RESET = "reset"

#: 상태 디렉터리를 가리키는 환경변수. 시험과 폐쇄망 배포가 자리를 옮길 때 쓴다.
STATE_ROOT_ENV = "MISSION_RUNTIME_STATE"

#: 장부 파일 이름. 자리는 바뀌어도 이름은 고정이라 사람이 찾을 수 있다.
OVERLAY_FILE_NAME = "operator_edits.json"


def state_root() -> Path:
    """쓸 수 있는 상태의 뿌리. 설치 트리도 저장소도 아닌 세 번째 자리다.

    `$MISSION_RUNTIME_STATE` → `$XDG_STATE_HOME/mission_runtime` →
    `~/.local/state/mission_runtime` 순서다. 앞의 두 개는 배포·시험이 자리를
    옮기기 위한 것이고 마지막이 XDG Base Directory 의 기본값이다.
    """
    override = os.environ.get(STATE_ROOT_ENV)
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "mission_runtime"
    return Path.home() / ".local" / "state" / "mission_runtime"


def default_overlay_path() -> Path:
    """기본 장부 자리. **호출할 때** 정한다 — import 시점에 고정하면 환경변수를
    나중에 세우는 시험·배포가 옛 자리를 쓴다."""
    return state_root() / "fms_overlay" / OVERLAY_FILE_NAME

OVERLAY_FORMAT_VERSION = "1"


class OverlayError(ValueError):
    """오버레이 파일을 읽을 수 없다."""


@dataclass(frozen=True)
class EditEntry:
    """수정 1건. 누가 언제 무엇을 왜 고쳤는지가 전부 들어 있다."""

    kind: str
    target_id: str
    action: str
    actor: str
    reason: str
    edited_at: float
    payload: Mapping[str, Any] = field(default_factory=dict)
    #: 이 수정이 어느 구역·도메인에 대한 것인가. 범위 질의에 쓴다.
    scope: str | None = None

    def as_dict(self) -> dict:
        body: dict[str, Any] = {
            "kind": self.kind, "target_id": self.target_id, "action": self.action,
            "actor": self.actor, "reason": self.reason, "edited_at": self.edited_at,
        }
        if self.payload:
            body["payload"] = dict(self.payload)
        if self.scope is not None:
            body["scope"] = self.scope
        return body

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EditEntry":
        for key in ("kind", "target_id", "action", "edited_at"):
            if key not in raw:
                raise OverlayError(f"overlay entry missing {key!r}")
        return cls(
            kind=str(raw["kind"]),
            target_id=str(raw["target_id"]),
            action=str(raw["action"]),
            actor=str(raw.get("actor") or ""),
            reason=str(raw.get("reason") or ""),
            edited_at=float(raw["edited_at"]),
            payload=dict(raw.get("payload") or {}),
            scope=raw.get("scope"),
        )


@dataclass
class OperatorOverlay:
    """운영자 수정의 append-only 장부. 선언 데이터는 건드리지 않는다."""

    path: Path = field(default_factory=default_overlay_path)
    #: 끌어다 놓기처럼 잦은 쓰기에서 매번 디스크에 가지 않게 하려면 False 로 두고
    #: `flush()` 를 직접 부른다. 기본은 즉시 쓰기 — 서버가 죽어도 남는 것이 요점이다.
    autosave: bool = True
    clock: Any = time.time
    _entries: list[EditEntry] = field(default_factory=list, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _dirty: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.load()

    # -- 파일 ------------------------------------------------------------

    def load(self) -> None:
        """파일이 없으면 빈 장부다 — 오류가 아니라 '아직 아무도 고치지 않았다'."""
        if not self.path.exists():
            self._entries = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise OverlayError(f"{self.path}: not valid JSON: {error}") from error
        entries = raw.get("entries")
        if not isinstance(entries, list):
            raise OverlayError(f"{self.path}: needs an 'entries' list")
        self._entries = [EditEntry.from_dict(entry) for entry in entries]

    def flush(self) -> Path:
        """원자적으로 쓴다 — 반쯤 쓰인 파일이 관측되면 이력 전체를 잃는다."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            body = {
                "$comment": (
                    "운영자가 관제 웹에서 고친 값의 append-only 장부. 선언 프로파일"
                    "(profiles/domains.example.json)은 이 파일이 있어도 바뀌지 않는다 — "
                    "원래 선언과 사람이 고친 값을 끝까지 구분하기 위해서다. 되돌림도 "
                    "삭제가 아니라 action=reset 항목으로 쌓인다."
                ),
                "format_version": OVERLAY_FORMAT_VERSION,
                "entries": [entry.as_dict() for entry in self._entries],
            }
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.name + ".", suffix=".tmp", delete=False)
            try:
                with handle:
                    json.dump(body, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(handle.name, self.path)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
            self._dirty = False
            return self.path

    # -- 쓰기 ------------------------------------------------------------

    def record(
        self,
        kind: str,
        target_id: str,
        payload: Mapping[str, Any],
        *,
        actor: str,
        reason: str = "",
        scope: str | None = None,
    ) -> EditEntry:
        if kind not in KNOWN_KINDS:
            # 모르는 종류를 조용히 받으면 읽는 쪽이 그것을 영원히 모른다.
            raise OverlayError(f"unknown overlay kind: {kind!r}")
        if not target_id:
            raise OverlayError("target_id must not be empty")
        if not actor:
            # 누가 고쳤는지 모르는 수정은 되짚을 수 없다(AI-L-03).
            raise OverlayError("actor must not be empty")
        entry = EditEntry(kind=kind, target_id=target_id, action=ACTION_SET,
                          actor=actor, reason=reason, edited_at=float(self.clock()),
                          payload=dict(payload), scope=scope)
        return self._append(entry)

    def reset(self, kind: str, target_id: str, *, actor: str, reason: str = "",
              scope: str | None = None) -> EditEntry:
        """선언된 값으로 되돌린다. 이력은 지우지 않고 되돌림을 하나 더 쌓는다."""
        if kind not in KNOWN_KINDS:
            raise OverlayError(f"unknown overlay kind: {kind!r}")
        if not actor:
            raise OverlayError("actor must not be empty")
        entry = EditEntry(kind=kind, target_id=target_id, action=ACTION_RESET,
                          actor=actor, reason=reason, edited_at=float(self.clock()),
                          scope=scope)
        return self._append(entry)

    def _append(self, entry: EditEntry) -> EditEntry:
        with self._lock:
            self._entries.append(entry)
            self._dirty = True
        if self.autosave:
            self.flush()
        return entry

    # -- 읽기 ------------------------------------------------------------

    def entries(self, kind: str | None = None, target_id: str | None = None
                ) -> tuple[EditEntry, ...]:
        """시간순 그대로. 장부는 순서가 의미다."""
        return tuple(
            entry for entry in self._entries
            if (kind is None or entry.kind == kind)
            and (target_id is None or entry.target_id == target_id)
        )

    def current(self, kind: str) -> dict[str, EditEntry]:
        """지금 유효한 수정만. 되돌려진 대상은 빠진다 — 선언이 다시 이긴다."""
        latest: dict[str, EditEntry] = {}
        for entry in self._entries:
            if entry.kind != kind:
                continue
            if entry.action == ACTION_RESET:
                latest.pop(entry.target_id, None)
            else:
                latest[entry.target_id] = entry
        return latest

    def current_payloads(self, kind: str) -> dict[str, dict]:
        """`FleetModel.placement_overrides` 가 바로 받을 수 있는 모양."""
        return {
            target_id: {**dict(entry.payload), "actor": entry.actor,
                        "reason": entry.reason, "edited_at": entry.edited_at}
            for target_id, entry in self.current(kind).items()
        }

    def history(self, kind: str, target_id: str) -> tuple[dict, ...]:
        """한 대상의 수정 이력. 화면이 '언제 누가 왜'를 그리는 데 쓴다."""
        return tuple(entry.as_dict() for entry in self.entries(kind, target_id))

    def stats(self) -> dict:
        counts: dict[str, int] = {}
        for entry in self._entries:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "format_version": OVERLAY_FORMAT_VERSION,
            "entry_count": len(self._entries),
            "by_kind": counts,
            "active_by_kind": {kind: len(self.current(kind)) for kind in sorted(KNOWN_KINDS)},
            "pending_write": self._dirty,
        }
