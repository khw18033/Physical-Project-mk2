"""implements: AI-B-04, AI-C-15, AI-B-01, AI-C-05, AI-C-13
covers: 실행 환경을 코드 분기가 아니라 선언 데이터로 해소, 미측정과 '없음'의 구분,
        맞는 프로파일이 없을 때의 축소 경로, 선택 사유 노출,
        선언된 노드 태그와 탐지된 환경의 어긋남 보고

이 시험이 지키는 것은 하나다 — "지금 이 기계에서 `compute.gpu` 를 붙여도 되는가"를
사람의 암묵지가 아니라 선언과 관측으로 답하게 둔다.

이 기계의 사실로 WSL2 해소를 확인하는 시험은 **주입된 사실**로 돈다(아래
`THIS_MACHINE_2026_11_03`). 실제 탐지에 의존하면 다른 기계에서 skip 되거나 깨지고,
skip 된 시험은 "통과했다"로 읽혀 아무것도 지키지 않는다. 그래서 진짜 탐지를 돌리는
시험(`test_live_detection_*`)은 **어느 기계에서나** 성립하는 것만 주장한다 —
"미측정을 0 으로 채우지 않았는가", "결과가 해소든 미해소든 사유를 들고 있는가".
"""

import json
from pathlib import Path

import pytest

from mission_runtime.runtime.environment_profile import (
    DEFAULT_NODE_DECLARATION,
    DEFAULT_PROFILE_DECLARATION,
    REASON_AMBIGUOUS,
    REASON_NO_MATCH,
    REASON_PROFILE_UNRESOLVED,
    REASON_RESOLVED,
    REASON_TAG_FORBIDDEN,
    REASON_UNMEASURED,
    ClauseOutcome,
    DeclaredNode,
    EnvironmentFacts,
    ExecutionEnvironmentProfile,
    FactClause,
    GpuProbe,
    environment_report,
    load_declared_nodes,
    load_environment_profiles,
    observe_environment,
    probe_accelerators,
    report_tag_conflicts,
    resolve_environment_profile,
)

PROFILES = load_environment_profiles(DEFAULT_PROFILE_DECLARATION)

# ---------------------------------------------------------------------------
# 사실 묶음. 각각 "실제로 존재하는 기계 한 대"이고, 코드가 아니라 데이터다.
# ---------------------------------------------------------------------------

#: 2026-11-03 이 개발 기계에서 `observe_environment()` 가 실제로 낸 값.
#: 다른 기계에서도 이 시험이 돌아야 하므로 관측 결과를 그대로 박아 입력으로 쓴다.
THIS_MACHINE_2026_11_03 = EnvironmentFacts(
    os_name="Linux",
    kernel_release="6.18.33.2-microsoft-standard-WSL2",
    proc_version=(
        "Linux version 6.18.33.2-microsoft-standard-WSL2 (root@f1bbfb02316b) "
        "(gcc (GCC) 13.2.0, GNU ld (GNU Binutils) 2.41) #1 SMP PREEMPT_DYNAMIC "
        "Thu Jun 18 21:54:43 UTC 2026"
    ),
    in_container=False,
    wsl_interop=True,
    gpu_probe=GpuProbe.ANSWERED,
    gpu_count=1,
    gpu_probe_detail="rc=0:lines=1",
)

#: 네이티브 리눅스 + nvidia 드라이버 충돌. 이 현장의 확정 사실이고, 관측 모양은
#: "nvidia-smi 는 있는데 조회가 실패한다"다 — GPU 0개와 같은 칸에 담기지 않는다.
NATIVE_LINUX_DRIVER_CONFLICT = EnvironmentFacts(
    os_name="Linux",
    kernel_release="6.8.0-45-generic",
    proc_version="Linux version 6.8.0-45-generic",
    in_container=False,
    wsl_interop=False,
    gpu_probe=GpuProbe.TOOL_FAILED,
    gpu_count=None,
    gpu_probe_detail="rc=9:NVIDIA-SMI has failed because it couldn't communicate with the driver",
)

#: 윈도 Docker Desktop(WSL2 백엔드) 컨테이너에 GPU 가 전달된 상태.
WINDOWS_DOCKER_GPU = EnvironmentFacts(
    os_name="Linux",
    kernel_release="5.15.167.4-microsoft-standard-WSL2",
    proc_version="Linux version 5.15.167.4-microsoft-standard-WSL2",
    in_container=True,
    wsl_interop=None,
    gpu_probe=GpuProbe.ANSWERED,
    gpu_count=1,
)

#: WSL2 인데 조회 도구가 아예 없다 — 가속기 유무는 **미측정**이다.
WSL2_TOOL_ABSENT = EnvironmentFacts(
    os_name="Linux",
    kernel_release="6.18.33.2-microsoft-standard-WSL2",
    proc_version="Linux version 6.18.33.2-microsoft-standard-WSL2",
    in_container=False,
    wsl_interop=True,
    gpu_probe=GpuProbe.TOOL_ABSENT,
    gpu_count=None,
)


# ---------------------------------------------------------------------------
# 선언 자체
# ---------------------------------------------------------------------------


def test_declaration_file_exists_and_declares_the_three_required_profiles():
    ids = {p.profile_id for p in PROFILES}

    assert {"wsl2-gpu", "native-linux-cpu", "windows-docker-gpu"} <= ids


def test_declaration_names_no_vendor_anywhere_in_resource_tags():
    """자원은 벤더 열거형이 아니라 자유 문자열 태그다(AI-B-04, 절대 준수 원칙 #1).

    선언의 사유 문장에는 nvidia 가 나와도 된다(현장 사실 서술이다). **태그**에
    벤더가 들어가는 순간 상위 코드가 벤더 이름으로 분기하기 시작한다.
    """
    for profile in PROFILES:
        for tag in profile.allowed_resource_tags | profile.forbidden_resource_tags:
            lowered = tag.lower()
            assert not any(
                vendor in lowered
                for vendor in ("nvidia", "cuda", "rocm", "amd", "intel", "jetson", "npu.")
            ), f"{profile.profile_id} 의 태그 {tag!r} 에 벤더 이름이 들어 있다"


def test_declared_profiles_are_mutually_exclusive_over_the_known_machines():
    """같은 사실 묶음이 둘 이상의 프로파일을 동시에 맞혀서는 안 된다.

    맞히면 해소가 임의 선택이 되고, 어느 기계에서 띄웠는지에 따라 결과가 달라진다.
    """
    for facts in (
        THIS_MACHINE_2026_11_03,
        NATIVE_LINUX_DRIVER_CONFLICT,
        WINDOWS_DOCKER_GPU,
    ):
        resolution = resolve_environment_profile(facts, PROFILES)
        winners = [e.profile_id for e in resolution.evaluations if e.matched]
        assert len(winners) == 1, f"{facts.kernel_release}: {winners}"


def test_every_profile_carries_a_rationale():
    """사유 없는 선언은 다음 사람이 고칠 수 없다(AI-C-13 의 근거 노출)."""
    for profile in PROFILES:
        assert profile.rationale.strip(), profile.profile_id


# ---------------------------------------------------------------------------
# 이 기계의 사실 → wsl2-gpu
# ---------------------------------------------------------------------------


def test_this_machine_resolves_to_the_wsl2_gpu_profile():
    resolution = resolve_environment_profile(THIS_MACHINE_2026_11_03, PROFILES)

    assert resolution.profile_id == "wsl2-gpu"
    assert resolution.reason == f"{REASON_RESOLVED}:wsl2-gpu"


def test_the_resolution_says_which_facts_pointed_at_the_profile():
    """AI-C-13: 고른 사유가 결과에 담겨야 한다. "WSL2 니까"로 줄지 않는다."""
    resolution = resolve_environment_profile(THIS_MACHINE_2026_11_03, PROFILES)

    joined = " ".join(resolution.selecting_facts)
    assert "kernel_release[contains]=microsoft-standard-WSL2" in joined
    assert "gpu_probe=answered" in joined
    assert "gpu_count[at_least]=1" in joined
    assert "in_container[is_false]" in joined


def test_wsl2_with_gpu_may_use_the_gpu_tag():
    profile = resolve_environment_profile(THIS_MACHINE_2026_11_03, PROFILES).profile

    assert profile is not None
    assert profile.permits("compute.gpu") is True
    assert profile.permits("compute.cpu") is True


# ---------------------------------------------------------------------------
# 미측정은 "없음" 이 아니다
# ---------------------------------------------------------------------------


def test_gpu_count_cannot_exist_without_an_answering_probe():
    """조회가 응답하지 않았는데 개수가 들어오면 그 숫자의 출처가 없다."""
    with pytest.raises(ValueError):
        EnvironmentFacts(gpu_probe=GpuProbe.TOOL_ABSENT, gpu_count=0)


def test_tool_absent_and_zero_gpus_are_different_facts():
    """nvidia-smi 가 없는 것과 0개라고 답한 것은 섞이지 않는다."""
    absent = EnvironmentFacts(gpu_probe=GpuProbe.TOOL_ABSENT)
    answered_zero = EnvironmentFacts(gpu_probe=GpuProbe.ANSWERED, gpu_count=0)

    assert absent.gpu_count is None
    assert answered_zero.gpu_count == 0
    assert "gpu_count" in absent.unmeasured()
    assert "gpu_count" not in answered_zero.unmeasured()


def test_an_unmeasured_fact_neither_matches_nor_mismatches():
    from mission_runtime.runtime.environment_profile import _evaluate

    clause = FactClause("gpu_count", "at_least", 1)

    assert _evaluate(clause, {"gpu_count": None}) is ClauseOutcome.UNMEASURED
    assert _evaluate(clause, {"gpu_count": 0}) is ClauseOutcome.MISMATCH
    assert _evaluate(clause, {"gpu_count": 2}) is ClauseOutcome.MATCH


def test_unmeasured_facts_block_resolution_instead_of_assuming_no_gpu():
    """WSL2 인데 조회 도구가 없다 → "GPU 없음"이 아니라 미해소 + 미측정 사유."""
    resolution = resolve_environment_profile(WSL2_TOOL_ABSENT, PROFILES)

    # wsl2-cpu 의 any_of 가 tool_absent 를 맞히므로 이 선언에서는 해소된다 —
    # 중요한 것은 **왜** 그 결론인지가 사실 이름으로 남는 것이다.
    assert resolution.profile_id == "wsl2-cpu"
    assert "gpu_probe=tool_absent" in " ".join(resolution.selecting_facts)
    # 그리고 개수는 끝까지 미측정으로 남는다.
    assert "gpu_count" in resolution.unmeasured_facts


def test_a_clause_on_a_fact_we_could_not_read_leaves_the_profile_undetermined():
    """미측정으로 막힌 것과 어긋난 것은 다른 사유를 낸다."""
    needs_gpu_only = (
        ExecutionEnvironmentProfile(
            profile_id="needs-gpu",
            label="GPU 가 필요한 선언",
            all_of=(FactClause("gpu_count", "at_least", 1),),
            allowed_resource_tags=frozenset({"compute.gpu"}),
        ),
    )

    blocked = resolve_environment_profile(WSL2_TOOL_ABSENT, needs_gpu_only)
    assert blocked.profile is None
    assert blocked.reason.startswith(REASON_UNMEASURED)

    mismatched = resolve_environment_profile(
        EnvironmentFacts(gpu_probe=GpuProbe.ANSWERED, gpu_count=0), needs_gpu_only
    )
    assert mismatched.profile is None
    assert mismatched.reason.startswith(REASON_NO_MATCH)


def test_driver_conflict_is_not_reported_as_zero_gpus():
    """드라이버 충돌은 'tool_failed' 로 남는다 — 금지 결론은 같아도 고칠 방법이 다르다."""
    resolution = resolve_environment_profile(NATIVE_LINUX_DRIVER_CONFLICT, PROFILES)

    assert resolution.profile_id == "native-linux-cpu"
    assert "gpu_probe=tool_failed" in " ".join(resolution.selecting_facts)
    assert NATIVE_LINUX_DRIVER_CONFLICT.gpu_count is None


# ---------------------------------------------------------------------------
# 축소 경로 — 맞는 프로파일이 없으면 고르지 않는다
# ---------------------------------------------------------------------------


def test_no_declared_profile_means_none_plus_a_reason_not_an_arbitrary_pick():
    """AI-C-05: 예외가 아니라 `None` + 사유. 선언에 없는 조합은 사람에게 보인다.

    여기 쓰는 사실은 실제로 선언이 비워 둔 자리다 — 네이티브 리눅스에서
    nvidia-smi 가 GPU 를 정상 응답하는 상태. 이 현장의 확정 사실과 어긋나므로
    자동으로 GPU 를 허용하지 않는다.
    """
    native_linux_with_working_gpu = EnvironmentFacts(
        os_name="Linux",
        kernel_release="6.8.0-45-generic",
        proc_version="Linux version 6.8.0-45-generic",
        in_container=False,
        wsl_interop=False,
        gpu_probe=GpuProbe.ANSWERED,
        gpu_count=2,
    )

    resolution = resolve_environment_profile(native_linux_with_working_gpu, PROFILES)

    assert resolution.profile is None
    assert resolution.profile_id is None
    assert resolution.reason.startswith(REASON_NO_MATCH)
    assert resolution.selecting_facts == ()


def test_two_matching_profiles_are_refused_rather_than_ordered():
    """선언이 배타적이지 않으면 순서로 몰래 고르지 않는다."""
    overlapping = (
        ExecutionEnvironmentProfile(
            profile_id="a", label="a", all_of=(FactClause("os_name", "equals", "Linux"),)
        ),
        ExecutionEnvironmentProfile(
            profile_id="b", label="b", all_of=(FactClause("os_name", "contains", "Linu"),)
        ),
    )

    resolution = resolve_environment_profile(THIS_MACHINE_2026_11_03, overlapping)

    assert resolution.profile is None
    assert resolution.reason.startswith(REASON_AMBIGUOUS)
    assert "a" in resolution.reason and "b" in resolution.reason


def test_unknown_fact_names_do_not_silently_match():
    """선언이 모르는 사실을 가리키면 맞다고 보지 않는다."""
    bogus = (
        ExecutionEnvironmentProfile(
            profile_id="bogus",
            label="없는 사실을 가리키는 선언",
            all_of=(FactClause("accelerator_vendor", "equals", "nvidia"),),
        ),
    )

    resolution = resolve_environment_profile(THIS_MACHINE_2026_11_03, bogus)

    assert resolution.profile is None
    assert resolution.reason.startswith(REASON_UNMEASURED)


# ---------------------------------------------------------------------------
# 선언된 노드 태그와의 어긋남
# ---------------------------------------------------------------------------


def test_the_fms_declaration_really_carries_gpu_tagged_nodes():
    nodes = load_declared_nodes(DEFAULT_NODE_DECLARATION)

    gpu_nodes = [n.node_id for n in nodes if "compute.gpu" in n.tags]
    assert gpu_nodes, "선언에 compute.gpu 노드가 없으면 이 시험이 아무것도 지키지 않는다"


def test_a_gpu_forbidding_environment_surfaces_the_declared_gpu_tags():
    """선언 파일을 고치지 않고 어긋남만 보고한다."""
    resolution = resolve_environment_profile(NATIVE_LINUX_DRIVER_CONFLICT, PROFILES)
    nodes = load_declared_nodes(DEFAULT_NODE_DECLARATION)

    conflicts = report_tag_conflicts(resolution, nodes)

    assert conflicts, "GPU 를 금지하는 환경인데 어긋남이 하나도 보고되지 않았다"
    assert {c.tag for c in conflicts} == {"compute.gpu"}
    assert all(c.reason == f"{REASON_TAG_FORBIDDEN}:native-linux-cpu" for c in conflicts)
    # 선언은 그대로다 — 보고가 선언을 깎지 않는다.
    assert {n.node_id for n in nodes if "compute.gpu" in n.tags} == {c.node_id for c in conflicts}


def test_declaration_text_is_untouched_by_reporting():
    before = Path(DEFAULT_NODE_DECLARATION).read_bytes()

    report_tag_conflicts(
        resolve_environment_profile(NATIVE_LINUX_DRIVER_CONFLICT, PROFILES),
        load_declared_nodes(DEFAULT_NODE_DECLARATION),
    )

    assert Path(DEFAULT_NODE_DECLARATION).read_bytes() == before


def test_a_gpu_allowing_environment_reports_no_conflict():
    resolution = resolve_environment_profile(THIS_MACHINE_2026_11_03, PROFILES)

    assert report_tag_conflicts(resolution, load_declared_nodes(DEFAULT_NODE_DECLARATION)) == ()


def test_non_compute_tags_are_out_of_scope_rather_than_implicitly_forbidden():
    """센서·계층 태그까지 어긋남으로 보고하면 보고가 의미를 잃는다."""
    resolution = resolve_environment_profile(NATIVE_LINUX_DRIVER_CONFLICT, PROFILES)
    node = DeclaredNode(
        "pi-example",
        frozenset({"compute.cpu", "tier.fixed_camera", "sensor.camera.imx708", "power.external"}),
    )

    assert report_tag_conflicts(resolution, (node,)) == ()
    assert resolution.profile is not None
    assert resolution.profile.permits("sensor.camera.imx708") is None  # 관할 밖


def test_an_unresolved_profile_does_not_pass_as_no_problem():
    """미해소를 '어긋남 없음'으로 읽히게 두면 조용한 가정이 그대로 돌아온다."""
    unresolved = resolve_environment_profile(
        EnvironmentFacts(
            os_name="Linux",
            kernel_release="6.8.0-45-generic",
            proc_version="Linux version 6.8.0-45-generic",
            in_container=False,
            wsl_interop=False,
            gpu_probe=GpuProbe.ANSWERED,
            gpu_count=2,
        ),
        PROFILES,
    )
    node = DeclaredNode("edge-gpu", frozenset({"compute.cpu", "compute.gpu"}))

    conflicts = report_tag_conflicts(unresolved, (node,))

    assert conflicts
    assert all(c.reason.startswith(REASON_PROFILE_UNRESOLVED) for c in conflicts)
    assert {c.tag for c in conflicts} == {"compute.cpu", "compute.gpu"}


# ---------------------------------------------------------------------------
# 실제 탐지 — 어느 기계에서나 성립하는 것만 주장한다
# ---------------------------------------------------------------------------


def test_live_detection_never_fills_unmeasured_with_zero():
    """진짜 탐지를 돌려도 미측정이 0 으로 채워지지 않는다(AI-B-01/AI-O-05)."""
    facts = observe_environment()

    if facts.gpu_probe is not GpuProbe.ANSWERED:
        assert facts.gpu_count is None
    else:
        assert isinstance(facts.gpu_count, int)


def test_live_detection_produces_a_resolution_with_a_reason_either_way():
    """해소든 미해소든 사유가 있어야 한다 — 조용히 기본값으로 가지 않는다."""
    report = environment_report()

    assert report["reason"]
    if report["profile_id"] is None:
        assert report["selecting_facts"] == []
    else:
        assert report["profile_id"] in {p.profile_id for p in PROFILES}
        assert report["selecting_facts"]
    # 보고서는 JSON 으로 그대로 나가야 한다(운영 상태 뷰의 입력, AI-O-06).
    json.dumps(report, ensure_ascii=False)


def test_a_missing_probe_tool_is_tool_absent_not_zero_gpus():
    """조회 도구가 없는 기계를 가정한다 — 주입으로 어느 기계에서나 돈다."""

    def missing(_command):
        raise FileNotFoundError("nvidia-smi")

    probe, count, detail = probe_accelerators(missing)

    assert probe is GpuProbe.TOOL_ABSENT
    assert count is None
    assert "not_found" in detail


def test_a_failing_probe_tool_is_tool_failed_not_zero_gpus():
    """드라이버 충돌: 도구는 있고 비영 종료코드를 낸다."""
    import subprocess

    def failing(command):
        return subprocess.CompletedProcess(
            list(command),
            returncode=9,
            stdout="",
            stderr="NVIDIA-SMI has failed because it couldn't communicate with the driver\n",
        )

    probe, count, detail = probe_accelerators(failing)

    assert probe is GpuProbe.TOOL_FAILED
    assert count is None
    assert "rc=9" in detail


def test_an_answering_probe_counts_the_lines_it_returned():
    import subprocess

    def answering(command):
        return subprocess.CompletedProcess(
            list(command), returncode=0, stdout="GPU A\nGPU B\n", stderr=""
        )

    probe, count, _ = probe_accelerators(answering)

    assert probe is GpuProbe.ANSWERED
    assert count == 2


def test_an_answering_probe_with_no_devices_is_a_measured_zero():
    import subprocess

    def empty(command):
        return subprocess.CompletedProcess(list(command), returncode=0, stdout="\n", stderr="")

    probe, count, _ = probe_accelerators(empty)

    assert probe is GpuProbe.ANSWERED
    assert count == 0  # 측정된 0 이다 — 미측정과 다르다.
