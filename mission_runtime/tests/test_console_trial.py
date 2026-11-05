"""implements: AI-B-09, AI-L-06, AI-B-01, AI-S-08, AI-L-03, AI-S-04, AI-C-08, AI-O-06
covers: 운영자가 웹에서 **세부 임계값을 그림에 돌려 보고 바꾸는** 길. 그 길이 쉽게
        틀리는 자리를 고정한다 — 값이 코드 상수에서 오지 않는가, 돌려 본 것과 적용한
        것이 구분되는가, 적용이 선언 파일을 덮지 않는가, 임계값을 바꾼 것이 다른 실행
        구성이 되는가(AI-B-01), 그리고 하한이 없는 라벨이 응답에서 사라지지 않는가
        (AI-S-04).

`tools/fms_console/trial.py` 의 docstring 이 가리키던 시험 파일이고, 그 파일이
없었다 — 시도 책상 전체가 시험 없이 돌고 있었다.

2026-11-04 에 두 묶음이 더해졌다. **상자 좌표**(§6) — 좌표는 표현이 아니라 상태이고,
그것 없이는 화면이 "이 모델이 어디를 봤는가" 를 그릴 수 없었다. 픽셀은 여전히 이
응답으로 나가지 않는다(AI-C-08). 그리고 **화면**(§7) — 서버 쪽은 완성되어 시험까지
있었는데 `/api/trial` · `/api/trial-run` · `/api/threshold` 를 부르는 화면 코드가 한
줄도 없었다. 브라우저를 띄우지 않고 고정할 수 있는 것(서버가 내는 칸 이름과 화면이
읽는 칸 이름의 일치, 미측정 ≠ 0 ≠ 미달 의 세 렌더링, 두 권한 두 단추)만 고정한다 —
`tests/test_fms_console_wiring.py` 가 같은 방식으로 이 페이지를 읽는다.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONSOLE_DIR = PROJECT_DIR / "tools" / "fms_console"
for candidate in (CONSOLE_DIR, PROJECT_DIR / "tools" / "status_ui"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from accounts import PERM_DEPLOY_MODEL, PERM_TRAIN, Caller  # noqa: E402
from trial import (  # noqa: E402
    BASIS_TRIAL_REQUEST,
    MAX_TRIAL_FRAMES,
    TrialCandidate,
    TrialDesk,
    candidates_from_body,
)

from mission_runtime.perception.detection_thresholds import (  # noqa: E402
    BASIS_DECLARED,
    BASIS_NO_DECLARATION,
    BASIS_OPERATOR_EDIT,
    DEFAULT_THRESHOLDS_PATH,
)
from mission_runtime.perception.obstacle_taxonomy import (  # noqa: E402
    FLOOR_ABOVE,
    FLOOR_BELOW,
    FLOOR_NO_BASIS,
)

PROMPT_FREE = "yoloe-11s-seg-prompt-free"
PROMPT_FREE_CONF = "detector.yoloe-11s-seg-prompt-free.score_floor"
PROMPTED = "yoloe-11s-seg-prompted"


def _console():
    spec = importlib.util.spec_from_file_location(
        "fms_console_serve_for_trial", CONSOLE_DIR / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


console = _console()


@pytest.fixture()
def service(tmp_path):
    return console.build_service(
        ui_config=PROJECT_DIR / "config" / "status_ui.fms.example.json",
        zone_profile=PROJECT_DIR / "profiles" / "domains.example.json",
        goal_kinds=PROJECT_DIR / "profiles" / "goal_kinds.example.json",
        with_fleet=True,
        overlay_path=tmp_path / "edits.json",
    )


def _admin():
    return Caller.for_role("admin")


class _Result:
    """provider 가 내는 상자 하나의 모양만 흉내 낸다(추론은 돌리지 않는다)."""

    def __init__(self, label, confidence, box=(0.0, 0.0, 10.0, 10.0)):
        self.label, self.confidence, self.box = label, confidence, box


class _Provider:
    """고정 결과를 내는 대역. **임계값을 자기가 적용한다** — 실제 provider 의
    `conf` 가 추론 전에 자르는 것과 같은 자리다."""

    def __init__(self, results, conf=0.0):
        self._results, self.conf = results, conf

    def is_available(self):
        return True

    def detect(self, image):
        del image
        return [r for r in self._results if r.confidence >= self.conf]


# ---------------------------------------------------------------------------
# 1. 값은 코드 상수가 아니라 선언에서 온다
# ---------------------------------------------------------------------------


def test_a_trial_with_no_numbers_in_the_form_runs_at_the_declared_value(service):
    """운영자가 아무 수도 적지 않아도 시도는 **선언된 값**으로 돈다. 그래야
    화면에 보이는 수와 실제로 돌아간 수가 같다."""
    candidates = candidates_from_body(
        [{"implementation_ref": PROMPT_FREE}], declared=service._trial_declared)

    assert len(candidates) == 1
    one = candidates[0]
    assert one.params == {"conf": 0.05}
    assert one.param_basis["conf"] == BASIS_DECLARED
    # 어휘와 이름 공간도 **선언이 정한다** — "zeroshot" 을 채워 넣지 않는다.
    assert one.taxonomy_vocabulary is None
    assert one.label_namespace == "model_builtin_vocabulary"
    assert one.prompt_free is True


def test_a_number_typed_into_the_form_is_marked_as_a_try_and_not_an_apply(service):
    """돌려 보는 것과 적용하는 것은 다른 행위다. 폼의 수는 선언을 이기지만 그
    사실이 근거에 남고, 선언 파일은 그대로다."""
    candidates = candidates_from_body(
        [{"implementation_ref": PROMPT_FREE, "params": {"conf": 0.4}}],
        declared=service._trial_declared)

    assert candidates[0].params["conf"] == 0.4
    assert candidates[0].param_basis["conf"] == BASIS_TRIAL_REQUEST
    assert service.thresholds().get(PROMPT_FREE_CONF).value == 0.05


def test_the_prompted_candidate_follows_its_own_declared_vocabulary(service):
    declared = service._trial_declared(PROMPTED)
    assert declared["taxonomy_vocabulary"] == "zeroshot"
    assert declared["label_namespace"] == "operator_vocabulary"
    assert declared["prompt_free"] is False


def test_an_operator_edit_beats_the_declaration_without_overwriting_it(service):
    """AI-L-03: 선언은 읽기 전용이고 수정은 장부에 쌓인다."""
    service.apply_threshold(caller=_admin(), body={
        "threshold_id": PROMPT_FREE_CONF, "value": 0.4,
        "reason": "이 현장은 장면 범주가 너무 많이 올라온다"})

    candidate = candidates_from_body([{"implementation_ref": PROMPT_FREE}],
                                     declared=service._trial_declared)[0]
    assert candidate.params["conf"] == 0.4
    assert candidate.param_basis["conf"] == BASIS_OPERATOR_EDIT
    # 선언 파일은 바뀌지 않았다.
    assert service.thresholds().get(PROMPT_FREE_CONF).value == 0.05


# ---------------------------------------------------------------------------
# 2. 시도 결과가 말하는 것 — 센다, 거르지 않는다
# ---------------------------------------------------------------------------


def _desk(service, provider):
    return TrialDesk(
        resolver=lambda ref, vocab, params: provider,
        frame_loader=lambda ref: (object(), (640, 480)),
        media_ref=lambda ref: {"path": "/api/media", "file": ref},
        floor_lookup=service._trial_floor,
        capability_kind="perception.detect_ovd")


def test_the_trial_counts_three_floor_states_and_drops_nothing(service):
    """AI-S-04: 하한에 못 미친 상자도, 하한을 말할 근거가 없는 상자도 응답에서
    빠지지 않는다. 빼면 이름 없는 관측이 운영자 화면에서 사라지고 확인·학습 후보
    경로가 함께 끊긴다."""
    provider = _Provider([
        _Result("box", 0.30),       # zeroshot box 하한 0.12 → above
        _Result("box", 0.05),       # → below
    ])
    prompted = TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",),
                              taxonomy_vocabulary="zeroshot",
                              label_namespace="operator_vocabulary")

    body = _desk(service, provider).run(candidates=[prompted],
                                        frame_refs=["f1"], actor="tester")

    assert body["runs"][0]["detection_count"] == 2      # 아무것도 빠지지 않았다
    used = body["thresholds_used"][0]
    assert used["floor_states"] == {FLOOR_ABOVE: 1, FLOOR_BELOW: 1}
    # 라벨 하나에 상태가 둘일 수 있다 — 라벨당 한 상태만 적으면 마지막 상자가
    # 앞의 것을 덮는다.
    rows = {row["label"]: row for row in used["label_floors"]}
    assert rows["box"]["state_counts"] == {FLOOR_ABOVE: 1, FLOOR_BELOW: 1}

    # 세 번째 상태는 **어휘에 속하지 않는 라벨**에서 나온다(프롬프트프리).
    free = TrialCandidate(implementation_ref=PROMPT_FREE, prompt_free=True,
                          taxonomy_vocabulary=None,
                          label_namespace="model_builtin_vocabulary")
    free_body = _desk(service, _Provider([_Result("promptfree:sea ice", 0.61)])).run(
        candidates=[free], frame_refs=["f1"], actor="tester")

    assert free_body["runs"][0]["detection_count"] == 1
    free_used = free_body["thresholds_used"][0]
    assert free_used["floor_states"] == {FLOOR_NO_BASIS: 1}
    assert free_used["label_floors"][0]["value"] is None     # 0.0 이 아니다


def test_a_prompt_free_candidate_does_not_borrow_the_vocabulary_floor(service):
    """**이 작업이 고치려던 결함이다.** prompt-free 후보의 어휘는 `None` 이므로
    `zeroshot` 의 기본 하한(0.25)이 그 라벨에 붙지 않는다."""
    provider = _Provider([_Result("promptfree:chair", 0.30)])
    candidate = TrialCandidate(implementation_ref=PROMPT_FREE, prompt_free=True,
                               taxonomy_vocabulary=None,
                               label_namespace="model_builtin_vocabulary")

    used = _desk(service, provider).run(
        candidates=[candidate], frame_refs=["f1"], actor="tester")["thresholds_used"][0]

    row = used["label_floors"][0]
    assert row["basis"] == BASIS_NO_DECLARATION
    assert row["value"] is None
    assert row["state_counts"] == {FLOOR_NO_BASIS: 1}
    assert row["threshold_id"] == "label_namespace.model_builtin_vocabulary.label_score_floor"


def test_two_thresholds_on_the_same_model_are_two_configurations(service):
    """AI-B-01: 임계값을 바꾼 것은 **다른 실행 구성**이다. 같은 구현이어도 지문이
    달라져야 옛 측정값이 새 값에 붙지 않는다."""
    low = TrialCandidate(implementation_ref=PROMPT_FREE, prompt_free=True,
                         params={"conf": 0.05})
    high = TrialCandidate(implementation_ref=PROMPT_FREE, prompt_free=True,
                          params={"conf": 0.40})

    desk = _desk(service, _Provider([_Result("promptfree:person", 0.5)]))
    body = desk.run(candidates=[low, high], frame_refs=["f1"], actor="tester")

    assert low.postprocess_ref != high.postprocess_ref
    fingerprints = {row["configuration_fingerprint"] for row in body["runs"]}
    assert len(fingerprints) == 2
    # 정답이 없으면 우열을 말하지 않는다 — 그 규칙은 그대로다.
    assert body["kind"] == "descriptive_no_ground_truth"
    assert any("더 많이 찾은 쪽이 더 나은 쪽이 아니다" in c for c in body["caveats"])


def test_the_trial_says_it_is_not_a_measurement(service):
    body = _desk(service, _Provider([_Result("box", 0.3)])).run(
        candidates=[TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",))],
        frame_refs=["f1"], actor="tester")
    assert "trial_is_not_a_measurement" in body["not_a_measurement"]


def test_a_refusal_keeps_the_same_shape(service):
    """거절도 결과다 — 빈 응답을 내면 화면이 '못 찾았다'와 '못 돌렸다'를 구분할 수
    없다. 새 칸(`thresholds_used`)도 거절 응답에 있어야 한다."""
    body = _desk(service, _Provider([])).run(candidates=[], frame_refs=["f1"],
                                             actor="tester")
    assert body["reason"] == "no_candidate_selected"
    assert body["thresholds_used"] == []


def test_the_frame_cap_is_reported_rather_than_hidden(service):
    refs = [f"f{i}" for i in range(MAX_TRIAL_FRAMES + 3)]
    body = _desk(service, _Provider([_Result("box", 0.3)])).run(
        candidates=[TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",))],
        frame_refs=refs, actor="tester")
    assert len(body["frames"]) == MAX_TRIAL_FRAMES
    assert any("상한" in c for c in body["caveats"])


# ---------------------------------------------------------------------------
# 3. 무엇을 바꿔 볼 수 있는가 (GET /api/trial)
# ---------------------------------------------------------------------------


def test_the_options_say_what_can_be_changed_and_where_each_value_came_from(service):
    options = service.trial_options()
    block = options["thresholds"]

    assert block["declaration_present"] is True
    assert block["apply_path"] == "/api/threshold"
    rows = {row["threshold_id"]: row for row in block["rows"]}

    conf = rows[PROMPT_FREE_CONF]
    assert conf["declared_value"] == 0.05
    assert conf["provenance"]["measured"] is False
    assert "accuracy" not in conf["provenance"]        # 미측정은 키가 없다
    assert conf["effective"]["basis"] == BASIS_DECLARED
    # 그 이름이 실제로 provider 에 전달되는가. 전달되지 않는 이름을 폼에 띄우면
    # 운영자가 고친 값이 조용히 버려진다.
    assert conf["reaches_provider"] is True

    floor = rows["label_namespace.model_builtin_vocabulary.label_score_floor"]
    assert floor["declared"] is False
    assert floor["effective"]["value"] is None
    assert floor["effective"]["basis"] == BASIS_NO_DECLARATION


def test_the_options_do_not_run_anything_or_change_anything(service):
    before = DEFAULT_THRESHOLDS_PATH.read_text(encoding="utf-8")
    service.trial_options()
    service.trial_options()
    assert DEFAULT_THRESHOLDS_PATH.read_text(encoding="utf-8") == before
    assert service.overlay.entries(console.KIND_THRESHOLD) == ()


# ---------------------------------------------------------------------------
# 4. 적용 — 거절해야 할 때 거절한다
# ---------------------------------------------------------------------------


def test_applying_a_threshold_does_not_touch_the_declaration_file(service):
    before = DEFAULT_THRESHOLDS_PATH.read_text(encoding="utf-8")

    body = service.apply_threshold(caller=_admin(), body={
        "threshold_id": PROMPT_FREE_CONF, "value": 0.4,
        "reason": "장면 범주가 너무 많다", "trial_fingerprint": "abc"})

    assert DEFAULT_THRESHOLDS_PATH.read_text(encoding="utf-8") == before
    # 선언과 적용값이 **다른 칸**에 있다.
    assert body["declaration"]["declared_value"] == 0.05
    assert body["effective"]["value"] == 0.4
    assert body["effective"]["basis"] == BASIS_OPERATOR_EDIT
    assert body["effective"]["declared_value"] == 0.05
    # 무엇을 보고 골랐는지가 장부에 남는다.
    entry = service.overlay.entries(console.KIND_THRESHOLD)[-1]
    assert entry.payload["trial_fingerprint"] == "abc"
    assert entry.payload["declared_value"] == 0.05
    assert entry.actor and entry.reason


def test_changing_a_threshold_changes_the_execution_configuration(service):
    """AI-B-01 을 **자료형의 성질로** 고정한다 — 선언이 아니라 지문이 달라진다."""
    body = service.apply_threshold(caller=_admin(), body={
        "threshold_id": PROMPT_FREE_CONF, "value": 0.4, "reason": "현장 판단"})

    config = body["configuration"]
    assert config["changed"] is True
    assert config["declared_postprocess_ref"] == "conf=0.05"
    assert config["postprocess_ref"] == "conf=0.4"
    assert config["fingerprint"] != config["declared_fingerprint"]
    assert body["invalidates_prior_measurements"] is True


def test_an_edit_without_an_author_or_a_reason_is_refused(service):
    with pytest.raises(console.ApiError):      # 사유 없음
        service.apply_threshold(caller=_admin(), body={
            "threshold_id": PROMPT_FREE_CONF, "value": 0.4})

    nameless = Caller(actor="", permissions=frozenset({PERM_DEPLOY_MODEL}),
                      role="admin")
    with pytest.raises(Exception):             # 작성자 없음 — 장부가 거절한다
        service.apply_threshold(caller=nameless, body={
            "threshold_id": PROMPT_FREE_CONF, "value": 0.4, "reason": "why"})


def test_a_value_outside_the_declared_bounds_and_an_unknown_id_are_refused(service):
    with pytest.raises(console.ApiError, match="value_out_of_bounds"):
        service.apply_threshold(caller=_admin(), body={
            "threshold_id": PROMPT_FREE_CONF, "value": 9.0, "reason": "오타"})

    with pytest.raises(console.ApiError, match="unknown_threshold"):
        service.apply_threshold(caller=_admin(), body={
            "threshold_id": "없는.임계값", "value": 0.4, "reason": "왜"})

    with pytest.raises(console.ApiError, match="value_not_a_number"):
        service.apply_threshold(caller=_admin(), body={
            "threshold_id": PROMPT_FREE_CONF, "value": "낮게", "reason": "왜"})


def test_a_revert_is_a_record_and_not_a_deletion(service):
    service.apply_threshold(caller=_admin(), body={
        "threshold_id": PROMPT_FREE_CONF, "value": 0.4, "reason": "올려 본다"})
    body = service.apply_threshold(caller=_admin(), body={
        "threshold_id": PROMPT_FREE_CONF, "action": "reset",
        "reason": "선언으로 돌린다"})

    assert body["action"] == "reset"
    # 선언이 다시 이긴다.
    assert body["effective"]["basis"] == BASIS_DECLARED
    assert body["effective"]["value"] == 0.05
    # 이력은 지워지지 않는다 — 올린 기록과 되돌린 기록이 모두 남는다.
    assert len(body["history"]) == 2
    assert [row["action"] for row in body["history"]] == ["set", "reset"]


def test_the_prompt_free_label_floor_can_be_declared_from_the_web(service):
    """사용자 요구의 알맹이: 아무도 선언하지 않은 하한을 **웹에서** 채운다.
    선언 파일은 `value: null` 로 남고, 채운 값은 장부에 쌓인다."""
    before = service.thresholds().resolve(
        "label_score_floor", label_namespace="model_builtin_vocabulary",
        operator_values=service._operator_thresholds())
    assert before.basis == BASIS_NO_DECLARATION

    service.apply_threshold(caller=_admin(), body={
        "threshold_id": "label_namespace.model_builtin_vocabulary.label_score_floor",
        "value": 0.45, "reason": "실측 스캔에서 장면 범주가 0.4 아래에 몰린다"})

    after = service.thresholds().resolve(
        "label_score_floor", label_namespace="model_builtin_vocabulary",
        operator_values=service._operator_thresholds())
    assert (after.basis, after.value) == (BASIS_OPERATOR_EDIT, 0.45)
    assert after.declared_value is None       # 선언은 여전히 비어 있다

    # 이제 그 라벨에 하한 상태가 생긴다 — 그 전에는 셋째 상태였다.
    assert service._trial_floor("promptfree:sea ice", 0.61, None,
                                "model_builtin_vocabulary")["state"] == FLOOR_ABOVE
    assert service._trial_floor("promptfree:sea ice", 0.20, None,
                                "model_builtin_vocabulary")["state"] == FLOOR_BELOW


def test_a_namespace_threshold_does_not_claim_one_execution_configuration(service):
    """이름 공간 하한은 구현 하나로 좁혀지지 않는다. 지문을 지어내지 않는다."""
    body = service.apply_threshold(caller=_admin(), body={
        "threshold_id": "label_namespace.model_builtin_vocabulary.label_score_floor",
        "value": 0.45, "reason": "왜"})
    assert body["configuration"]["fingerprint"] is None
    assert body["configuration"]["reason"] == "not_scoped_to_one_implementation"


# ---------------------------------------------------------------------------
# 5. 조회와 제어는 다른 계약이다 (AI-O-06)
# ---------------------------------------------------------------------------


def test_trying_and_applying_are_different_paths_with_different_permissions():
    assert "/api/threshold" in console._ROUTES_POST
    assert "/api/threshold" not in console._ROUTES_GET
    assert console._POST_PERMISSIONS["/api/threshold"] == PERM_DEPLOY_MODEL
    # 돌려 보는 권한과 적용하는 권한이 **다르다**: 시도는 추론만 돌리지만 적용은
    # 운영 중인 탐지가 무엇을 내보내는지를 바꾼다.
    assert console._POST_PERMISSIONS["/api/trial-run"] == PERM_TRAIN
    assert console._POST_PERMISSIONS["/api/trial-run"] != \
        console._POST_PERMISSIONS["/api/threshold"]
    # 읽는 이름과 쓰는 이름이 겹치지 않는다.
    assert not set(console._ROUTES_POST) & set(console._ROUTES_GET)


def test_the_shipped_declaration_stays_valid_json_after_a_full_apply_cycle(service):
    service.apply_threshold(caller=_admin(), body={
        "threshold_id": PROMPT_FREE_CONF, "value": 0.4, "reason": "왜"})
    service.apply_threshold(caller=_admin(), body={
        "threshold_id": PROMPT_FREE_CONF, "action": "reset", "reason": "되돌린다"})

    raw = json.loads(DEFAULT_THRESHOLDS_PATH.read_text(encoding="utf-8"))
    assert any(row["threshold_id"] == PROMPT_FREE_CONF for row in raw["thresholds"])
    ledger = json.loads(Path(service.overlay.path).read_text(encoding="utf-8"))
    assert [e["action"] for e in ledger["entries"]] == ["set", "reset"]


# ---------------------------------------------------------------------------
# 6. 상자 좌표 — 화면이 오버레이를 그릴 수 있어야 한다 (2026-11-04)
#
# 개수와 점수 폭만 내던 동안 운영자는 **어디를 봤는지** 볼 수 없었다. 좌표는
# 표현이 아니라 상태이므로 상태 계약에 실린다. 픽셀은 여전히 `/api/media` 다
# (AI-C-08).
# ---------------------------------------------------------------------------


def test_each_run_carries_its_boxes_per_frame(service):
    """구성마다, 프레임마다 상자 목록이 있어야 겹쳐 그릴 수 있다.

    `runs[]` 와는 **구성 지문**으로 이어진다 — 구현 이름으로 이으면 같은 구현의
    두 설정이 한 줄로 합쳐진다.
    """
    provider = _Provider([_Result("box", 0.30, box=(10.0, 20.0, 110.0, 220.0))])
    candidate = TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",),
                               taxonomy_vocabulary="zeroshot",
                               label_namespace="operator_vocabulary")

    body = _desk(service, provider).run(candidates=[candidate],
                                        frame_refs=["f1", "f2"], actor="tester")

    assert len(body["detections"]) == 1
    det = body["detections"][0]
    assert det["configuration_fingerprint"] == body["runs"][0]["configuration_fingerprint"]
    assert [f["frame_ref"] for f in det["frames"]] == ["f1", "f2"]
    box = det["frames"][0]["boxes"][0]
    assert box["box_xyxy"] == [10.0, 20.0, 110.0, 220.0]
    assert box["label"] == "box"
    # 상자는 픽셀 좌표이므로 그 좌표계의 크기가 **프레임마다** 함께 나가야 한다 —
    # 구성의 `input_profile` 은 첫 그림의 크기 하나뿐이다.
    assert [(f["width"], f["height"]) for f in body["frames"]] == [(640, 480), (640, 480)]


def test_a_box_under_the_floor_stays_in_the_payload_with_its_state(service):
    """AI-S-04: 하한에 못 미친 상자를 **빼지 않는다.** 빼면 운영자가 하한을 고치려고
    보는 바로 그 상자가 화면에서 사라진다."""
    provider = _Provider([
        _Result("box", 0.30, box=(0.0, 0.0, 10.0, 10.0)),     # zeroshot box 0.12 → above
        _Result("box", 0.05, box=(20.0, 20.0, 30.0, 30.0)),   # → below
    ])
    candidate = TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",),
                               taxonomy_vocabulary="zeroshot",
                               label_namespace="operator_vocabulary")

    boxes = _desk(service, provider).run(
        candidates=[candidate], frame_refs=["f1"],
        actor="tester")["detections"][0]["frames"][0]["boxes"]

    assert len(boxes) == 2, "두 상자 모두 남는다"
    states = {b["floor_state"] for b in boxes}
    assert states == {FLOOR_ABOVE, FLOOR_BELOW}
    low = next(b for b in boxes if b["floor_state"] == FLOOR_BELOW)
    # 상태만이 아니라 **무엇에 못 미쳤는지**도 상자가 들고 다닌다.
    assert low["floor_value"] == 0.12
    assert low["box_xyxy"] == [20.0, 20.0, 30.0, 30.0]


def test_an_undeclared_floor_is_a_third_state_on_the_box_and_not_zero(service):
    """선언이 없으면 셋째 상태다 — `below_floor` 도 0 도 아니다(AI-S-08)."""
    free = TrialCandidate(implementation_ref=PROMPT_FREE, prompt_free=True,
                          taxonomy_vocabulary=None,
                          label_namespace="model_builtin_vocabulary")

    boxes = _desk(service, _Provider([_Result("promptfree:sea ice", 0.61)])).run(
        candidates=[free], frame_refs=["f1"],
        actor="tester")["detections"][0]["frames"][0]["boxes"]

    assert [b["floor_state"] for b in boxes] == [FLOOR_NO_BASIS]
    assert boxes[0]["floor_value"] is None          # 0.0 이 아니다
    assert boxes[0]["floor_basis"] == BASIS_NO_DECLARATION
    # 웹에서 채울 수 있는 자리를 상자가 직접 가리킨다.
    assert boxes[0]["threshold_id"] == \
        "label_namespace.model_builtin_vocabulary.label_score_floor"


def test_with_no_floor_owner_the_state_is_absent_and_not_invented(service):
    """하한을 물을 주인이 없는 배치에서는 `None` 이다 — "선언이 없다" 와 **다른
    사실**이고, 한 값으로 적으면 둘이 화면에서 같은 말이 된다."""
    desk = TrialDesk(resolver=lambda ref, vocab, params: _Provider([_Result("box", 0.3)]),
                     frame_loader=lambda ref: (object(), (640, 480)),
                     media_ref=lambda ref: {"path": "/api/media", "file": ref},
                     floor_lookup=None)

    body = desk.run(candidates=[TrialCandidate(implementation_ref=PROMPTED,
                                               vocabulary=("box",))],
                    frame_refs=["f1"], actor="tester")

    box = body["detections"][0]["frames"][0]["boxes"][0]
    assert box["floor_state"] is None
    assert box["floor_basis"] is None
    assert "floor_states" not in body["thresholds_used"][0]


def test_the_floor_is_asked_once_and_the_two_views_agree(service):
    """같은 상자의 상태를 두 칸이 **따로** 유도하면 어긋날 여지가 생긴다. 셈과
    상자가 같은 판정에서 나온다는 것을 수로 고정한다."""
    provider = _Provider([_Result("box", 0.30), _Result("box", 0.05),
                          _Result("box", 0.02)])
    candidate = TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",),
                               taxonomy_vocabulary="zeroshot",
                               label_namespace="operator_vocabulary")

    body = _desk(service, provider).run(candidates=[candidate], frame_refs=["f1"],
                                        actor="tester")

    counted = body["thresholds_used"][0]["floor_states"]
    drawn: dict[str, int] = {}
    for frame in body["detections"][0]["frames"]:
        for box in frame["boxes"]:
            drawn[box["floor_state"]] = drawn.get(box["floor_state"], 0) + 1
    assert drawn == counted == {FLOOR_ABOVE: 1, FLOOR_BELOW: 2}


def test_the_boxes_are_coordinates_and_never_pixels(service):
    """AI-C-08: 상자가 생겼어도 픽셀은 이 응답으로 나가지 않는다. 그림은
    `/api/media` 가 따로 낸다."""
    body = _desk(service, _Provider([_Result("box", 0.3)])).run(
        candidates=[TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",))],
        frame_refs=["f1"], actor="tester")

    text = json.dumps(body, ensure_ascii=False)
    for forbidden in ("jpeg", "base64", "data:image", "\\xff\\xd8", "image/"):
        assert forbidden not in text
    # 꺼낼 자리는 있고 픽셀은 없다.
    assert body["frames"][0]["media"]["path"] == "/api/media"


def test_the_frame_cap_still_bounds_the_box_payload(service):
    """응답 크기의 상한은 그대로 `MAX_TRIAL_FRAMES` 다 — 상자를 더해도 프레임 수가
    상한이므로 전체 폴더를 고른 요청이 무한정 커지지 않는다."""
    refs = [f"f{i}" for i in range(MAX_TRIAL_FRAMES + 5)]
    body = _desk(service, _Provider([_Result("box", 0.3)])).run(
        candidates=[TrialCandidate(implementation_ref=PROMPTED, vocabulary=("box",))],
        frame_refs=refs, actor="tester")

    assert len(body["detections"][0]["frames"]) == MAX_TRIAL_FRAMES
    assert len(body["frames"]) == MAX_TRIAL_FRAMES


def test_a_refusal_still_carries_the_new_box_slot(service):
    """거절도 결과다 — 새 칸이 빠지면 화면이 `undefined` 를 순회한다."""
    body = _desk(service, _Provider([])).run(candidates=[], frame_refs=["f1"],
                                             actor="tester")
    assert body["detections"] == []


# ---------------------------------------------------------------------------
# 7. 화면 — 서버가 내는 모양을 그 화면이 실제로 읽는가
#
# 브라우저를 띄우지 않고 고정할 수 있는 것만 고정한다(`tests/test_fms_console_wiring.py`
# 가 같은 방식으로 이 페이지를 읽는다). 고정하는 것은 **이름의 일치**다 — 서버가
# 내는 칸 이름과 화면이 읽는 칸 이름이 어긋나면 화면은 조용히 빈칸이 된다.
# ---------------------------------------------------------------------------

FMS_PAGE = (CONSOLE_DIR / "index.html").read_text(encoding="utf-8")


def test_the_page_actually_calls_the_three_trial_paths():
    """**이 작업이 메우려던 공백이다.** 서버 쪽은 완성되어 시험까지 있었는데 그
    경로를 부르는 화면 코드가 한 줄도 없었다."""
    assert 'api("/api/trial"' in FMS_PAGE
    assert 'post("/api/trial-run"' in FMS_PAGE
    assert 'post("/api/threshold"' in FMS_PAGE


def test_the_section_is_mounted_with_its_own_body_div():
    """조각마다 제 본문 칸을 쓴다 — 한 칸을 돌려쓰면 돌아왔을 때 앞 조각이 적어 둔
    결과가 사라진다(그 주석이 `paintOps` 에 있다)."""
    assert 'key: "ops.sec.trial"' in FMS_PAGE
    assert "mount: () => Trial.open()" in FMS_PAGE
    assert '<div id="sec-trial"' in FMS_PAGE
    assert 'el("sec-trial")' in FMS_PAGE


def test_running_and_applying_are_two_buttons_behind_two_capabilities():
    """같은 단추에 두면 결과를 보려고 누른 사람이 운영 값을 바꾼다. 서버가 두
    경로에 다른 권한을 걸었으므로 화면도 둘을 따로 묻는다."""
    from accounts import PERM_DEPLOY_MODEL, PERM_TRAIN

    assert f'may("{PERM_TRAIN}")' in FMS_PAGE
    assert f'may("{PERM_DEPLOY_MODEL}")' in FMS_PAGE
    assert 'el("trRun").disabled = !may("may_request_training")' in FMS_PAGE
    # 적용 폼은 배포 권한이 없으면 아예 그려지지 않는다.
    assert 'if (!may("may_deploy_model"))' in FMS_PAGE


def test_the_three_states_of_reaches_provider_get_three_renderings():
    """`null`(모른다)을 `false`(전달되지 않는다)와 같은 글자로 그리면, 고친 값이
    조용히 버려지는 경우와 아직 알 수 없는 경우가 한 상태가 된다."""
    assert "if (value === true) return chip" in FMS_PAGE
    assert "if (value === false) return chip" in FMS_PAGE
    for key in ("tr.reaches.true", "tr.reaches.false", "tr.reaches.null"):
        assert key in FMS_PAGE
    # 사람이 읽는 글자뿐 아니라 **원래 값**도 함께 적는다.
    assert "esc(String(row.reaches_provider))" in FMS_PAGE


def test_a_declared_null_is_drawn_as_nobody_declared_it_and_not_as_zero():
    """선언값 `null` 은 "아직 아무도 선언하지 않았다" 다 — 0 도, 미달도 아니다."""
    assert "row.declared_value === null || row.declared_value === undefined" in FMS_PAGE
    assert 'chip("warn", T("tr.notDeclared"))' in FMS_PAGE


def test_the_page_draws_four_floor_states_with_shape_as_well_as_colour():
    """색만으로 가르면 색을 구분하지 못하는 눈에는 한 상태가 된다."""
    for state in ("above_floor", "below_floor", "no_floor_declared", "floor_unknown"):
        assert f".trshot .bx.{state}" in FMS_PAGE
    assert "stroke-dasharray" in FMS_PAGE
    # 넷째는 **하한을 물을 주인이 없다**이고 선언이 없는 것과 다르다. 그 문구는
    # 상태 토큰이 `null` 일 때 고르는 자리에 있다(`floorText`).
    assert '"tr.floor." + state : "tr.floor.unknown"' in FMS_PAGE


def test_the_overlay_divides_pixel_boxes_by_the_frame_size_the_server_sent():
    """서버가 주는 좌표는 픽셀이다. 프레임 크기로 나누지 않고 그리면 상자가 그림
    왼쪽 위 한 구석에 몰린다 — 크기를 모르는 프레임은 그리지 않고 그 사실을 적는다.
    """
    assert "const w = frame.width, h = frame.height;" in FMS_PAGE
    assert "x1 / w * 1000" in FMS_PAGE
    assert "if (!w || !h){" in FMS_PAGE


def test_the_result_shows_that_a_trial_is_not_a_measurement():
    assert "out.not_a_measurement" in FMS_PAGE
    assert "out.caveats" in FMS_PAGE
    assert 'T("tr.notMeasurement")' in FMS_PAGE


def test_no_winner_is_named_when_there_is_no_ground_truth():
    """`scored` 가 비어 있으면 설명이고 우열이 아니다. 그 사실을 표 **위에** 적는다."""
    assert "out.scored && Object.keys(out.scored).length" in FMS_PAGE
    assert 'T("tr.descriptive")' in FMS_PAGE


def test_each_unavailable_candidate_renders_its_own_reason():
    """전부 "불가" 로 뭉개면 "가중치가 없다" 와 "세우면 네트워크로 나간다" 가 같은
    말이 된다 — 서버가 후보마다 자기 사유를 들려 보내는 이유다."""
    assert "out.unavailable.map(u =>" in FMS_PAGE
    assert 'pick("tr.reason.", u.reason)' in FMS_PAGE
    assert "esc(u.reason)" in FMS_PAGE


def test_a_server_refusal_surfaces_the_token_and_not_only_a_sentence():
    """사람이 읽는 문장만 내면 그 문장을 검색해도 코드에서 찾을 수 없다."""
    assert 'T("tr.serverRefused")' in FMS_PAGE
    assert "<code>${esc(token)}</code>" in FMS_PAGE
    assert 'refusal("tr.err.", err.message)' in FMS_PAGE
    assert 'refusal("tr.reason.", out.reason)' in FMS_PAGE


def test_the_apply_form_carries_the_trial_it_was_looking_at():
    """어느 시도를 보고 골랐는지가 장부에 남아야 기준을 낮춰 통과시킨 것과 넘은
    것이 뒤에서 구분된다(AI-L-06)."""
    assert "body.trial_fingerprint = fp;" in FMS_PAGE
    assert 'T("tr.whichRun")' in FMS_PAGE


def test_the_page_does_not_build_a_media_url_into_the_state_contract():
    """픽셀은 `/api/media` 가 낸다(AI-C-08). 화면은 서버가 준 `media` 칸으로 그
    주소를 만들고, 상자 응답에서 그림을 기대하지 않는다."""
    assert "function mediaSrc(media){" in FMS_PAGE
    assert 'm.path || "/api/media"' in FMS_PAGE


def test_every_string_the_trial_section_asks_for_exists_in_both_languages():
    """한쪽에만 있는 키는 화면에서 빈칸이나 영어 잔재로 나타난다. 페이지가 실제로
    묻는 키만 골라 두 표에서 찾는다."""
    import re

    from strings import STRINGS

    asked = set(re.findall(r'T\("(tr\.[a-zA-Z0-9_.]+)"\)', FMS_PAGE))
    # 접두어로 만드는 키(`pick("tr.basis.", ...)`)는 토큰이 데이터에서 오므로
    # 서버가 실제로 내는 토큰으로 조립해 확인한다.
    asked |= {"tr.floor." + s for s in (FLOOR_ABOVE, FLOOR_BELOW, FLOOR_NO_BASIS)}
    asked.add("tr.floor.unknown")
    asked |= {"tr.basis." + b for b in (BASIS_DECLARED, BASIS_OPERATOR_EDIT,
                                        BASIS_NO_DECLARATION, BASIS_TRIAL_REQUEST)}
    assert asked, "페이지가 이 구역의 문구를 하나도 묻지 않는다"
    for locale in ("en", "ko"):
        missing = sorted(k for k in asked if k not in STRINGS[locale])
        assert missing == [], f"{locale}: {missing}"


def test_the_refusal_tokens_the_server_can_send_all_have_text():
    """사유 토큰에 글이 없으면 `pick` 이 토큰을 그대로 보여 준다 — 틀리지는 않지만
    비개발자가 읽을 수 없다. 서버가 낼 수 있는 토큰을 여기서 묶어 둔다."""
    from strings import STRINGS

    import trial as trial_desk

    tokens = [trial_desk.REASON_NO_FRAMES, trial_desk.REASON_NO_CANDIDATE,
              trial_desk.REASON_UNKNOWN_FRAME, trial_desk.REASON_DETECTOR_UNAVAILABLE,
              trial_desk.REASON_NO_FRAME_ASSETS,
              trial_desk.REASON_WOULD_REACH_NETWORK]
    for token in tokens:
        for locale in ("en", "ko"):
            assert f"tr.reason.{token}" in STRINGS[locale], token
    for token in ("reason_required", "value_required", "value_not_a_number",
                  "value_out_of_bounds", "unknown_threshold", "no_overlay_ledger",
                  "threshold_id_required", "unknown_action"):
        for locale in ("en", "ko"):
            assert f"tr.err.{token}" in STRINGS[locale], token


def test_a_trial_where_no_candidate_stood_up_says_so_and_keeps_each_reason(service):
    """실제 배치에서 본 경우다 — 프롬프트형 두 후보가 모두 자산 때문에 거절됐다.
    그때 응답이 "하나만 돌린 것은 비교가 아니다" 라고 말하면 운영자는 자기가 하나만
    골랐다고 읽는다. 사유는 후보마다 남아 있어야 한다."""
    from mission_runtime.runtime.model_trial import REASON_NO_RUN

    desk = TrialDesk(
        # 해소하는 쪽이 사유를 돌려준다. 두 사유가 **서로 다르다**.
        resolver=lambda ref, vocab, params: (
            "would_reach_outbound_network:mobileclip" if ref == PROMPTED
            else "detector_unavailable"),
        frame_loader=lambda ref: (object(), (640, 480)),
        media_ref=lambda ref: {"path": "/api/media", "file": ref},
        floor_lookup=service._trial_floor)

    body = desk.run(candidates=[TrialCandidate(implementation_ref=PROMPTED,
                                               vocabulary=("box",)),
                                TrialCandidate(implementation_ref=PROMPT_FREE,
                                               prompt_free=True)],
                    frame_refs=["f1"], actor="tester")

    assert body["reason"] == REASON_NO_RUN
    assert body["runs"] == [] and body["detections"] == []
    reasons = {u["implementation_ref"]: u["reason"] for u in body["unavailable"]}
    assert reasons[PROMPTED].startswith("would_reach_outbound_network")
    assert reasons[PROMPT_FREE] == "detector_unavailable"


def test_the_page_still_shows_each_reason_when_the_trial_itself_was_refused():
    """거절 사유만 내고 후보별 사유를 숨기면, 아무것도 돌지 않은 이유가 바로 거기
    적혀 있는데 화면에는 거절 한 줄만 남는다."""
    assert "function unavailableView(){" in FMS_PAGE
    assert 'refusal("tr.reason.", out.reason)}${unavailableView()}' in FMS_PAGE
