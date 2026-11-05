"""탐지기 행동 특성 선언을 읽는다 — 판정하지 않는다.

implements: AI-C-18(구성요소 capability 선언 규약), AI-C-15(도메인 차이는 설정)
관련: AI-B-01(측정값의 주인은 여기가 아니다), AI-B-09(새 확장은 등록으로),
      AI-C-10(이름이 아니라 capability 로 탐색), AI-C-16(나가는 연결 요구의 가시화),
      AI-E-04(선택형 보조 기능의 선택)

`config/detector_characteristics.example.json` 하나를 자료형으로 옮긴다. 그
파일이 정본이고 이 모듈은 **아무 값도 화이트리스트로 검사하지 않는다** — 네
번째 탐지기를 더하는 것은 설정 한 항목이고 코드 변경이 아니다(원칙 #1·#7).
그래서 여기에는 탐지기 이름도, 벤더 enum 도, 허용 태그 목록도 없다.

여기 **적지 않는 것**
---------------------
품질·지연·메모리. 그 수치는 모델이 아니라 **실행 구성**의 성질이고
`contracts/profile.py` 의 `MeasurementSet`/`VerifiedExecutionProfile`(AI-B-01)과
`config/model_versions.example.json` 이 주인이다. 같은 사실을 두 곳에서 선언하면
어느 쪽이 맞는지 아무도 모른다.

선언과 관측을 가른다
--------------------
"이 모델이 어휘를 어떻게 받는가"는 어디서 돌려도 참인 선언이다. "그 가중치가 이
노드에 있는가"는 관측이고, 기계마다 다르다. 그래서 전자는 파일에 적고 후자는
`weights_present(asset_root)` / `missing_external_assets(asset_root)` 가 그때
계산한다. 선언 파일에 `present: true` 를 적어 두면 그 줄은 다른 기계에서 거짓말이
된다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

#: 기본 선언 파일. 다른 파일을 쓰려면 `from_file(path)` 에 경로를 준다.
DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "detector_characteristics.example.json")

#: 가중치 출처가 로컬 파일이 **아닐** 때 존재 여부 질문의 답. False(없다)와 다르다 —
#: 물어볼 로컬 경로가 없다는 뜻이다.
PRESENCE_NOT_APPLICABLE = None

#: 존재 여부 답(`bool | None`)과 **짝으로** 나가는 사유. `None` 이 되는 길이 둘이고
#: 그 둘은 받는 쪽이 할 일이 다르기 때문이다 — 허브 스냅샷은 할 일이 없고, 자산
#: 뿌리가 없는 노드는 뿌리를 가리키면 답이 생긴다. `False`(선언된 경로를 **보고**
#: 없었다)는 세 번째 사실이라 이 셋과 섞이지 않는다(미측정 ≠ 0 ≠ 미달).
#: `observability/host_resources.py` 가 온도를 `(값, 사유)` 로 내는 것과 같은 축이다.
PRESENCE_MEASURED = "measured"
PRESENCE_SOURCE_NOT_LOCAL = "source_not_local"
PRESENCE_NO_ASSET_ROOT = "no_asset_root"

#: `outbound_network_reason()` 이 "가중치 때문" 을 가리킬 때 쓰는 값. 외부 자산은
#: 자기 `asset_id` 로 돌아오므로 그것들과 겹치지 않는 이름이어야 한다.
WEIGHTS_SOURCE_REASON = "weights"


class DetectorCatalogError(ValueError):
    """선언 파일의 구조가 깨졌다. 값의 내용은 여기서 판정하지 않는다."""


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise DetectorCatalogError(f"expected a JSON array of strings, got a scalar: {value!r}")
    return tuple(str(item) for item in value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


@dataclass(frozen=True)
class ExternalAssetDeclaration:
    """모델 가중치와 **별개로** 필요한 자산 한 건.

    YOLO-World 의 CLIP 텍스트 인코더, YOLOE 프롬프트 모드의 MobileCLIP 인코더가
    그 자리다. 이것이 선언으로 드러나야 폐쇄망 배치가 배치 **전에** 검증된다
    (AI-C-16: "어떤 실행 단위가 외부 연결을 요구하는지는 등록 정보로 드러나야").
    """

    asset_id: str
    path: str | None
    size_bytes: int | None
    required_for: tuple[str, ...]
    outbound_network_if_absent: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ExternalAssetDeclaration":
        asset_id = raw.get("asset_id")
        if not asset_id:
            raise DetectorCatalogError("external asset entry without 'asset_id'")
        return cls(
            asset_id=str(asset_id),
            path=_opt_str(raw.get("path")),
            size_bytes=_opt_int(raw.get("size_bytes")),
            required_for=_as_str_tuple(raw.get("required_for")),
            outbound_network_if_absent=bool(raw.get("outbound_network_if_absent", False)),
        )


@dataclass(frozen=True)
class WeightsDeclaration:
    """가중치 파일 하나. `size_bytes` 가 None 이면 **모르는 값**이고 0 이 아니다."""

    source: str
    path: str | None
    size_bytes: int | None
    outbound_network_if_absent: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "WeightsDeclaration":
        return cls(
            source=str(raw.get("source", "")),
            path=_opt_str(raw.get("path")),
            size_bytes=_opt_int(raw.get("size_bytes")),
            outbound_network_if_absent=bool(raw.get("outbound_network_if_absent", False)),
        )


@dataclass(frozen=True)
class PromptingDeclaration:
    """어휘를 **어떻게 주는가**, 그리고 바꾸는 값이 무엇인가.

    두 질문이 따로다. `model_supports_per_call_prompt` 는 모델이 원리상 호출마다
    다른 프롬프트를 받을 수 있는지이고, `vocabulary_change_requires` 는 **지금
    코드가** 어휘를 바꾸려면 무엇을 요구하는지다. 둘을 한 칸에 담으면 "원리상
    싼데 우리 구현이 비싸다"는 사실이 사라지고, 그 사실이 바로 고칠 수 있는
    자리를 가리킨다.
    """

    vocabulary_channel: str
    prompt_required: bool
    prompt_syntax: str | None
    model_supports_per_call_prompt: bool
    provider_fixes_prompt_at_construction: bool
    vocabulary_change_requires: tuple[str, ...]
    vocabulary_change_invalidates_results: bool
    builtin_vocabulary_size: int | None
    label_namespace: str
    label_prefix: str | None
    #: 이 탐지기의 라벨을 `perception/obstacle_taxonomy.py` 의 어느 어휘로
    #: 판정해야 하는가. None 은 "모른다"가 아니라 **선언된 어떤 어휘에도 속하지
    #: 않는다** — prompt-free 라벨이 그렇고, 그래서 전부 unmapped 로 남는다.
    taxonomy_vocabulary: str | None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PromptingDeclaration":
        return cls(
            vocabulary_channel=str(raw.get("vocabulary_channel", "")),
            prompt_required=bool(raw.get("prompt_required", False)),
            prompt_syntax=_opt_str(raw.get("prompt_syntax")),
            model_supports_per_call_prompt=bool(raw.get("model_supports_per_call_prompt", False)),
            provider_fixes_prompt_at_construction=bool(
                raw.get("provider_fixes_prompt_at_construction", False)),
            vocabulary_change_requires=_as_str_tuple(raw.get("vocabulary_change_requires")),
            vocabulary_change_invalidates_results=bool(
                raw.get("vocabulary_change_invalidates_results", False)),
            builtin_vocabulary_size=_opt_int(raw.get("builtin_vocabulary_size")),
            label_namespace=str(raw.get("label_namespace", "")),
            label_prefix=_opt_str(raw.get("label_prefix")),
            taxonomy_vocabulary=_opt_str(raw.get("taxonomy_vocabulary")),
        )


@dataclass(frozen=True)
class OutputDeclaration:
    """무엇을 내주고, 무엇을 **못 싣고**, 무엇이 아예 없는가.

    `not_surfaced` 와 `missing` 은 다른 사실이다. YOLOE seg 가중치는 인스턴스
    마스크를 실제로 계산하지만 `perception/detection.py::PerceptionResult` 에 그
    칸이 없어 전달되지 않는다 — 모델에 없는 것(깊이·내부 파라미터)과 한 칸에
    담으면 "마스크를 쓰려면 계약만 넓히면 된다"는 사실이 사라진다.
    `edge/zipdepth_provider.py::health()["missing_outputs"]` 의 선언된 결손과 같은
    축이다.
    """

    provided: tuple[str, ...]
    not_surfaced: tuple[str, ...]
    missing: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "OutputDeclaration":
        return cls(
            provided=_as_str_tuple(raw.get("provided")),
            not_surfaced=_as_str_tuple(raw.get("not_surfaced")),
            missing=_as_str_tuple(raw.get("missing")),
        )


@dataclass(frozen=True)
class ConstructionDeclaration:
    """그 provider 를 **무슨 인자 이름으로** 세우는가.

    세 계열의 생성자가 서로 다르다 — 어휘를 첫 인자로 받는 것, 가중치 경로를 받는
    것, 점수 하한의 이름이 `conf` 인 것과 `box_threshold` 인 것. 그 차이를
    `provider_for()` 안에서 탐지기 이름으로 분기하면 **네 번째 탐지기가 코드
    변경이 된다**. 그래서 조립 규약도 선언 데이터다.

    `param_kwargs` 는 운영자 파라미터 이름 → 생성자 인자 이름이다. 여기에 없는
    파라미터는 전달되지 않는다 — 그래서 `accepted_params` 를 선언 행에 함께 내서
    운영자가 **고르기 전에** 무엇이 받아들여지는지 알게 한다(조용히 버리지 않는다).
    """

    weights_kwarg: str | None
    vocabulary_kwarg: str | None
    param_kwargs: dict[str, str]
    fixed_kwargs: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ConstructionDeclaration":
        params = raw.get("param_kwargs") or {}
        fixed = raw.get("fixed_kwargs") or {}
        if not isinstance(params, Mapping) or not isinstance(fixed, Mapping):
            raise DetectorCatalogError("construction: 'param_kwargs'/'fixed_kwargs' must be objects")
        return cls(
            weights_kwarg=_opt_str(raw.get("weights_kwarg")),
            vocabulary_kwarg=_opt_str(raw.get("vocabulary_kwarg")),
            param_kwargs={str(k): str(v) for k, v in params.items()},
            fixed_kwargs=dict(fixed),
        )


@dataclass(frozen=True)
class DetectorCharacteristics:
    """탐지기 하나의 선언. 전부 **어디서 돌려도 참인 사실**이다."""

    detector_id: str
    display_name: str
    capability_kind: str
    provider_path: str | None
    tags: tuple[str, ...]
    prompting: PromptingDeclaration
    outputs: OutputDeclaration
    weights: WeightsDeclaration
    external_assets: tuple[ExternalAssetDeclaration, ...]
    construction: ConstructionDeclaration
    notes: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DetectorCharacteristics":
        detector_id = raw.get("detector_id")
        if not detector_id:
            raise DetectorCatalogError("detector entry without 'detector_id'")
        assets = raw.get("external_assets") or ()
        if isinstance(assets, (str, bytes)):
            raise DetectorCatalogError(f"{detector_id}: 'external_assets' must be a JSON array")
        return cls(
            detector_id=str(detector_id),
            display_name=str(raw.get("display_name", detector_id)),
            capability_kind=str(raw.get("capability_kind", "")),
            provider_path=_opt_str(raw.get("provider_path")),
            tags=_as_str_tuple(raw.get("tags")),
            prompting=PromptingDeclaration.from_dict(raw.get("prompting") or {}),
            outputs=OutputDeclaration.from_dict(raw.get("outputs") or {}),
            weights=WeightsDeclaration.from_dict(raw.get("weights") or {}),
            external_assets=tuple(ExternalAssetDeclaration.from_dict(a) for a in assets),
            construction=ConstructionDeclaration.from_dict(raw.get("construction") or {}),
            notes=str(raw.get("$comment", "")),
        )

    # ── 선언에서 바로 답할 수 있는 질문 ─────────────────────────────────────

    def gives(self, output_name: str) -> bool:
        """그 출력을 이 provider 가 실제로 **전달하는가**. 계산 여부가 아니다."""
        return output_name in self.outputs.provided

    @property
    def requires_prompt(self) -> bool:
        return self.prompting.prompt_required

    @property
    def vocabulary_change_is_free(self) -> bool:
        """어휘를 바꾸는 데 아무것도 요구하지 않는가(= 바꿀 어휘가 없거나 공짜)."""
        return not self.prompting.vocabulary_change_requires

    @property
    def accepted_params(self) -> tuple[str, ...]:
        """이 탐지기가 실제로 받는 운영자 파라미터 이름. 나머지는 전달되지 않는다."""
        return tuple(sorted(self.construction.param_kwargs))

    def prompt_ref(self, class_names=()) -> str:
        """이 탐지기 + 이 어휘가 만드는 **실행 구성 축 값**(AI-B-01).

        정규화는 여기서 하지 않고 `contracts/profile.py::prompt_ref_for` 에
        위임한다 — 같은 어휘를 다른 순서로 적은 것이 같은 구성이라는 규칙의 주인이
        둘이 되면 측정값이 엉뚱한 구성에 붙는다.

        세 상태가 **서로 다른 값**이 된다:
        어휘를 받지 않는 모델(`"prompt_free"`), 어휘를 받지만 아직 아무도 고르지
        않은 상태(`""`), 어휘가 정해진 상태(`"vocabN:…"`).
        """
        from mission_runtime.contracts.profile import prompt_ref_for

        return prompt_ref_for(class_names, prompt_free=not self.prompting.prompt_required)

    # ── 이 노드에서만 답할 수 있는 질문(관측) ───────────────────────────────

    def weights_present(self, asset_root: str | Path | None) -> bool | None:
        """가중치 파일이 이 노드에 있는가. 물어볼 수 없으면 `None` 이다.

        `None` 은 "없다"가 아니다 — HF Hub 스냅샷처럼 물어볼 로컬 파일이 없는
        출처거나, 물어볼 **자리**(자산 뿌리)가 이 노드에 없다는 뜻이고, 그 둘을
        `False` 와 한 값으로 접으면 화면이 "없음"을 띄워 운영자가 없는 문제를
        고치러 간다. 둘 중 어느 쪽인지는 `presence_reason()` 이 말한다.

        자산 뿌리가 없는 노드는 **정상 배치다**(AI-C-05) — 공개 트리만 받은 사람에게
        `local/` 은 없고, 그 상태에서 예외가 나면 선택 결손이 장애로 번진다.
        """
        if self.weights.path is None:
            return PRESENCE_NOT_APPLICABLE
        if asset_root is None:
            return PRESENCE_NOT_APPLICABLE
        return (Path(asset_root) / self.weights.path).exists()

    def presence_reason(self, asset_root: str | Path | None) -> str:
        """존재 여부 답이 **어떻게 나온 것인가**. 값과 짝으로 읽는다.

        `measured` 는 실제로 보고 답한 것이고, 나머지 둘은 묻지 못한 것이다.
        묻지 못한 이유를 하나로 합치면 "뿌리를 가리키면 답이 생기는 상태" 와
        "애초에 물을 것이 없는 출처" 가 같아 보인다.
        """
        if asset_root is None:
            return PRESENCE_NO_ASSET_ROOT
        if self.weights.path is None:
            return PRESENCE_SOURCE_NOT_LOCAL
        return PRESENCE_MEASURED

    def external_assets_absent_from(self, search_paths) -> tuple[str, ...]:
        """선언된 외부 자산 중 **이 자리들 어디에도** 없는 것의 asset_id.

        `missing_external_assets()` 와 **다른 질문이다.** 가중치는 우리가 경로를
        넘겨 읽히지만(`provider_for` 가 `asset_root / path` 를 준다) 외부 자산은
        **찾는 쪽이 라이브러리다** — ultralytics 는 작업 디렉터리와 자기
        weights_dir 을 보고 없으면 받아 온다. 그래서 "자산 뿌리에 있다" 는
        "받아 오지 않는다" 의 근거가 되지 못하고, 그 둘을 한 질문으로 합치면
        뿌리에 파일을 둔 노드가 "나가지 않는다" 고 거짓을 말한다(실측: 프롬프트형
        YOLOE 의 텍스트 인코더 572MB 가 뿌리에는 있고 런타임 자리에는 없었다).

        **어디를 보는지는 그 자리를 아는 쪽이 넘겨준다** — provider 를 세우는
        쪽만 자기 작업 디렉터리를 안다. 이 모듈은 선언을 들고 비교만 한다.
        """
        bases = [Path(p) for p in search_paths]
        return tuple(
            a.asset_id for a in self.external_assets
            if a.path is not None and not any((base / a.path).is_file() for base in bases)
        )

    def missing_external_assets(self, asset_root: str | Path | None) -> tuple[str, ...]:
        """선언된 외부 자산 중 **자산 뿌리에** 없는 것의 asset_id — 조달 질문이다.

        "배치 작업이 무엇을 더 가져와야 하는가" 에 답한다. "세우면 나가는 연결이
        생기는가" 는 위 `external_assets_absent_from()` 이 답하고 자리를 호출자가
        넘긴다 — 두 질문의 답이 다를 수 있다는 것이 이 분리의 이유다.

        자산 뿌리가 없으면 빈 튜플이다 — "하나도 없다"가 아니라 **보지 않았다**이고,
        어느 쪽인지는 `presence_reason()` 이 말한다. 보지 않은 것을 "전부 없다"로
        적으면 선언된 자산 목록이 그 노드에서 전부 결손으로 보이고, "전부 있다"로
        적으면 폐쇄망 배치 전 검증이 거짓으로 통과한다 — 그래서 값이 아니라 사유로
        가른다(아래 `outbound_network_required` 는 이 상태를 보수적으로 읽는다).
        """
        if asset_root is None:
            return ()
        root = Path(asset_root)
        return tuple(
            a.asset_id for a in self.external_assets
            if a.path is not None and not (root / a.path).exists()
        )

    def as_row(self, asset_root: str | Path | None, *,
               runtime_search_paths=None) -> dict[str, Any]:
        """선언 + 이 노드의 관측을 **한 행**으로. 운영 화면이 읽는 모양이다.

        `implementation_ref` 가 이 선언의 `detector_id` 와 같은 값인 것은 의도다 —
        운영자가 고른 것과 실제로 세워진 것이 같은 이름이어야 비교 결과를 되짚을 수
        있다. `prompt_free` 를 따로 내는 이유: 시도 경로가 그 값으로 구성 축을
        채우고(`prompt_ref`), 어휘가 비어 있는 것과 **다른 상태**로 남겨야 한다.
        """
        root = None if asset_root is None else Path(asset_root)
        return {
            "implementation_ref": self.detector_id,
            "detector_id": self.detector_id,
            "display_name": self.display_name,
            "capability_kind": self.capability_kind,
            "provider_path": self.provider_path,
            "tags": list(self.tags),
            "prompt_free": not self.prompting.prompt_required,
            "prompting": {
                "vocabulary_channel": self.prompting.vocabulary_channel,
                "prompt_required": self.prompting.prompt_required,
                "prompt_syntax": self.prompting.prompt_syntax,
                "model_supports_per_call_prompt": self.prompting.model_supports_per_call_prompt,
                "provider_fixes_prompt_at_construction":
                    self.prompting.provider_fixes_prompt_at_construction,
                "vocabulary_change_requires": list(self.prompting.vocabulary_change_requires),
                "vocabulary_change_invalidates_results":
                    self.prompting.vocabulary_change_invalidates_results,
                "builtin_vocabulary_size": self.prompting.builtin_vocabulary_size,
                "label_namespace": self.prompting.label_namespace,
                "label_prefix": self.prompting.label_prefix,
                "taxonomy_vocabulary": self.prompting.taxonomy_vocabulary,
            },
            "outputs": {
                "provided": list(self.outputs.provided),
                "not_surfaced": list(self.outputs.not_surfaced),
                "missing": list(self.outputs.missing),
            },
            "weights": {
                "source": self.weights.source,
                "path": self.weights.path,
                "size_bytes": self.weights.size_bytes,
            },
            "external_assets": [
                {"asset_id": a.asset_id, "path": a.path, "size_bytes": a.size_bytes,
                 "required_for": list(a.required_for)}
                for a in self.external_assets
            ],
            "accepted_params": list(self.accepted_params),
            # 관측. 선언이 아니라 이 기계의 사실이다.
            "weights_present": self.weights_present(root),
            # 그 답이 측정인가 미측정인가, 미측정이면 무엇 때문인가. 값만 보면
            # `None` 두 종류가 같아 보인다(AI-O-05: 미측정은 별도 상태다).
            "presence_reason": self.presence_reason(root),
            "missing_external_assets": list(self.missing_external_assets(root)),
            "outbound_network_required": self.outbound_network_required(
                root, runtime_search_paths=runtime_search_paths),
            # 무엇 때문인지. bool 만 내면 화면이 그 답을 다시 계산한다.
            "outbound_network_reason": self.outbound_network_reason(
                root, runtime_search_paths=runtime_search_paths),
            "buildable_here": self.buildable_here(root),
            "notes": self.notes,
        }

    def buildable_here(self, asset_root: str | Path | None) -> bool:
        """이 노드에서 provider 를 세울 수 있는가(어휘는 빼고 자산만 본다).

        어휘는 운영자가 그때 넣는 값이라 여기 포함하지 않는다 — 포함하면 어휘를
        고르기 전의 화면이 전부 "불가" 로 보인다.

        자산 뿌리가 없으면 **로컬 가중치를 선언한 탐지기는 조달할 수 없다** —
        그 가중치를 찾아볼 자리가 없으니 "세울 수 있다"고 말하지 않는다. 반대로
        로컬 경로를 선언하지 않은 출처(허브 스냅샷)는 뿌리와 무관하므로 그대로
        남는다. 둘을 함께 끄면 "뿌리만 주면 되는 것" 과 "애초에 뿌리를 안 쓰는 것"
        이 한 칸에 담긴다.
        """
        if not self.provider_path:
            return False
        if asset_root is None and self.weights.path is not None:
            return False
        return self.weights_present(asset_root) is not False

    def outbound_network_reason(self, asset_root: str | Path | None, *,
                                runtime_search_paths=None) -> str | None:
        """나가는 연결이 필요하면 **무엇 때문인지**, 아니면 `None`(AI-C-16).

        `WEIGHTS_SOURCE_REASON` 이면 가중치 때문이고, 그 밖에는 외부 자산의
        `asset_id` 다. bool 만 내면 운영 화면이 "무엇을 받아와야 하는지" 를 다시
        계산해야 하고, 그러면 같은 판정의 주인이 둘이 된다.

        `runtime_search_paths` 는 **추론 런타임이 외부 자산을 찾는 자리들**이다.
        provider 를 세우는 쪽만 그 자리를 알기 때문에 입력으로 받는다. 넘기지
        않으면 이 모듈은 "받아 오지 않는다" 고 말할 수 없다 — 자산 뿌리에 있다는
        사실은 그 근거가 아니다(위 `external_assets_absent_from` 참조). 그래서
        **보수적으로** 연결이 필요하다고 답한다: 폐쇄망 프로파일의 배치 전 검증이
        거짓으로 통과하는 것보다 한 번 더 경고하는 편이 낫다.
        """
        if self.weights_present(asset_root) is not True and self.weights.outbound_network_if_absent:
            return WEIGHTS_SOURCE_REASON
        if runtime_search_paths is None:
            # 자리를 모른다 — 선언이 연결을 요구한다고 적은 자산이 있으면 그대로
            # 답한다(자산 뿌리가 없는 노드도 같은 길로 들어온다).
            absent = {a.asset_id for a in self.external_assets if a.path is not None}
        else:
            absent = set(self.external_assets_absent_from(runtime_search_paths))
        for asset in self.external_assets:
            if asset.asset_id in absent and asset.outbound_network_if_absent:
                return asset.asset_id
        return None

    def outbound_network_required(self, asset_root: str | Path | None, *,
                                  runtime_search_paths=None) -> bool:
        """위 판정의 bool. **같은 판정을 두 번 하지 않는다** — 사유 쪽을 부른다."""
        return self.outbound_network_reason(
            asset_root, runtime_search_paths=runtime_search_paths) is not None


class DetectorCatalog:
    """선언 파일 하나를 담는다. 순서는 파일에 적힌 순서다."""

    def __init__(self, declaration: Mapping[str, Any]) -> None:
        entries = declaration.get("detectors")
        if not isinstance(entries, list):
            raise DetectorCatalogError("detector catalog: 'detectors' must be a JSON array")
        detectors: dict[str, DetectorCharacteristics] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise DetectorCatalogError("detector catalog: each entry must be a JSON object")
            item = DetectorCharacteristics.from_dict(entry)
            if item.detector_id in detectors:
                raise DetectorCatalogError(f"duplicate detector_id: {item.detector_id}")
            detectors[item.detector_id] = item
        self._detectors = detectors

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "DetectorCatalog":
        raw = json.loads(Path(path or DEFAULT_CATALOG_PATH).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise DetectorCatalogError("detector catalog: top level must be a JSON object")
        return cls(raw)

    @property
    def detector_ids(self) -> tuple[str, ...]:
        return tuple(self._detectors)

    def all(self) -> tuple[DetectorCharacteristics, ...]:
        return tuple(self._detectors.values())

    def get(self, detector_id: str) -> DetectorCharacteristics:
        try:
            return self._detectors[detector_id]
        except KeyError:
            raise DetectorCatalogError(f"unknown detector_id: {detector_id}") from None

    def of_capability(self, capability_kind: str) -> tuple[DetectorCharacteristics, ...]:
        """같은 capability 를 제공하는 탐지기들. 이름이 아니라 capability 로 고른다(AI-C-10)."""
        return tuple(d for d in self._detectors.values() if d.capability_kind == capability_kind)

    def presence(self, asset_root: str | Path | None, *,
                 runtime_search_paths=None) -> dict[str, dict[str, Any]]:
        """이 노드에서의 관측만 모아 낸다 — 선언은 `all()`/`get()` 이 낸다.

        둘을 한 응답으로 합치지 않는 이유: 선언은 저장소가 정본이고 관측은 기계마다
        다르다. 합쳐 두면 소비자가 어느 쪽을 캐시해도 되는지 알 수 없다.
        """
        root = None if asset_root is None else Path(asset_root)
        return {
            d.detector_id: {
                "weights_present": d.weights_present(root),
                "presence_reason": d.presence_reason(root),
                "missing_external_assets": list(d.missing_external_assets(root)),
                "outbound_network_required": d.outbound_network_required(
                    root, runtime_search_paths=runtime_search_paths),
                "outbound_network_reason": d.outbound_network_reason(
                    root, runtime_search_paths=runtime_search_paths),
            }
            for d in self._detectors.values()
        }


# ── 운영 콘솔이 부르는 두 이름 ───────────────────────────────────────────────
# `tools/fms_console/serve.py` 가 ImportError fallback 과 함께 이 둘만 쓴다.
# 표면을 작게 유지하는 것이 약속이라, 새 기능은 선언 항목으로 늘리고 이 두 이름의
# 수는 늘리지 않는다.


def characteristics(*, asset_root: str | Path | None,
                    catalog_path: str | Path | None = None,
                    runtime_search_paths=None) -> list[dict[str, Any]]:
    """선언 전부를 운영 화면이 읽을 행 목록으로. **아무것도 돌리지 않는다.**

    선언이 없으면 빈 목록이다 — 없는 특성을 추측해 채우지 않는다.

    `asset_root=None` 은 **정상 입력이다** — 자산 뿌리가 없는 노드(공개 트리만 받은
    사람)에서 선언은 그대로 읽히고 관측 칸만 미측정으로 남는다(AI-C-05). 전에는
    여기서 `Path(None)` 이 `TypeError` 가 되어 선택 결손이 장애로 번졌다.
    """
    return [d.as_row(asset_root, runtime_search_paths=runtime_search_paths)
            for d in DetectorCatalog.from_file(catalog_path).all()]


def provider_for(implementation_ref: str, *, vocabulary, params,
                 asset_root: str | Path | None,
                 catalog_path: str | Path | None = None):
    """선언 하나를 실제 provider 로 세운다. 세울 수 없으면 **None** 이고 장애가 아니다.

    `None` 이 되는 경우는 전부 "이 노드에서는 안 된다" 다(AI-C-05): 선언에 없는
    참조, 가중치가 없는 노드, **자산 뿌리가 없어 가중치를 찾아볼 자리가 없는 노드**,
    어휘가 필요한데 비어 있음, provider 모듈을 import 할 수 없음(그 optional
    의존성이 이 노드에 없음, AI-C-05).

    조립은 **선언의 `construction` 규약**으로만 한다 — 탐지기 이름으로 분기하지
    않으므로 네 번째 탐지기도 설정 한 항목이다. 선언에 없는 파라미터는 전달되지
    않고, 무엇이 받아들여지는지는 `as_row()["accepted_params"]` 로 미리 드러난다.
    """
    import importlib

    root = None if asset_root is None else Path(asset_root)
    try:
        detector = DetectorCatalog.from_file(catalog_path).get(implementation_ref)
    except (DetectorCatalogError, OSError):
        return None

    names = [str(v) for v in (vocabulary or ()) if str(v).strip()]
    if detector.prompting.prompt_required and not names:
        return None
    if not detector.provider_path:
        return None

    recipe = detector.construction
    kwargs: dict[str, Any] = dict(recipe.fixed_kwargs)

    if recipe.weights_kwarg is not None:
        # 뿌리가 없으면 가중치를 찾아볼 자리가 없다 — 추측한 자리를 집어 넣으면
        # 운영자가 고른 것과 실제로 돌아간 것이 달라진다.
        if detector.weights.path is None or root is None:
            return None
        weights = root / detector.weights.path
        if not weights.exists():
            return None
        kwargs[recipe.weights_kwarg] = weights
    elif detector.weights_present(root) is False:
        return None

    if recipe.vocabulary_kwarg is not None:
        kwargs[recipe.vocabulary_kwarg] = names

    for operator_name, argument_name in recipe.param_kwargs.items():
        if params and operator_name in params:
            kwargs[argument_name] = params[operator_name]

    module_name, _, class_name = detector.provider_path.partition(":")
    try:
        target = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError):
        return None
    try:
        return target(**kwargs)
    except (TypeError, ValueError):
        # 선언과 생성자가 어긋났다. 여기서 추측해 고치지 않는다 — 고장은 선언에
        # 있고, 추측은 운영자가 고른 것과 돌아간 것을 다르게 만든다.
        return None
