"""지금 돌고 있는 실행 환경을 **관측된 사실**로 모아 선언된 프로파일 하나로 해소한다.

implements: AI-B-04, AI-C-15, AI-B-01, AI-C-05, AI-C-13

이 모듈이 지우려는 상태는 이것이다 — 같은 저장소·같은 노드 선언을 들고도
"이 기계에서 `compute.gpu` 를 붙여도 되는가"는 사람만 알고 코드에는 적혀 있지
않았다. 현장의 확정 사실은 다음과 같다.

* 네이티브 리눅스에서 nvidia 드라이버가 충돌해 GPU 를 쓸 수 없다.
* GPU 가 필요하면 윈도에서 Docker 또는 WSL 로 가상환경을 만들어 쓴다.

이 차이를 코드 분기로 적으면 절대 준수 원칙 #1·#3 을 그대로 어긴다("GPU/NPU
벤더·실행 런타임을 핵심 코드에 하드코딩하지 않는다", "도메인·환경 이름으로 분기문을
추가하지 않는다"). 그래서 환경 차이는 전부 `config/deployment_profiles*.json` 의
**데이터**이고, 이 모듈은 사실을 모아 선언을 평가하는 일만 한다. 새 환경은 프로파일
한 건을 더 적어 추가하며 이 파일을 고치지 않는다(AI-B-09 와 같은 확장 방식).

설계에서 양보하지 않는 세 가지:

1. **미측정은 "없음"이 아니다.** AI-B-01 은 "미측정 항목은 구분해야 한다"고 적고,
   AI-O-05 는 "측정값이 없는 상태는 0 이나 미달과 구분되는 별도 상태로 표현해야
   한다"고 적는다. nvidia-smi 가 아예 없는 것(`GpuProbe.TOOL_ABSENT`), 있는데
   답하지 못하는 것(`TOOL_FAILED` — 드라이버 충돌의 관측 모양이 바로 이것이다),
   답해서 0개라고 말한 것(`ANSWERED` + `gpu_count == 0`)은 서로 다른 세 사실이다.
   그래서 `gpu_count` 는 `ANSWERED` 일 때만 숫자가 들어오고 나머지 경우에는
   `None` 으로 남는다 — 0 으로 채우면 "왜 GPU 를 안 쓰느냐"를 끝까지 추적할 수
   없다.
2. **맞는 프로파일이 없으면 고르지 않는다.** `resolve_environment_profile` 은
   예외가 아니라 `profile_id=None` + 사유를 내고, 호출자는 이 None 을 정상적인
   축소 경로로 처리한다(AI-C-05 — `SelectionResult(provider=None, reason=...)`
   와 같은 규약). 선언에 없는 조합이 조용히 기본값으로 흘러가지 않는다.
3. **고른 사유가 결과에 남는다.** AI-C-13 은 선택 로직을 교체 가능하게 두되 그
   근거를 노출하라고 요구한다. 어떤 사실이 그 프로파일을 가리켰는지,
   떨어진 프로파일은 어느 절에서 어긋났는지, 어느 절이 미측정으로 막혔는지가
   `ProfileResolution` 에 전부 들어간다.

사유 토큰은 `SelectionResult.reason` 과 같은 규약을 쓴다 — `':'` 앞이 토큰,
뒤가 데이터다.

선언 태그와의 어긋남(`report_tag_conflicts`)은 **선언 파일을 고치지 않는다**.
노드 선언은 그 노드가 원래 무엇을 들고 있는지를 말하는 정본이고, 지금 이 기계에서
그 태그를 쓸 수 없다는 것은 다른 사실이다. 둘을 한 칸에 합치면 기계를 옮겼을 때
원래 선언이 무엇이었는지 복원할 수 없다(AI-L-03 이 운영자 수정에 대해 요구하는
구분과 같은 이유다).
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

#: 선언 파일의 기본 자리. 운영 배치는 같은 형식의 `deployment_profiles.json` 을
#: 옆에 두고 경로로 넘긴다 — 예시 파일을 고쳐 쓰게 만들지 않는다.
DEFAULT_PROFILE_DECLARATION = (
    Path(__file__).resolve().parents[1] / "config" / "deployment_profiles.example.json"
)

#: 노드 태그 어긋남을 확인할 때 읽는 배치 선언의 기본 자리.
DEFAULT_NODE_DECLARATION = (
    Path(__file__).resolve().parents[1] / "config" / "status_ui.fms.example.json"
)

WSL_KERNEL_MARKER = "microsoft-standard-WSL2"


# ============================================================================
# 관측된 사실
# ============================================================================


class GpuProbe(str, Enum):
    """가속기 조회가 **무엇을 말했는가**. 세 값은 서로 대체되지 않는다.

    `TOOL_ABSENT` 는 "GPU 가 없다"가 아니라 "조회 도구가 없어 모른다"다. 이
    둘을 같은 값으로 쓰면 드라이버를 깔면 되는 기계와 가속기가 아예 없는 기계가
    한 칸에 들어간다.
    """

    #: 조회 도구(nvidia-smi 등)가 없다 — 가속기 유무는 **미측정**이다.
    TOOL_ABSENT = "tool_absent"
    #: 도구는 있는데 조회가 실패했다 — 드라이버 충돌의 관측 모양.
    TOOL_FAILED = "tool_failed"
    #: 조회가 응답했다. 이때만 `gpu_count` 가 숫자를 가진다.
    ANSWERED = "answered"


@dataclass(frozen=True)
class EnvironmentFacts:
    """지금 이 실행 환경에 대해 **관측된** 것만 담는다.

    모든 필드가 `None` 을 가질 수 있고, `None` 은 "그 값이 거짓/0" 이 아니라
    "읽지 못했다"다. 어휘와 의미는 선언 파일의 `fact_vocabulary` 가 같은 이름으로
    적는다 — 사실 이름을 늘리려면 양쪽을 함께 늘린다.
    """

    os_name: str | None = None
    kernel_release: str | None = None
    proc_version: str | None = None
    #: 컨테이너 안인가. 판단 근거를 하나도 읽지 못하면 `None`.
    in_container: bool | None = None
    #: WSL 상호운용 표식이 있는가. 커널 문자열의 보조 근거.
    wsl_interop: bool | None = None
    gpu_probe: GpuProbe | None = None
    #: `gpu_probe is ANSWERED` 일 때만 숫자. 그 밖에는 `None` — 0 으로 채우지 않는다.
    gpu_count: int | None = None
    #: 사람이 읽는 메모(도구 경로·실패 메시지). 판정에 쓰지 않는다.
    gpu_probe_detail: str | None = None

    def __post_init__(self) -> None:
        # 이 불변조건이 이 모듈의 핵심 주장이다. 조회가 응답하지 않았는데 개수가
        # 들어와 있으면 그 숫자의 출처를 아무도 설명할 수 없다.
        if self.gpu_probe is not GpuProbe.ANSWERED and self.gpu_count is not None:
            raise ValueError(
                "gpu_count 는 gpu_probe=answered 일 때만 값을 가진다 — "
                f"probe={self.gpu_probe!r} 인데 count={self.gpu_count!r}"
            )

    def as_mapping(self) -> dict[str, Any]:
        """선언 절이 `fact` 이름으로 찾아 쓰는 평면 사전."""
        return {
            "os_name": self.os_name,
            "kernel_release": self.kernel_release,
            "proc_version": self.proc_version,
            "in_container": self.in_container,
            "wsl_interop": self.wsl_interop,
            "gpu_probe": self.gpu_probe.value if self.gpu_probe is not None else None,
            "gpu_count": self.gpu_count,
        }

    def unmeasured(self) -> tuple[str, ...]:
        """읽지 못한 사실의 이름. 운영 상태로 그대로 노출할 값이다(AI-O-05)."""
        return tuple(name for name, value in self.as_mapping().items() if value is None)


# ============================================================================
# 사실 수집 — 바깥 세계와 닿는 유일한 자리
# ============================================================================

#: 조회 도구를 부르는 경계. 시험은 이 자리에 사실을 주입해 어느 기계에서나 돈다.
CommandRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _run(command: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(  # noqa: S603 - 고정된 조회 명령만 들어온다
        list(command), capture_output=True, text=True, timeout=10, check=False
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _detect_container(read_text: Callable[[Path], str | None]) -> tuple[bool | None, str | None]:
    """컨테이너 안인가. 근거를 하나도 읽지 못하면 `None`(미측정)이다."""
    for marker in (Path("/.dockerenv"), Path("/run/.containerenv")):
        if marker.exists():
            return True, f"marker:{marker}"

    cgroup = read_text(Path("/proc/1/cgroup"))
    if cgroup is None:
        # cgroup 도 못 읽고 표식도 없으면 "컨테이너가 아니다"라고 말할 근거가
        # 없다. 리눅스가 아닌 기계에서 그렇다.
        return None, "no_evidence"
    if re.search(r"/(docker|containerd|kubepods|libpod|lxc)[-./]", cgroup):
        return True, "cgroup"
    return False, "cgroup"


def probe_accelerators(runner: CommandRunner | None = None) -> tuple[GpuProbe, int | None, str]:
    """가속기 조회. 도구 부재·조회 실패·응답을 **서로 다른 결과로** 낸다.

    벤더 이름이 이 함수 밖으로 나가지 않는 것이 요점이다 — 결과는
    `compute.gpu` 태그를 허용해도 되는지에 대한 사실이고, 그 사실을 어떤 도구로
    얻었는지는 여기 안에 숨는다(AI-C-04 의 provider 경계와 같은 이유).
    """
    runner = runner or _run
    command = ("nvidia-smi", "--query-gpu=name", "--format=csv,noheader")
    try:
        completed = runner(command)
    except FileNotFoundError as exc:
        return GpuProbe.TOOL_ABSENT, None, f"not_found:{exc}"
    except (OSError, subprocess.SubprocessError) as exc:
        # 도구는 있었는데 부르는 데 실패했다 — 미측정이 아니라 '실패'다.
        return GpuProbe.TOOL_FAILED, None, f"invoke_failed:{type(exc).__name__}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return GpuProbe.TOOL_FAILED, None, f"rc={completed.returncode}:{detail[0] if detail else ''}"

    lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    return GpuProbe.ANSWERED, len(lines), f"rc=0:lines={len(lines)}"


def observe_environment(
    *,
    runner: CommandRunner | None = None,
    read_text: Callable[[Path], str | None] | None = None,
    environ: Mapping[str, str] | None = None,
) -> EnvironmentFacts:
    """이 기계의 사실을 모은다. 읽히지 않는 것은 `None` 으로 남긴다.

    주입 가능한 세 경계(`runner`/`read_text`/`environ`)는 시험용 구멍이 아니라
    이 모듈이 바깥 세계와 닿는 전부다 — 그 밖의 어떤 코드도 커널 문자열이나
    조회 도구를 직접 읽지 않는다.
    """
    read_text = read_text or _read_text
    environ = environ if environ is not None else os.environ

    kernel_release = platform.release() or None
    proc_version = read_text(Path("/proc/version"))
    in_container, _container_evidence = _detect_container(read_text)

    wsl_interop: bool | None
    if environ.get("WSL_INTEROP"):
        wsl_interop = True
    elif Path("/proc/sys/fs/binfmt_misc").is_dir():
        wsl_interop = Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()
    else:
        wsl_interop = None  # 확인할 자리 자체가 없으면 미측정이다.

    probe, count, detail = probe_accelerators(runner)

    return EnvironmentFacts(
        os_name=platform.system() or None,
        kernel_release=kernel_release,
        proc_version=proc_version.strip() if proc_version else None,
        in_container=in_container,
        wsl_interop=wsl_interop,
        gpu_probe=probe,
        gpu_count=count,
        gpu_probe_detail=detail,
    )


# ============================================================================
# 선언 — 데이터로 적힌 실행 환경 프로파일
# ============================================================================


@dataclass(frozen=True)
class FactClause:
    """사실 하나에 대한 절. 형식은 선언 파일의 `clause_forms` 가 적는다."""

    fact: str
    form: str
    value: Any

    def describe(self) -> str:
        if self.form in ("is_true", "is_false"):
            return f"{self.fact}[{self.form}]"
        return f"{self.fact}{'' if self.form == 'equals' else f'[{self.form}]'}={self.value}"


class ClauseOutcome(str, Enum):
    """절 하나의 결과. 세 값이고, 둘로 줄이면 이 모듈의 의미가 사라진다."""

    MATCH = "match"
    MISMATCH = "mismatch"
    #: 사실을 읽지 못해 **판단할 수 없다**. 불일치가 아니다.
    UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class ExecutionEnvironmentProfile:
    """선언된 실행 환경 하나 — 조건과 자원 태그 정책과 사유.

    `allowed_resource_tags` 에 없고 `forbidden_resource_tags` 에도 없는 태그는
    **이 프로파일의 관할 밖**이다(센서·급전·계층 태그가 전부 그렇다). 명시되지
    않은 태그를 암묵적으로 금지하면 모든 노드가 통째로 어긋남으로 보고된다.
    """

    profile_id: str
    label: str
    all_of: tuple[FactClause, ...] = ()
    any_of: tuple[FactClause, ...] = ()
    allowed_resource_tags: frozenset[str] = field(default_factory=frozenset)
    forbidden_resource_tags: frozenset[str] = field(default_factory=frozenset)
    rationale: str = ""

    def permits(self, tag: str) -> bool | None:
        """이 태그를 써도 되는가. 관할 밖이면 `None`."""
        if tag in self.forbidden_resource_tags:
            return False
        if tag in self.allowed_resource_tags:
            return True
        return None


_CLAUSE_FORMS = ("equals", "in", "contains", "not_contains", "at_least", "at_most", "is_true", "is_false")


def _parse_clause(raw: Mapping[str, Any]) -> FactClause:
    fact = raw.get("fact")
    if not isinstance(fact, str) or not fact:
        raise ValueError(f"절에 'fact' 이름이 없다: {raw!r}")
    forms = [key for key in raw if key in _CLAUSE_FORMS]
    if len(forms) != 1:
        raise ValueError(
            f"절 {fact!r} 은 {_CLAUSE_FORMS} 중 정확히 하나를 가져야 한다 — 받은 것: {forms}"
        )
    return FactClause(fact=fact, form=forms[0], value=raw[forms[0]])


def load_environment_profiles(
    source: Path | str | Mapping[str, Any] = DEFAULT_PROFILE_DECLARATION,
) -> tuple[ExecutionEnvironmentProfile, ...]:
    """선언 파일(또는 이미 읽은 사전)을 프로파일 튜플로 바꾼다."""
    if isinstance(source, Mapping):
        document: Mapping[str, Any] = source
    else:
        document = json.loads(Path(source).read_text(encoding="utf-8"))

    profiles: list[ExecutionEnvironmentProfile] = []
    for raw in document.get("profiles", ()):
        match = raw.get("match", {})
        profiles.append(
            ExecutionEnvironmentProfile(
                profile_id=raw["profile_id"],
                label=raw.get("label", raw["profile_id"]),
                all_of=tuple(_parse_clause(c) for c in match.get("all_of", ())),
                any_of=tuple(_parse_clause(c) for c in match.get("any_of", ())),
                allowed_resource_tags=frozenset(raw.get("allowed_resource_tags", ())),
                forbidden_resource_tags=frozenset(raw.get("forbidden_resource_tags", ())),
                rationale=raw.get("rationale", ""),
            )
        )
    if not profiles:
        raise ValueError("선언에 프로파일이 하나도 없다")
    return tuple(profiles)


# ============================================================================
# 해소 — 사실로 프로파일 하나를 고르거나, 고르지 않고 사유를 남긴다
# ============================================================================


def _evaluate(clause: FactClause, facts: Mapping[str, Any]) -> ClauseOutcome:
    if clause.fact not in facts:
        # 선언이 모르는 사실 이름을 가리켰다. 맞다고 보지 않는다 — 어휘를 늘리면
        # `EnvironmentFacts` 와 `fact_vocabulary` 를 함께 늘리라는 신호다.
        return ClauseOutcome.UNMEASURED
    value = facts[clause.fact]
    if value is None:
        # 핵심 규칙: 읽지 못한 사실은 어떤 절도 만족시키지 않고, 어긋나지도 않는다.
        return ClauseOutcome.UNMEASURED

    form, expected = clause.form, clause.value
    try:
        if form == "equals":
            ok = value == expected
        elif form == "in":
            ok = value in expected
        elif form == "contains":
            ok = str(expected) in str(value)
        elif form == "not_contains":
            ok = str(expected) not in str(value)
        elif form == "at_least":
            ok = float(value) >= float(expected)
        elif form == "at_most":
            ok = float(value) <= float(expected)
        elif form == "is_true":
            ok = bool(value) is bool(expected)
        elif form == "is_false":
            ok = bool(value) is not bool(expected)
        else:  # pragma: no cover - _parse_clause 가 이미 막는다
            raise ValueError(f"알 수 없는 절 형식 {form!r}")
    except (TypeError, ValueError):
        # 형식이 맞지 않는 사실은 "어긋났다"가 아니라 비교하지 못한 것이다.
        return ClauseOutcome.UNMEASURED
    return ClauseOutcome.MATCH if ok else ClauseOutcome.MISMATCH


@dataclass(frozen=True)
class ProfileEvaluation:
    """프로파일 하나가 어떻게 됐는지 — 사유를 절 단위로 보존한다."""

    profile_id: str
    matched: bool
    #: 맞은 절(그 프로파일을 가리킨 사실들).
    matched_clauses: tuple[str, ...] = ()
    #: 어긋난 절.
    mismatched_clauses: tuple[str, ...] = ()
    #: 읽지 못해 판단하지 못한 절. 비어 있지 않으면 이 프로파일은 '탈락'이 아니라 '미정'이다.
    unmeasured_clauses: tuple[str, ...] = ()

    @property
    def undetermined(self) -> bool:
        return not self.matched and bool(self.unmeasured_clauses)


@dataclass(frozen=True)
class ProfileResolution:
    """해소 결과. `profile` 이 `None` 인 것은 오류가 아니라 정상 경로다(AI-C-05)."""

    profile: ExecutionEnvironmentProfile | None
    #: `':'` 앞이 토큰, 뒤가 데이터(`SelectionResult.reason` 과 같은 규약).
    reason: str
    #: 왜 그 프로파일인가 / 왜 아무것도 아닌가 — 절 단위 근거(AI-C-13).
    evaluations: tuple[ProfileEvaluation, ...] = ()
    #: 읽지 못한 사실 전체. 0 으로 채우지 않았다는 증거로 그대로 노출한다.
    unmeasured_facts: tuple[str, ...] = ()

    @property
    def profile_id(self) -> str | None:
        return self.profile.profile_id if self.profile else None

    @property
    def selecting_facts(self) -> tuple[str, ...]:
        """고른 프로파일을 가리킨 절들. 고르지 못했으면 빈 튜플."""
        if self.profile is None:
            return ()
        chosen = next(e for e in self.evaluations if e.profile_id == self.profile.profile_id)
        return chosen.matched_clauses


REASON_RESOLVED = "environment_profile_resolved"
REASON_NO_MATCH = "no_profile_matched"
REASON_UNMEASURED = "unmeasured_facts_block_resolution"
REASON_AMBIGUOUS = "ambiguous_declaration"


def resolve_environment_profile(
    facts: EnvironmentFacts,
    profiles: Sequence[ExecutionEnvironmentProfile] | None = None,
) -> ProfileResolution:
    """관측된 사실로 선언된 프로파일 하나를 고른다.

    고르지 못하는 세 경우를 서로 다른 사유로 구분한다.

    * `REASON_UNMEASURED` — 맞을 수도 있었는데 사실을 읽지 못해 막혔다.
      고칠 방법은 "조회를 가능하게 하는 것"이다.
    * `REASON_NO_MATCH` — 사실은 다 읽었고 어느 선언과도 어긋난다.
      고칠 방법은 "프로파일을 하나 더 선언하는 것"이다.
    * `REASON_AMBIGUOUS` — 둘 이상이 동시에 맞는다. 선언 오류이므로 순서로
      임의 선택하지 않는다. 고칠 방법은 "선언을 배타적으로 만드는 것"이다.
    """
    profiles = tuple(profiles) if profiles is not None else load_environment_profiles()
    mapping = facts.as_mapping()

    evaluations: list[ProfileEvaluation] = []
    for profile in profiles:
        matched: list[str] = []
        mismatched: list[str] = []
        unmeasured: list[str] = []

        for clause in profile.all_of:
            outcome = _evaluate(clause, mapping)
            {ClauseOutcome.MATCH: matched,
             ClauseOutcome.MISMATCH: mismatched,
             ClauseOutcome.UNMEASURED: unmeasured}[outcome].append(clause.describe())
        all_of_ok = not mismatched and not unmeasured

        any_of_ok = True
        if profile.any_of:
            outcomes = [(c, _evaluate(c, mapping)) for c in profile.any_of]
            hits = [c.describe() for c, o in outcomes if o is ClauseOutcome.MATCH]
            if hits:
                # 맞은 절이 있으면 나머지가 미측정이어도 묶음은 성립한다 —
                # any_of 는 "하나면 된다"는 뜻이고, 그 하나가 사유에 남는다.
                matched.extend(hits)
            else:
                any_of_ok = False
                blocked = [c.describe() for c, o in outcomes if o is ClauseOutcome.UNMEASURED]
                mismatched.extend(c.describe() for c, o in outcomes if o is ClauseOutcome.MISMATCH)
                unmeasured.extend(blocked)

        evaluations.append(
            ProfileEvaluation(
                profile_id=profile.profile_id,
                matched=all_of_ok and any_of_ok,
                matched_clauses=tuple(matched),
                mismatched_clauses=tuple(mismatched),
                unmeasured_clauses=tuple(unmeasured),
            )
        )

    winners = [p for p, e in zip(profiles, evaluations) if e.matched]
    unmeasured_facts = facts.unmeasured()

    if len(winners) == 1:
        return ProfileResolution(
            profile=winners[0],
            reason=f"{REASON_RESOLVED}:{winners[0].profile_id}",
            evaluations=tuple(evaluations),
            unmeasured_facts=unmeasured_facts,
        )
    if len(winners) > 1:
        return ProfileResolution(
            profile=None,
            reason=f"{REASON_AMBIGUOUS}:{','.join(p.profile_id for p in winners)}",
            evaluations=tuple(evaluations),
            unmeasured_facts=unmeasured_facts,
        )

    blocked = [e for e in evaluations if e.undetermined]
    if blocked:
        detail = ",".join(f"{e.profile_id}({'|'.join(e.unmeasured_clauses)})" for e in blocked)
        return ProfileResolution(
            profile=None,
            reason=f"{REASON_UNMEASURED}:{detail}",
            evaluations=tuple(evaluations),
            unmeasured_facts=unmeasured_facts,
        )
    return ProfileResolution(
        profile=None,
        reason=f"{REASON_NO_MATCH}:{','.join(e.profile_id for e in evaluations)}",
        evaluations=tuple(evaluations),
        unmeasured_facts=unmeasured_facts,
    )


# ============================================================================
# 선언 태그와의 어긋남 — 보고만 하고 선언을 고치지 않는다
# ============================================================================


@dataclass(frozen=True)
class DeclaredNode:
    """배치 선언에 적힌 노드 하나(필요한 만큼만 읽는다)."""

    node_id: str
    tags: frozenset[str] = field(default_factory=frozenset)
    label: str = ""


@dataclass(frozen=True)
class TagConflict:
    """선언된 노드 태그 하나가 지금 이 환경에서 쓸 수 없다는 사실."""

    node_id: str
    tag: str
    profile_id: str
    reason: str

    def describe(self) -> str:
        return f"{self.node_id}: {self.tag} — {self.reason}"


def load_declared_nodes(
    source: Path | str | Mapping[str, Any] = DEFAULT_NODE_DECLARATION,
) -> tuple[DeclaredNode, ...]:
    """배치 선언의 `nodes` 를 읽는다. 태그 어휘는 그대로 둔다."""
    if isinstance(source, Mapping):
        document: Mapping[str, Any] = source
    else:
        document = json.loads(Path(source).read_text(encoding="utf-8"))
    return tuple(
        DeclaredNode(
            node_id=raw["node_id"],
            tags=frozenset(raw.get("tags", ())),
            label=raw.get("label", ""),
        )
        for raw in document.get("nodes", ())
    )


REASON_TAG_FORBIDDEN = "forbidden_in_environment_profile"
REASON_PROFILE_UNRESOLVED = "environment_profile_unresolved"


def report_tag_conflicts(
    resolution: ProfileResolution,
    nodes: Sequence[DeclaredNode],
) -> tuple[TagConflict, ...]:
    """선언 태그와 탐지된 환경이 어긋나는 자리를 **보고한다**.

    고치지 않는 이유는 머리말에 적은 그대로다 — 노드 선언은 그 노드가 원래
    무엇을 들고 있는지에 대한 정본이고, "지금 이 기계에서는 쓸 수 없다"는 다른
    사실이다. 둘을 합치면 같은 선언을 다른 기계로 옮겼을 때 원래 무엇이었는지
    복원할 수 없다.

    프로파일이 해소되지 않은 경우에는 어긋남을 하나도 못 찾았다고 말하지 않고
    노드마다 "판단하지 못했다"를 낸다 — 미해소를 "문제 없음"으로 읽히게 두면
    이 모듈이 막으려는 조용한 가정이 그대로 돌아온다.
    """
    if resolution.profile is None:
        return tuple(
            TagConflict(
                node_id=node.node_id,
                tag=tag,
                profile_id="",
                reason=f"{REASON_PROFILE_UNRESOLVED}:{resolution.reason}",
            )
            for node in nodes
            for tag in sorted(node.tags)
            if tag.startswith("compute.")
        )

    profile = resolution.profile
    return tuple(
        TagConflict(
            node_id=node.node_id,
            tag=tag,
            profile_id=profile.profile_id,
            reason=f"{REASON_TAG_FORBIDDEN}:{profile.profile_id}",
        )
        for node in nodes
        for tag in sorted(node.tags)
        if profile.permits(tag) is False
    )


def environment_report(
    *,
    profile_source: Path | str | Mapping[str, Any] = DEFAULT_PROFILE_DECLARATION,
    node_source: Path | str | Mapping[str, Any] = DEFAULT_NODE_DECLARATION,
    facts: EnvironmentFacts | None = None,
) -> dict[str, Any]:
    """운영 상태로 그대로 낼 수 있는 한 장 — 사실·해소·사유·어긋남.

    판정을 새로 하지 않고 위 함수들의 결과를 모으기만 한다(FMS 콘솔이 지키는
    규칙과 같다 — 같은 판정을 두 곳에서 하면 두 화면이 다른 답을 말한다).
    """
    facts = facts if facts is not None else observe_environment()
    resolution = resolve_environment_profile(facts, load_environment_profiles(profile_source))
    conflicts = report_tag_conflicts(resolution, load_declared_nodes(node_source))
    return {
        "facts": facts.as_mapping(),
        "unmeasured_facts": list(resolution.unmeasured_facts),
        "profile_id": resolution.profile_id,
        "reason": resolution.reason,
        "selecting_facts": list(resolution.selecting_facts),
        "tag_conflicts": [
            {"node_id": c.node_id, "tag": c.tag, "reason": c.reason} for c in conflicts
        ],
    }


if __name__ == "__main__":  # pragma: no cover - 운영자가 손으로 확인하는 경로
    print(json.dumps(environment_report(), ensure_ascii=False, indent=2))
