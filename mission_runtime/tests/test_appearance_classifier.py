"""implements: AI-E-01, AI-S-04, AI-L-09

여기서 검증하는 것은 "분류가 맞는가"보다 먼저 **틀릴 수 있는 상황에서 무엇을
하는가**다: 사전이 없는 노드, 참조영상이 없는 기종, 두 기종이 비슷하게 나온 crop.
세 경우 모두 예외도 추측도 아니어야 한다(AI-C-05, AI-S-04).

점수 계산은 공개 트리의 실제 사전(config/device_appearance_classes.example.json)에
실린 **진짜 CLIP 벡터**로 돌린다 — 유사도를 흉내 낸 값으로 재면 임계값이 맞는지는
영영 알 수 없다. 모델 파일과 원본 사진이 필요한 시험만 자산 유무로 skip 된다
(자산 자리는 conftest 의 asset_path 한 곳이 정한다).
"""

import json

import pytest

from conftest import PACKAGE_DIR, asset_path
from mission_runtime.contracts.data_dictionary import (
    WEIGHTED_REFERENCE_SIMILARITY,
    FEATURE_SIMILARITIES,
    MANDATORY_GATES,
    SEMANTIC_CLASS,
)
from mission_runtime.perception.appearance_classifier import (
    ORIGIN_FIELD,
    ORIGIN_WEB,
    REASON_NO_DICTIONARY,
    REASON_NO_ENGINE,
    REASON_NO_FIT_CLASS,
    UNFIT_ALL_WEIGHTS_ZERO,
    UNFIT_NO_REFERENCE,
    AppearanceClassifier,
    AppearanceDictionary,
    AppearanceState,
    ClassScore,
)

#: 사전은 공개 트리의 설정이라 자산 뿌리와 달리 항상 있다 — 판정 규칙 시험은
#: 어떤 노드에서도 돌아야 한다.
DICTIONARY_PATH = PACKAGE_DIR / "config" / "device_appearance_classes.example.json"

CLIP_DIR = asset_path("models", "openvocab", "clip-vit-base-patch32")
REFERENCE_ROOT = asset_path("appearance")

needs_model = pytest.mark.skipif(
    not (CLIP_DIR / "onnx" / "vision_model_quantized.onnx").exists(),
    reason="CLIP onnx 모델이 없는 노드 — 이 provider 시험만 skip 된다 (AI-C-05)",
)
needs_reference_images = pytest.mark.skipif(
    not REFERENCE_ROOT.exists(),
    reason="내려받은 참조영상이 없다 (tools/appearance/fetch_references.py)",
)


@pytest.fixture(scope="module")
def dictionary() -> AppearanceDictionary:
    return AppearanceDictionary.load(DICTIONARY_PATH)


@pytest.fixture
def classifier(dictionary) -> AppearanceClassifier:
    """모델 없이 판정 규칙만 돌리는 분류기.

    `classify_embedding` 은 사전에 실린 실제 벡터로 실제 코사인 유사도를 잰다 —
    모델이 필요한 것은 crop → 벡터 한 단계뿐이고 그 단계는 따로 시험한다.
    """
    return AppearanceClassifier(dictionary)


def _references(dictionary, class_name):
    return next(entry for entry in dictionary.fit_classes if entry.class_name == class_name)


def _dictionary_file(tmp_path, classes: dict) -> "object":
    """시험용 사전 파일 하나. 벡터는 직교 단위벡터라 유사도가 손으로 확인된다.

    실제 사전에는 지금 참조영상 0 장인 기종이 없다 — 있었던 기종(mt4)이
    2026-11-03 에 제품이 확인돼 사진이 붙었기 때문이다. 그렇다고 "0 장일 때
    어떻게 되는가"를 시험하지 않으면, 다음에 새 기종이 등록될 때 그 상태를
    처음 보게 된다.
    """
    path = tmp_path / "dictionary.json"
    path.write_text(json.dumps({"_meta": {"embedding_model": {"id": "test", "vision_model": "v"}},
                                **classes}, ensure_ascii=False), encoding="utf-8")
    return path


def _unit(dim: int, axis: int) -> list:
    vector = [0.0] * dim
    vector[axis] = 1.0
    return vector


def test_a_missing_dictionary_degrades_instead_of_raising(tmp_path):
    """사전을 배포하지 않은 노드가 기동에 실패하면 안 된다 (AI-C-05, 원칙 #3)."""
    empty = AppearanceDictionary.load(tmp_path / "there-is-no-such-file.json")

    assert empty.missing_reason == REASON_NO_DICTIONARY
    assert empty.fit_classes == ()

    verdict = AppearanceClassifier(empty).classify(object())

    assert verdict.state is AppearanceState.NO_REFERENCE
    assert verdict.appearance_class is None
    assert verdict.reason == REASON_NO_DICTIONARY


def test_a_missing_model_leaves_the_classifier_unavailable_but_callable(tmp_path):
    """모델이 없는 것도 상태이지 예외가 아니다 — 사유까지 돌려줘야 한다."""
    classifier = AppearanceClassifier.from_files(DICTIONARY_PATH, model_dir=tmp_path / "nope")

    assert classifier.available is False
    assert classifier.unavailable_reason == REASON_NO_ENGINE
    assert classifier.classify(object()).state is AppearanceState.NO_REFERENCE


def test_a_class_without_reference_images_is_reported_unfit_and_never_wins(tmp_path):
    """참조영상 0 장인 기종은 목록에서 조용히 사라지지 않는다.

    사라지면 "그 기종이 안 보인다"와 "그 기종을 볼 능력이 없다"가 같은 모양이 되고,
    운영자는 무엇을 보완해야 하는지 알 수 없다(AI-S-05). 동시에 후보로 세어서도
    안 된다 — 0 벡터로 채우면 "닮지 않았다"는 측정값처럼 보이지만 아무것도 잰 적이
    없다.
    """
    path = _dictionary_file(tmp_path, {
        "with_pictures": {"label": "사진이 있는 기종", "references": [
            {"file": "a.jpg", "embedding": _unit(4, 0)}]},
        "without_pictures": {"label": "사진이 없는 기종"},
    })
    classifier = AppearanceClassifier(AppearanceDictionary.load(path))

    assert classifier.unfit_classes == {"without_pictures": UNFIT_NO_REFERENCE}

    verdict = classifier.classify_embedding(_unit(4, 0))

    assert verdict.appearance_class == "with_pictures"
    assert [score.class_name for score in verdict.ranked] == ["with_pictures"]
    assert verdict.explanation()["unfit_classes"] == {"without_pictures": UNFIT_NO_REFERENCE}


def test_every_class_in_the_shipped_dictionary_currently_has_references(classifier):
    """실제 사전에 분류 불가 기종이 남아 있으면 그것은 보고될 사실이다."""
    assert classifier.unfit_classes == {}, (
        f"참조영상이 없는 기종이 남아 있다: {classifier.unfit_classes}")


def test_an_operator_can_weight_a_wrong_reference_out_without_hiding_it(tmp_path):
    """운영자 교정: 틀린 참조영상은 점수에서 빼되 설명에는 남긴다(AI-L-03).

    지워 버리면 "왜 저 사진이 더 이상 근거가 아닌가"를 화면에서 되짚을 수 없고,
    같은 사진이 다음 수집에서 다시 들어온다.
    """
    path = _dictionary_file(tmp_path, {
        "kind": {"label": "기종", "score_top_k_references": 1, "references": [
            {"file": "good.jpg", "embedding": _unit(4, 0), "origin": ORIGIN_WEB},
            {"file": "wrong.jpg", "embedding": _unit(4, 1), "origin": ORIGIN_WEB,
             "weight": 0.0},
        ]},
    })
    classifier = AppearanceClassifier(AppearanceDictionary.load(path))

    winner = classifier.classify_embedding(_unit(4, 1)).ranked[0]

    assert winner.score == pytest.approx(0.0, abs=1e-6), "0 으로 내린 참조영상이 점수를 냈다"
    assert [m.file for m in winner.driving_references] == ["good.jpg"]
    assert "wrong.jpg" in winner.as_dict()[FEATURE_SIMILARITIES]


def test_a_class_whose_references_are_all_weighted_out_becomes_unfit(tmp_path):
    """점수에 들어갈 사진이 하나도 남지 않으면 그 기종은 후보가 아니다."""
    path = _dictionary_file(tmp_path, {
        "kind": {"label": "기종", "references": [
            {"file": "a.jpg", "embedding": _unit(4, 0), "weight": 0.0}]},
    })
    classifier = AppearanceClassifier(AppearanceDictionary.load(path))

    assert classifier.unfit_classes == {"kind": UNFIT_ALL_WEIGHTS_ZERO}
    assert classifier.unavailable_reason == REASON_NO_FIT_CLASS
    assert classifier.classify_embedding(_unit(4, 0)).state is AppearanceState.NO_REFERENCE


def test_a_field_photo_can_be_appended_and_is_marked_as_such(tmp_path):
    """현장 사진은 제품 사진과 같은 자료형으로 **덧붙는다**.

    사전을 처음부터 다시 만들어야만 현장 사진을 넣을 수 있다면, 현장 보강은
    실제로는 일어나지 않는다. 출처 표시를 잃으면 "아직 제품 사진뿐"인 기종과
    "현장에서 확인된" 기종이 화면에서 같아 보인다.
    """
    web_only = {"kind": {"label": "기종", "references": [
        {"file": "web.jpg", "embedding": _unit(4, 0), "origin": ORIGIN_WEB}]}}
    reinforced = {"kind": {"label": "기종", "references": [
        {"file": "web.jpg", "embedding": _unit(4, 0), "origin": ORIGIN_WEB},
        {"file": "field.jpg", "embedding": _unit(4, 1), "origin": ORIGIN_FIELD}]}}

    before = AppearanceClassifier(AppearanceDictionary.load(
        _dictionary_file(_fresh(tmp_path / "before"), web_only)))
    after = AppearanceClassifier(AppearanceDictionary.load(
        _dictionary_file(_fresh(tmp_path / "after"), reinforced)))

    assert len(before.dictionary.fit_classes[0].references) == 1
    winner = after.classify_embedding(_unit(4, 1)).ranked[0]
    assert winner.as_dict()["reference_origins"] == {ORIGIN_WEB: 1, ORIGIN_FIELD: 1}
    assert [m.file for m in winner.driving_references][0] == "field.jpg"


def _fresh(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_two_near_identical_scores_produce_an_ambiguous_verdict(classifier, dictionary):
    """두 기종 사이에 놓인 crop 에서는 1 위를 고르지 않는다.

    두 기종 원형의 중간점을 실제 벡터로 만들어 넣는다 — 이 지점에서 1 위를 고르면
    그것은 판단이 아니라 동전 던지기이고, 그 결과가 개체 결속의 입력이 된다.
    """
    import numpy as np

    left = _references(dictionary, "ep01").embeddings.mean(axis=0)
    right = _references(dictionary, "holybro_x500_v2").embeddings.mean(axis=0)
    probe = left / np.linalg.norm(left) + right / np.linalg.norm(right)

    verdict = classifier.classify_embedding(probe)

    assert verdict.state is AppearanceState.AMBIGUOUS
    assert verdict.appearance_class is None
    assert verdict.margin is not None and verdict.margin <= classifier.ambiguity_margin
    assert {verdict.ranked[0].class_name, verdict.ranked[1].class_name} == {
        "ep01", "holybro_x500_v2"}
    gate = verdict.explanation()[MANDATORY_GATES]["margin_to_runner_up"]
    assert gate["passed"] is False
    assert gate["margin"] == pytest.approx(verdict.margin, abs=1e-4)


def test_nothing_like_any_reference_is_unrecognised_rather_than_assigned(classifier):
    """어느 참조영상과도 닮지 않은 crop 을 가장 가까운 기종에 떠넘기지 않는다(AI-S-04)."""
    import numpy as np

    rng = np.random.default_rng(7)
    probe = rng.normal(size=len(_first_embedding(classifier))).astype(np.float32)

    verdict = classifier.classify_embedding(probe)

    assert verdict.state is AppearanceState.UNRECOGNISED
    assert verdict.appearance_class is None
    assert verdict.explanation()[MANDATORY_GATES]["similarity_floor"]["passed"] is False


def _first_embedding(classifier):
    return classifier.dictionary.fit_classes[0].embeddings[0]


def test_every_reference_image_is_read_back_as_its_own_class(classifier, dictionary):
    """사전에 실린 벡터를 그대로 넣으면 그 기종이 나와야 한다.

    맞히는 것이 어려워서가 아니라, 사전을 쓰는 쪽과 만드는 쪽의 정규화·정렬·반올림이
    어긋나면 가장 먼저 여기서 깨지기 때문이다.
    """
    for entry in dictionary.fit_classes:
        for index, info in enumerate(entry.references):
            verdict = classifier.classify_embedding(entry.embeddings[index])

            assert verdict.state is AppearanceState.CLASSIFIED, (info.file, verdict.reason)
            assert verdict.appearance_class == entry.class_name


def test_the_explanation_names_the_reference_images_that_drove_the_score(
    classifier, dictionary
):
    """화면이 "무엇을 닮아서 그 판정인가"를 그릴 수 있어야 한다(AI-S-03)."""
    entry = _references(dictionary, "go1")
    known_files = {info.file for info in entry.references}

    explanation = classifier.classify_embedding(entry.embeddings[0]).explanation()
    winner = explanation["ranked"][0]

    assert winner[SEMANTIC_CLASS] == "go1"
    assert set(winner[FEATURE_SIMILARITIES]) == known_files
    assert winner["driving_references"], "점수를 만든 참조영상이 하나도 적히지 않았다"
    assert set(winner["driving_references"]) <= known_files
    # 1 위로 적힌 참조영상이 실제로 가장 닮은 것이어야 설명이 거짓이 아니다.
    best_file = max(winner[FEATURE_SIMILARITIES], key=winner[FEATURE_SIMILARITIES].get)
    assert winner["driving_references"][0] == best_file
    assert explanation["runner_up"] == explanation["ranked"][1][SEMANTIC_CLASS]


def test_the_explanation_carries_the_model_it_was_measured_with(classifier, dictionary):
    """어떤 모델로 잰 유사도인지 없으면 다른 배포의 수치와 비교할 수 없다(AI-B-01)."""
    from mission_runtime.contracts.data_dictionary import MODEL_VERSION

    explanation = classifier.classify_embedding(_first_embedding(classifier)).explanation()

    assert explanation[MODEL_VERSION] == dictionary.model_version
    assert explanation[MODEL_VERSION]


def test_the_verdict_never_carries_a_device_id(classifier, dictionary):
    """외형은 **종류**까지만 말한다 — 개체는 device_identity.py 가 따로 푼다.

    여기서 장치 하나를 가리키면 같은 기종 두 대가 있는 현장에서 그 값이 곧바로
    명령 대상이 된다(AI-C-19).
    """
    from mission_runtime.contracts.data_dictionary import DEVICE_ID

    verdict = classifier.classify_embedding(_first_embedding(classifier))

    assert not hasattr(verdict, DEVICE_ID)
    serialised = json.dumps(verdict.explanation(), ensure_ascii=False)
    assert DEVICE_ID not in serialised
    assert verdict.appearance_class in {entry.class_name for entry in dictionary.fit_classes}


def test_ranking_is_deterministic_for_the_same_input(classifier):
    """같은 입력에 같은 순서. 아니면 그 순서를 근거로 한 설명이 재현되지 않는다."""
    probe = _first_embedding(classifier)

    first = classifier.classify_embedding(probe).explanation()
    second = classifier.classify_embedding(probe).explanation()

    assert first == second


def test_a_tighter_margin_turns_an_ambiguous_case_into_a_pick(classifier, dictionary):
    """마진은 데이터다 — 현장마다 비교 실험으로 바꾼다(AI-C-13)."""
    import numpy as np

    left = _references(dictionary, "ep01").embeddings.mean(axis=0)
    right = _references(dictionary, "holybro_x500_v2").embeddings.mean(axis=0)
    probe = left / np.linalg.norm(left) + right / np.linalg.norm(right)

    strict = AppearanceClassifier(dictionary, ambiguity_margin=0.0)

    assert classifier.classify_embedding(probe).state is AppearanceState.AMBIGUOUS
    assert strict.classify_embedding(probe).state is AppearanceState.CLASSIFIED


def test_the_dictionary_records_the_measured_basis_for_its_thresholds():
    """임계값에 실측 근거가 없으면 그것은 근거가 아니라 취향이다(AI-B-01)."""
    payload = json.loads(DICTIONARY_PATH.read_text(encoding="utf-8"))
    check = payload["_meta"]["self_check"]

    assert check["probes"] > 0
    assert check["correct"] <= check["probes"]
    # 절대점수만으로는 가를 수 없다는 실측 사실이 사전에 남아 있어야, 나중에
    # 누군가 "0.8 이상이면 그 기종" 같은 규칙을 다시 넣지 않는다.
    assert check["other_class_score_max"] >= check["own_class_score_min"]
    assert payload["_meta"]["thresholds"]["ambiguity_margin"] > 0


def test_the_payload_never_calls_a_similarity_a_confidence():
    """닮은 정도와 근거 충분도는 **다른 축**이다(AI-S-03 첫 문장).

    한동안 이 설명 payload 는 상위 k 장 참조영상 유사도의 가중 평균을 `confidence`
    라는 이름으로 실었다. 화면은 그것을 "확신 0.87" 로 읽었지만 실제로는 "참조영상과
    0.87 닮음" 이었고, 외형은 애초에 개체를 가리지 못한다. 이름이 그 사실을 가렸다.

    implements: AI-S-03, AI-C-01
    """
    score = ClassScore(class_name="go1", label="Go1", score=0.87,
                       matches=(), driving_count=0)
    body = score.as_dict()

    assert body[WEIGHTED_REFERENCE_SIMILARITY] == 0.87
    # 두 이름을 다 내보내면 틀린 쪽이 살아남는다 — 읽는 쪽이 옛 이름을 계속 쓴다.
    assert "confidence" not in body


@needs_model
@needs_reference_images
def test_a_real_reference_photo_is_classified_through_the_real_model():
    """사진 한 장을 실제 CLIP ONNX 로 인코딩해 끝까지 돌린다.

    사전의 벡터는 이 경로로 만들어졌으므로, 여기서 다른 기종이 나오면 사전을 만들 때
    쓴 전처리와 운영에서 쓰는 전처리가 갈라진 것이다.
    """
    import cv2

    classifier = AppearanceClassifier.from_files(DICTIONARY_PATH, model_dir=CLIP_DIR)
    assert classifier.available is True

    entry = _references(classifier.dictionary, "go1")
    file_name = entry.references[0].file
    frame = cv2.imread(str(REFERENCE_ROOT / "go1" / file_name))
    assert frame is not None, f"참조영상을 읽지 못했다: {file_name}"

    verdict = classifier.classify(frame)

    assert verdict.state is AppearanceState.CLASSIFIED
    assert verdict.appearance_class == "go1"
    # `confidence` 가 아니라 **참조영상 유사도의 가중 평균**이다. 이름이 섞여 있던
    # 동안 화면은 이 값을 "확신" 으로 읽었고, 외형은 종류만 말한다(AI-S-03).
    assert (verdict.explanation()["ranked"][0][WEIGHTED_REFERENCE_SIMILARITY]
            > classifier.similarity_floor)
