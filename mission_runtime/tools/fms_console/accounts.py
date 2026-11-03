"""Who is at the console, and what they are allowed to do.

implements: AI-C-19 (판단·권한·책임 경계), AI-B-02 (자격증명을 이미지·저장소에 넣지 않는다)
관련: AI-O-06 (조회와 제어의 분리), AI-L-03 (사용자 확인의 작성자 추적), AI-L-06
tests: tests/test_fms_accounts.py

## 두 가지 자세 — 예시와 실제

이 콘솔은 지금 **예시 자세**로 돌아간다. 계정 파일이 없으면 사용자는 비밀번호 없이
역할을 골라 들어오고(`assume_role`), 그 역할의 능력으로 화면 기능이 갈린다. 요구된
것이 "권한별로 웹 기능 접근이 갈리는 것" 이고, 데모에서 비밀번호를 관리하게 만들면
보여 주려는 것과 무관한 마찰만 생기기 때문이다.

계정 파일이 생기는 순간 자세가 바뀐다 — 역할을 고르는 길은 닫히고 비밀번호 로그인만
남는다. 두 자세를 섞지 않는 이유는 하나다: **예시 자세를 실제 배포에서 모르고 쓰는
것**이 가장 위험한 경우이고, 계정을 하나 만드는 것이 그 전환의 명시적 신호가 된다.

예시 자세는 응답(`auth_mode`)과 기동 배너에 **그대로 적힌다.** 화면 문구로 훈계하지는
않는다 — 운영자가 읽어야 하는 것은 "이 작업에는 권한이 필요하다" 이고, 어느 자세로
돌고 있는지는 그 콘솔을 세운 사람이 알아야 하는 것이다.

## 왜 이 파일이 생겼는가

지금까지 콘솔의 권한은 질의 인자 하나였다 — `?role=admin`. 그것은 **보기 편하게 하는
필터**였고, 실제로 아무것도 막지 않았다. 조회만 하던 동안에는 그 정직한 한계를 적어
두는 것으로 충분했다.

그 전제가 바뀌었다. 콘솔은 이제 물리 명령을 발급하고, 융합 결과를 사람이 고쳐 학습
후보를 만들고, 모델 버전을 기기에 배정하고, 장치를 함대에 들인다. 그중 어느 것도 "URL
에 role=admin 을 적은 사람" 이 해도 되는 일이 아니다. 그래서 **계정**이 필요하다.

## 이것이 전체 시스템의 권한 경계는 아니다

운영 전체의 authoritative 인가는 백엔드가 역할·범위로 판정한다(BE-Q-04). 이 모듈은
**이 콘솔이 자기 문을 잠그는 것**이고, 둘은 같은 것이 아니다. 백엔드 판정을 여기서
복제하면 같은 사실에 주인이 둘이 되므로, 이 모듈은 백엔드가 내준 판정을 소비할 수
있게 열어 두되(`external_subject`) 스스로 그것을 재판정하지 않는다.

이 구분을 화면 문구로 쓰지는 않는다. 사용자가 읽어야 하는 것은 "이 작업에는 권한이
필요하다" 이고, 어느 파트가 최종 판정자인지는 운영자의 관심사가 아니다.

## 권한은 역할 **이름**이 아니라 능력 목록이다

`role == "admin"` 으로 분기하면 역할이 하나 늘 때마다 분기가 늘고, 그것은 이 저장소가
장치·도메인에서 이미 거부한 모양이다(절대 준수 원칙 #3). 그래서 검사하는 쪽은 항상
**능력**(`may_issue_command` …)을 묻고, 역할은 그 능력들의 **이름 붙은 묶음**으로
데이터에 있다. 새 역할은 표에 한 줄이고 코드 변경이 아니다.

## 비밀은 저장소에 들어가지 않는다

계정 파일은 공개 트리 밖(`local/`)에 있고, 기본 계정도 기본 비밀번호도 **출하하지
않는다**(AI-B-02: 자격증명을 이미지에 포함하지 않는다). 첫 계정은 운영자가
`python -m tools.fms_console.accounts add` 로 만든다. 파일이 없으면 "아직 계정이 없다"
는 정상 상태이고, 그 상태에서 콘솔은 **읽기만** 허용한다 — 잠긴 문을 열어 두는 것보다
들어갈 수 없다고 말하는 쪽이 옳다.

비밀번호는 PBKDF2-HMAC-SHA256 으로 늘려 저장하고 사용자마다 난수 salt 를 쓴다. 평문도
되돌릴 수 있는 형태도 남기지 않으며, 비교는 `hmac.compare_digest` 로 해서 실패 지점이
시간으로 새지 않게 한다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

# --- 능력 어휘 ---------------------------------------------------------------
# 검사하는 쪽은 역할 이름이 아니라 이 이름들을 묻는다. 새 능력은 여기 한 줄이고,
# 어느 역할이 그것을 가질지는 아래 표가 정한다.

PERM_VIEW = "may_view"                      # 상태 조회. 로그인한 모든 계정의 기본
PERM_SEE_INTERNALS = "may_see_internals"    # 계약 원문·provider 내부·원인 추적
PERM_COMMAND = "may_issue_command"          # 물리 명령 발급 요청(AI-C-19: 발급은 백엔드)
PERM_CORRECT = "may_correct_evidence"       # 융합 결과·단서 정정 → 학습 후보(AI-L-03)
PERM_EDIT_PLACEMENT = "may_edit_placement"  # 고정 장치 자리·공간 실측값
PERM_LABEL = "may_label_ground_truth"       # GT 생성·확정
PERM_CALIBRATE = "may_calibrate"            # 카메라 정보 입력·보정 실행
PERM_ONBOARD = "may_onboard_device"         # 새 장치를 함대에 들이기
PERM_TRAIN = "may_request_training"         # 학습 실행 요청
PERM_DEPLOY_MODEL = "may_deploy_model"      # 기기별 모델 배정·교체(AI-L-10)
PERM_MANAGE_ACCOUNTS = "may_manage_accounts"  # 계정 생성·권한 변경

ALL_PERMISSIONS: tuple[str, ...] = (
    PERM_VIEW, PERM_SEE_INTERNALS, PERM_COMMAND, PERM_CORRECT, PERM_EDIT_PLACEMENT,
    PERM_LABEL, PERM_CALIBRATE, PERM_ONBOARD, PERM_TRAIN, PERM_DEPLOY_MODEL,
    PERM_MANAGE_ACCOUNTS,
)

#: 역할 = 능력들의 이름 붙은 묶음. **데이터다.**
#:
#: `operator` 와 `labeler` 가 따로 있는 이유: GT 를 만드는 사람과 로봇을 움직이는
#: 사람은 보통 다른 사람이고, 라벨 작업자에게 물리 명령 권한을 같이 주면 그 권한이
#: 필요 없는 사람 수만큼 사고 표면이 넓어진다.
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "viewer": (PERM_VIEW,),
    "labeler": (PERM_VIEW, PERM_LABEL, PERM_CORRECT),
    "operator": (PERM_VIEW, PERM_COMMAND, PERM_EDIT_PLACEMENT, PERM_CALIBRATE),
    "developer": (PERM_VIEW, PERM_SEE_INTERNALS, PERM_LABEL, PERM_CORRECT,
                  PERM_CALIBRATE, PERM_TRAIN),
    "admin": ALL_PERMISSIONS,
}

#: 계정이 하나도 없을 때 열어 두는 능력. 조회만이고, 그 사실을 화면이 적는다.
#: 설치 직후 아무것도 보이지 않으면 설치가 실패한 것처럼 보이고, 반대로 명령까지
#: 열어 두면 잠기지 않은 문이 된다 — 그 사이를 조회로 잡는다.
NO_ACCOUNT_PERMISSIONS: tuple[str, ...] = (PERM_VIEW,)

#: 기본 자리. 공개 트리 밖이고 `.gitignore` 가 제외한다.
DEFAULT_ACCOUNTS_PATH = Path("../local/fms_accounts/accounts.json")

ACCOUNTS_FORMAT_VERSION = "1"

#: 지금 어느 자세로 돌고 있는가. 응답에 실어 보내 뷰어가 추측하지 않게 한다.
AUTH_MODE_DEMO_ROLES = "demo_roles"       # 계정 없음 — 예시 계정을 골라 들어온다
AUTH_MODE_ACCOUNTS = "accounts"           # 계정 있음 — 비밀번호 로그인

#: 예시 자세에서 쓰는 작성자 접두. 장부를 나중에 읽을 때 이 기록이 예시 자세에서
#: 만들어졌다는 것을 알 수 있어야 한다 — 실제 사람이 한 것과 섞이면 안 된다.
DEMO_ACTOR_PREFIX = "demo:"

DENY_DEMO_DISABLED = "demo_roles_disabled_accounts_exist"

#: 예시 자세에서 관리자 화면이 다룰 수 있도록 **메모리에만** 두는 계정들.
#: 왜 필요한가: 예시 자세에는 계정 파일이 없으므로 "계정별로 권한을 부여한다" 를 보일
#: 대상이 없다. 그래서 몇 개를 메모리에 두되 **디스크에 쓰지 않고**, 이들로 로그인할
#: 수도 없다(예시 자세의 로그인은 역할 선택이다). 재시작하면 선언된 상태로 돌아간다.
#: 관리자 하나와 사용자 넷. 사용자는 **조회만** 들고 시작하고 나머지는 관리자가
#: 하나씩 부여한다 — 그것이 "권한을 준다" 가 실제로 무엇인지 보이는 유일한 모양이다.
#: 역할 이름으로 미리 묶어 두면 "저 사람은 운영자니까 당연히 된다" 가 되고, 누가
#: 무엇을 언제 열어 줬는지가 장부에 남지 않는다.
EXAMPLE_ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("admin", "admin", "관리자"),
    ("user1", "viewer", "사용자 1"),
    ("user2", "viewer", "사용자 2"),
    ("user3", "viewer", "사용자 3"),
    ("user4", "viewer", "사용자 4"),
)

#: 계정 변경의 종류. 사유 어휘이고 화면 문구가 아니다.
CHANGE_GRANTED = "granted"
CHANGE_REVOKED = "revoked"
CHANGE_ROLE_SET = "role_set"
CHANGE_NOT_NEEDED = "no_change_needed"
DENY_ROLE_PERMISSION_NOT_REVOCABLE = "permission_comes_from_role"  # + ":<role>"
DENY_LAST_ADMIN = "would_leave_no_account_able_to_manage_accounts"

#: PBKDF2 반복 수. 느려지는 것이 목적이다 — 올릴 때는 기존 계정의 저장값에 적힌
#: 반복 수를 그대로 쓰고(아래 `iterations` 칸) 새 계정만 올라간다.
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32

#: 세션 수명. 짧게 두고 활동으로 갱신한다.
SESSION_TTL_S = 8 * 3600.0

#: 거절 사유. 통제 어휘이고 화면 문구가 아니다.
DENY_NO_SESSION = "no_session"
DENY_SESSION_EXPIRED = "session_expired"
DENY_UNKNOWN_SESSION = "unknown_session"
DENY_MISSING_PERMISSION = "missing_permission"      # + ":<permission>"
DENY_ACCOUNT_DISABLED = "account_disabled"
DENY_NO_ACCOUNTS_CONFIGURED = "no_accounts_configured"
AUTH_BAD_CREDENTIALS = "bad_credentials"            # 사용자 없음과 비밀번호 불일치를 구분하지 않는다


class AccountError(ValueError):
    """계정 저장소를 읽을 수 없거나 선언이 잘못됐다."""


def _hash_password(password: str, *, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations).hex()


@dataclass(frozen=True)
class Account:
    """계정 1개. **비밀번호 평문은 어디에도 없다.**"""

    account_id: str
    role: str
    password_hash: str
    salt_hex: str
    iterations: int = PBKDF2_ITERATIONS
    display_name: str = ""
    #: 역할 묶음에 더해 개별로 준 능력. 묶음을 늘리지 않고 한 사람만 열 때 쓴다.
    extra_permissions: tuple[str, ...] = ()
    enabled: bool = True
    created_at: float | None = None
    #: 백엔드가 내준 주체 식별자. 우리가 재판정하지 않고 그대로 들고 다닌다.
    external_subject: str | None = None

    def __post_init__(self) -> None:
        if not self.account_id:
            raise AccountError("account_id must not be empty")
        if self.role not in ROLE_PERMISSIONS:
            raise AccountError(f"unknown role: {self.role!r}")
        unknown = set(self.extra_permissions) - set(ALL_PERMISSIONS)
        if unknown:
            # 모르는 능력을 조용히 받으면 검사하는 쪽이 그것을 영원히 묻지 않는다.
            raise AccountError(f"unknown permissions: {sorted(unknown)}")

    @property
    def permissions(self) -> frozenset[str]:
        return frozenset(ROLE_PERMISSIONS[self.role]) | frozenset(self.extra_permissions)

    def verify(self, password: str) -> bool:
        candidate = _hash_password(password, salt=bytes.fromhex(self.salt_hex),
                                   iterations=self.iterations)
        # 같은 길이 비교를 상수 시간으로 — 실패 지점이 시간으로 새지 않게.
        return hmac.compare_digest(candidate, self.password_hash)

    def as_stored(self) -> dict:
        body: dict[str, Any] = {
            "account_id": self.account_id, "role": self.role,
            "password_hash": self.password_hash, "salt_hex": self.salt_hex,
            "iterations": self.iterations, "enabled": self.enabled,
        }
        for name in ("display_name", "created_at", "external_subject"):
            value = getattr(self, name)
            if value:
                body[name] = value
        if self.extra_permissions:
            body["extra_permissions"] = list(self.extra_permissions)
        return body

    def as_public(self) -> dict:
        """화면에 보내도 되는 모양. 해시도 salt 도 나가지 않는다."""
        return {
            "account_id": self.account_id,
            "display_name": self.display_name or self.account_id,
            "role": self.role,
            "enabled": self.enabled,
            "permissions": sorted(self.permissions),
        }

    @classmethod
    def create(cls, account_id: str, password: str, role: str, **kwargs) -> "Account":
        if len(password) < 10:
            # 길이만으로 좋은 비밀번호가 되지는 않지만, 짧은 것은 확실히 나쁘다.
            raise AccountError("password must be at least 10 characters")
        salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
        return cls(
            account_id=account_id, role=role,
            password_hash=_hash_password(password, salt=salt,
                                         iterations=PBKDF2_ITERATIONS),
            salt_hex=salt.hex(), iterations=PBKDF2_ITERATIONS,
            created_at=time.time(), **kwargs)


@dataclass(frozen=True)
class Session:
    """로그인 1회. 토큰은 저장소에 남지만 화면 밖으로는 한 번만 나간다."""

    token: str
    account_id: str
    issued_at: float
    expires_at: float

    def expired(self, *, now: float) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True)
class Decision:
    """권한 검사 1회의 결과. 거절이면 **무엇이 없어서**인지 말한다."""

    allowed: bool
    reason: str
    account: Account | None = None
    #: 계정이 하나도 없는 설치, 즉 예시 자세인가.
    unconfigured: bool = False
    #: 예시 자세에서 고른 예시 계정. 실제 계정으로 들어왔으면 None 이다.
    demo_account: Account | None = None

    @property
    def actor(self) -> str:
        """장부에 적힐 작성자.

        예시 자세에서는 `demo:<account_id>` 로 적는다 — 접두 없이 적으면 나중에
        장부를 읽을 때 실제 사람이 한 것과 구분되지 않는다(AI-L-03: 사용자 확인
        결과는 작성자와 함께 보존된다).
        """
        if self.account is not None:
            return self.account.account_id
        if self.demo_account is not None:
            return f"{DEMO_ACTOR_PREFIX}{self.demo_account.account_id}"
        return "unauthenticated"


@dataclass(frozen=True)
class Caller:
    """요청 하나를 낸 **인증된 주체**. 서비스 계층이 들고 다니는 것이 이것이다.

    역할 문자열(`role: str`)을 넘기던 자리를 이것으로 바꿨다. 문자열을 넘기면 받는
    쪽이 `role == "admin"` 으로 분기하게 되고, 그러면 역할이 하나 늘 때마다 분기가
    늘고 장부에 적히는 작성자도 사람이 아니라 역할 이름이 된다 — "admin 이 고쳤다"
    는 기록으로는 누가 고쳤는지 알 수 없다(AI-L-03).

    그래서 이 객체는 **할 수 있는 것의 목록**과 **누구인지**를 같이 들고 있고, 받는
    쪽은 항상 능력을 묻는다.
    """

    actor: str
    permissions: frozenset[str] = frozenset()
    unconfigured: bool = False
    display_name: str = ""
    role: str = ""

    def may(self, permission: str) -> bool:
        if permission not in ALL_PERMISSIONS:
            # 오타난 능력 이름이 조용히 False 가 되면 그 문은 영원히 닫힌 채 잊힌다.
            raise AccountError(f"unknown permission: {permission!r}")
        return permission in self.permissions

    def as_dict(self) -> dict:
        return {
            "actor": self.actor,
            "display_name": self.display_name or self.actor,
            "role": self.role,
            "permissions": sorted(self.permissions),
            "unconfigured": self.unconfigured,
        }

    @classmethod
    def for_role(cls, role: str) -> "Caller":
        """역할 이름으로 호출자를 만든다.

        예시 자세의 역할 선택과 시험이 같은 문을 쓰게 하려고 둔다 — 시험이 자기만의
        가짜 호출자를 만들면 실제로 돌아가는 권한 계산과 다른 것을 검사하게 된다.
        """
        if role not in ROLE_PERMISSIONS:
            raise AccountError(f"unknown role: {role!r}")
        return cls(actor=f"{DEMO_ACTOR_PREFIX}{role}",
                   permissions=frozenset(ROLE_PERMISSIONS[role]),
                   unconfigured=True, display_name=role, role=role)

    @classmethod
    def unauthenticated(cls) -> "Caller":
        return cls(actor="unauthenticated")

    @classmethod
    def from_decision(cls, decision: "Decision") -> "Caller":
        if decision.account is not None:
            return cls(actor=decision.account.account_id,
                       permissions=decision.account.permissions,
                       display_name=decision.account.display_name,
                       role=decision.account.role)
        if decision.demo_account is not None:
            # 예시 자세: 고른 **계정**의 능력을 그대로 쓴다. 역할 묶음이 아니라
            # 계정의 유효 능력이라, 관리자가 그 사람에게 부여한 것이 바로 보인다.
            return cls(actor=decision.actor,
                       permissions=decision.demo_account.permissions,
                       unconfigured=True,
                       display_name=decision.demo_account.display_name
                       or decision.demo_account.account_id,
                       role=decision.demo_account.role)
        if decision.unconfigured:
            # 계정도 없고 아무도 고르지 않았다. 조회만 열어 선택 화면을 띄운다.
            return cls(actor="unconfigured", permissions=frozenset(NO_ACCOUNT_PERMISSIONS),
                       unconfigured=True)
        return cls.unauthenticated()


@dataclass
class AccountStore:
    """계정과 세션. 파일은 공개 트리 밖에 있고 0600 으로만 읽는다."""

    path: Path = field(default_factory=lambda: DEFAULT_ACCOUNTS_PATH)
    strict_permissions: bool = True
    session_ttl_s: float = SESSION_TTL_S
    clock: Any = time.time
    #: 예시 자세에서만 쓰는 메모리 전용 계정. `configured` 에 **들어가지 않는다** —
    #: 들어가면 예시 계정이 생기자마자 역할 선택이 닫혀 버린다.
    seed_examples: bool = True
    _accounts: dict[str, Account] = field(default_factory=dict, init=False)
    _examples: dict[str, Account] = field(default_factory=dict, init=False)
    _sessions: dict[str, Session] = field(default_factory=dict, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.load()
        if self.seed_examples and not self.configured:
            self._seed_examples()

    def _seed_examples(self) -> None:
        """예시 계정을 메모리에 세운다. 비밀번호로 쓸 수 없는 해시를 넣는다.

        로그인에 쓰이지 않을 해시를 일부러 난수로 채운다 — 빈 문자열이나 알려진 값을
        넣으면 그것이 사실상 기본 자격증명이 되고, 그것이 AI-B-02 가 금지하는 것이다.
        """
        for account_id, role, display_name in EXAMPLE_ACCOUNTS:
            self._examples[account_id] = Account(
                account_id=account_id, role=role,
                password_hash=secrets.token_hex(32),
                salt_hex=secrets.token_bytes(PBKDF2_SALT_BYTES).hex(),
                display_name=display_name, created_at=float(self.clock()))

    # -- 파일 -------------------------------------------------------------

    @property
    def configured(self) -> bool:
        """계정이 **설정된 적이 있는가**. 쓸 수 있는 계정이 있는가가 아니다.

        처음에는 `any(enabled)` 로 썼고 시험이 그것을 잡았다 — 마지막 계정을 막으면
        `configured` 가 다시 False 가 되어 **익명 조회가 열렸다.** 막는 행위가 문을
        여는 셈이다.

        그래서 기준은 "계정이 하나라도 존재하는가" 다. 전부 막힌 설치는 아무도 못
        들어오는 상태가 되고, 그것이 안전한 쪽의 실패다 — 잠겨 버린 콘솔은 셸에서
        `accounts add` 로 복구할 수 있지만, 실수로 열린 콘솔은 그 실수로부터 복구할
        수 없다.
        """
        return bool(self._accounts)

    def load(self) -> None:
        """파일이 없으면 계정이 없는 정상 상태다 — 오류가 아니다."""
        if not self.path.exists():
            self._accounts = {}
            return
        self._check_permissions()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise AccountError(f"{self.path}: not valid JSON: {error}") from error
        entries = raw.get("accounts")
        if not isinstance(entries, list):
            raise AccountError(f"{self.path}: needs a top-level 'accounts' list")
        loaded: dict[str, Account] = {}
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                raise AccountError(f"{self.path}: accounts[{index}] must be an object")
            try:
                loaded[entry["account_id"]] = Account(
                    account_id=entry["account_id"], role=entry["role"],
                    password_hash=entry["password_hash"], salt_hex=entry["salt_hex"],
                    iterations=int(entry.get("iterations", PBKDF2_ITERATIONS)),
                    display_name=entry.get("display_name", ""),
                    extra_permissions=tuple(entry.get("extra_permissions", ())),
                    enabled=bool(entry.get("enabled", True)),
                    created_at=entry.get("created_at"),
                    external_subject=entry.get("external_subject"),
                )
            except KeyError as error:
                raise AccountError(
                    f"{self.path}: accounts[{index}] missing {error.args[0]!r}") from error
        self._accounts = loaded

    def _check_permissions(self) -> None:
        """다른 사용자가 읽을 수 있는 계정 파일은 쓰지 않는다.

        `registry/device_registry.py::CredentialStore` 와 같은 규칙을 쓴다 — 비밀이
        담긴 파일의 모드를 두 곳에서 다르게 보면 한쪽이 느슨해진 것을 아무도 모른다.
        """
        if not self.strict_permissions or os.name != "posix":
            return
        mode = stat.S_IMODE(self.path.stat().st_mode)
        if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
            raise AccountError(
                f"{self.path}: must not be readable by group/other (chmod 600), got {mode:o}")

    def save(self) -> Path:
        """원자적으로 쓰고 0600 으로 만든다."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            body = {
                "$comment": (
                    "FMS 콘솔 계정. **공개 저장소에 올리지 않는다** — 비밀번호 해시와 "
                    "salt 가 들어 있다(AI-B-02). 평문 비밀번호는 어디에도 저장되지 "
                    "않으며, 분실하면 재설정이 아니라 새로 만든다."
                ),
                "format_version": ACCOUNTS_FORMAT_VERSION,
                "accounts": [a.as_stored() for a in self._accounts.values()],
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
                os.chmod(handle.name, 0o600)
                os.replace(handle.name, self.path)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
            return self.path

    # -- 계정 -------------------------------------------------------------

    def add(self, account_id: str, password: str, role: str, **kwargs) -> Account:
        with self._lock:
            if account_id in self._accounts:
                raise AccountError(f"account already exists: {account_id!r}")
            account = Account.create(account_id, password, role, **kwargs)
            self._accounts[account_id] = account
        self.save()
        return account

    def disable(self, account_id: str) -> Account:
        """계정을 지우지 않고 막는다 — 지우면 그 계정이 만든 기록의 작성자가 사라진다."""
        with self._lock:
            account = self._holder(account_id)[account_id]
            if PERM_MANAGE_ACCOUNTS in account.permissions:
                self._guard_last_manager(account_id, PERM_MANAGE_ACCOUNTS)
            updated = replace(account, enabled=False)
            self._holder(account_id)[account_id] = updated
            # 막힌 계정의 세션도 함께 끊는다 — 막았는데 들어와 있으면 막은 것이 아니다.
            for token, session in list(self._sessions.items()):
                if session.account_id == account_id:
                    del self._sessions[token]
            persisted = account_id in self._accounts
        if persisted:
            self.save()
        return updated

    def accounts(self) -> tuple[dict, ...]:
        """관리자 화면이 그리는 목록. 예시 계정은 그 사실을 달고 나간다."""
        rows = [{**a.as_public(), "example": False} for a in self._accounts.values()]
        rows += [{**a.as_public(), "example": True} for a in self._examples.values()]
        return tuple(sorted(rows, key=lambda row: row["account_id"]))

    def _holder(self, account_id: str) -> dict[str, Account]:
        if account_id in self._accounts:
            return self._accounts
        if account_id in self._examples:
            return self._examples
        raise AccountError(f"unknown account: {account_id!r}")

    def _store_change(self, account_id: str, updated: Account) -> bool:
        """바꾼 것을 제자리에 넣는다. 예시 계정은 디스크에 쓰지 않는다."""
        holder = self._holder(account_id)
        holder[account_id] = updated
        if holder is self._accounts:
            self.save()
            return True
        return False

    def grant(self, account_id: str, permission: str, *, actor: str) -> dict:
        """한 사람에게 능력 하나를 더한다 — **역할을 넓히지 않고.**

        역할을 고쳐서 해결하면 그 역할을 가진 모든 사람이 같이 넓어진다. 한 사람만
        열어야 하는 경우가 실제로 대부분이고, 그래서 개별 부여가 따로 있다.
        """
        if permission not in ALL_PERMISSIONS:
            raise AccountError(f"unknown permission: {permission!r}")
        with self._lock:
            account = self._holder(account_id)[account_id]
            if permission in account.permissions:
                return {"account_id": account_id, "change": CHANGE_NOT_NEEDED,
                        "permission": permission, "actor": actor,
                        "from_role": permission in ROLE_PERMISSIONS[account.role]}
            updated = replace(
                account,
                extra_permissions=tuple(sorted(set(account.extra_permissions) | {permission})))
            persisted = self._store_change(account_id, updated)
        return {"account_id": account_id, "change": CHANGE_GRANTED,
                "permission": permission, "actor": actor, "persisted": persisted,
                "account": updated.as_public()}

    def revoke(self, account_id: str, permission: str, *, actor: str) -> dict:
        """개별 부여를 되돌린다. **역할이 주는 능력은 여기서 뺄 수 없다.**

        역할이 주는 것을 개별로 빼면 "그 역할이 무엇인가" 가 사람마다 달라지고, 그
        목록을 보고 권한을 판단할 수 없게 된다. 그 경우에는 역할을 바꾸는 것이 맞고,
        거절 사유가 그렇게 말한다.
        """
        if permission not in ALL_PERMISSIONS:
            raise AccountError(f"unknown permission: {permission!r}")
        with self._lock:
            account = self._holder(account_id)[account_id]
            if permission in ROLE_PERMISSIONS[account.role]:
                raise AccountError(
                    f"{DENY_ROLE_PERMISSION_NOT_REVOCABLE}:{account.role}")
            if permission not in account.extra_permissions:
                return {"account_id": account_id, "change": CHANGE_NOT_NEEDED,
                        "permission": permission, "actor": actor}
            self._guard_last_manager(account_id, permission)
            updated = replace(
                account,
                extra_permissions=tuple(p for p in account.extra_permissions
                                        if p != permission))
            persisted = self._store_change(account_id, updated)
        return {"account_id": account_id, "change": CHANGE_REVOKED,
                "permission": permission, "actor": actor, "persisted": persisted,
                "account": updated.as_public()}

    def set_role(self, account_id: str, role: str, *, actor: str) -> dict:
        if role not in ROLE_PERMISSIONS:
            raise AccountError(f"unknown role: {role!r}")
        with self._lock:
            account = self._holder(account_id)[account_id]
            if account.role == role:
                return {"account_id": account_id, "change": CHANGE_NOT_NEEDED,
                        "role": role, "actor": actor}
            if PERM_MANAGE_ACCOUNTS not in frozenset(ROLE_PERMISSIONS[role]) | set(
                    account.extra_permissions):
                self._guard_last_manager(account_id, PERM_MANAGE_ACCOUNTS)
            updated = replace(account, role=role)
            persisted = self._store_change(account_id, updated)
        return {"account_id": account_id, "change": CHANGE_ROLE_SET, "role": role,
                "actor": actor, "persisted": persisted, "account": updated.as_public()}

    def _guard_last_manager(self, account_id: str, permission: str) -> None:
        """계정을 관리할 수 있는 사람을 0 으로 만드는 변경을 막는다.

        막아 두지 않으면 관리자가 자기 권한을 떼는 한 번의 실수로 아무도 권한을
        고칠 수 없는 상태가 되고, 그건 셸로만 복구된다. 잠기는 것 자체는 안전한
        실패지만, **되돌릴 수 없는 잠김**은 안전이 아니라 사고다.
        """
        if permission != PERM_MANAGE_ACCOUNTS:
            return
        managers = {
            row["account_id"] for row in self.accounts()
            if row["enabled"] and PERM_MANAGE_ACCOUNTS in row["permissions"]
        }
        if managers <= {account_id}:
            raise AccountError(DENY_LAST_ADMIN)

    def _require(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountError(f"unknown account: {account_id!r}")
        return account

    # -- 세션 -------------------------------------------------------------

    @property
    def auth_mode(self) -> str:
        return AUTH_MODE_ACCOUNTS if self.configured else AUTH_MODE_DEMO_ROLES

    def assume_account(self, account_id: str) -> tuple[Session | None, str]:
        """비밀번호 없이 예시 계정을 골라 들어온다. **예시 자세에서만** 된다.

        역할이 아니라 계정을 고른다. 역할을 고르게 하면 관리자가 한 사람에게
        부여한 능력이 그 사람에게 생기지 않는다 — 역할 묶음만 들고 들어오기
        때문이다. 계정을 고르면 부여가 그대로 보인다.

        계정이 하나라도 **설정되면** 거절한다 — 실제 계정을 만들어 둔 배포에서 이
        길이 남아 있으면 계정을 만든 의미가 없다.
        """
        if self.configured:
            return None, DENY_DEMO_DISABLED
        if account_id not in self._examples:
            raise AccountError(f"unknown example account: {account_id!r}")
        now = float(self.clock())
        session = Session(token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
                          account_id=f"{DEMO_ACTOR_PREFIX}{account_id}",
                          issued_at=now, expires_at=now + self.session_ttl_s)
        with self._lock:
            self._sessions[session.token] = session
        return session, AUTH_MODE_DEMO_ROLES

    def login(self, account_id: str, password: str) -> tuple[Session | None, str]:
        """성공하면 세션, 실패하면 사유. **사용자 없음과 비밀번호 불일치를 구분하지
        않는다** — 구분하면 어느 계정이 존재하는지 알려 주는 창구가 된다.
        """
        account = self._accounts.get(account_id)
        if account is None:
            # 존재하지 않는 계정에도 같은 비용을 쓴다. 응답 시간으로 존재 여부가
            # 새지 않게 하려면 해시를 실제로 한 번 돌려야 한다.
            _hash_password(password, salt=b"\x00" * PBKDF2_SALT_BYTES,
                           iterations=PBKDF2_ITERATIONS)
            return None, AUTH_BAD_CREDENTIALS
        if not account.enabled:
            return None, DENY_ACCOUNT_DISABLED
        if not account.verify(password):
            return None, AUTH_BAD_CREDENTIALS
        now = float(self.clock())
        session = Session(token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
                          account_id=account_id, issued_at=now,
                          expires_at=now + self.session_ttl_s)
        with self._lock:
            self._sessions[session.token] = session
        return session, "authenticated"

    def logout(self, token: str) -> bool:
        with self._lock:
            return self._sessions.pop(token, None) is not None

    def session_count(self) -> int:
        return len(self._sessions)

    def _resolve(self, token: str | None) -> Decision:
        # 토큰을 **먼저** 본다. 미설정 상태를 먼저 돌려주면 예시 자세에서 고른 역할의
        # 세션이 그 분기에 가로막혀 영원히 조회 전용으로 보인다 — 처음에 그렇게
        # 썼고, 역할을 골라도 아무 권한이 붙지 않는 증상으로 드러났다.
        if not token:
            if not self.configured:
                # 계정도 없고 아직 역할도 고르지 않았다. 조회만 열어 선택 화면을 띄운다.
                return Decision(allowed=True, reason=DENY_NO_ACCOUNTS_CONFIGURED,
                                unconfigured=True)
            return Decision(allowed=False, reason=DENY_NO_SESSION)
        session = self._sessions.get(token)
        if session is None:
            return Decision(allowed=False, reason=DENY_UNKNOWN_SESSION)
        if session.expired(now=float(self.clock())):
            with self._lock:
                self._sessions.pop(token, None)
            return Decision(allowed=False, reason=DENY_SESSION_EXPIRED)
        if session.account_id.startswith(DEMO_ACTOR_PREFIX):
            # 예시 세션. 실제 계정 레코드가 아니라 예시 계정을 가리킨다. **매번
            # 다시 집는다** — 그래야 관리자가 방금 부여한 능력이 다음 요청부터
            # 그 사람에게 생긴다(사본을 들고 있으면 영영 바뀌지 않는다).
            example_id = session.account_id[len(DEMO_ACTOR_PREFIX):]
            example = self._examples.get(example_id)
            if self.configured or example is None or not example.enabled:
                # 도는 중에 계정이 생겼거나 그 예시 계정이 막혔다면 즉시 무효다.
                with self._lock:
                    self._sessions.pop(token, None)
                return Decision(allowed=False, reason=DENY_DEMO_DISABLED)
            return Decision(allowed=True, reason=AUTH_MODE_DEMO_ROLES,
                            account=None, unconfigured=True,
                            demo_account=example)
        account = self._accounts.get(session.account_id)
        if account is None or not account.enabled:
            with self._lock:
                self._sessions.pop(token, None)
            return Decision(allowed=False, reason=DENY_ACCOUNT_DISABLED)
        return Decision(allowed=True, reason="authenticated", account=account)

    # -- 검사 -------------------------------------------------------------

    def authorize(self, token: str | None, permission: str) -> Decision:
        """이 토큰이 이 능력을 갖고 있는가. 검사하는 쪽은 역할 이름을 묻지 않는다."""
        if permission not in ALL_PERMISSIONS:
            raise AccountError(f"unknown permission: {permission!r}")
        decision = self._resolve(token)
        if not decision.allowed:
            return decision
        if decision.unconfigured:
            allowed = permission in NO_ACCOUNT_PERMISSIONS
            return Decision(
                allowed=allowed,
                reason=DENY_NO_ACCOUNTS_CONFIGURED if allowed
                else f"{DENY_MISSING_PERMISSION}:{permission}",
                unconfigured=True)
        if permission not in decision.account.permissions:
            return Decision(allowed=False,
                            reason=f"{DENY_MISSING_PERMISSION}:{permission}",
                            account=decision.account)
        return decision

    def caller(self, token: str | None) -> Caller:
        """토큰 하나를 호출자로 바꾼다. 거절은 능력이 비는 것으로 표현된다."""
        return Caller.from_decision(self._resolve(token))

    def identify(self, token: str | None) -> dict:
        """화면이 "지금 누구로 들어와 있는가" 를 그리는 데 쓰는 묶음."""
        decision = self._resolve(token)
        caller = Caller.from_decision(decision)
        session = self._sessions.get(token or "")
        # 세션이 언제 끊기는지는 **남은 초**로 낸다. 만료 시각을 그대로 내면 화면이
        # 서버와 시계가 다를 때 엉뚱한 숫자를 띄운다(두 기계의 시계는 다르다).
        remaining = (None if session is None
                     else max(0.0, session.expires_at - float(self.clock())))
        return {
            "session_expires_in_s": remaining,
            "authenticated": decision.allowed and (
                decision.account is not None or decision.demo_account is not None),
            "auth_mode": self.auth_mode,
            "demo_account": (None if decision.demo_account is None
                             else decision.demo_account.account_id),
            # 예시 자세에서 고를 수 있는 **계정** 목록. 역할이 아니라 계정이라
            # 관리자가 한 사람에게 준 능력이 그 사람에게 그대로 생긴다.
            "selectable_accounts": ([] if self.configured else
                [{"account_id": a.account_id,
                  "display_name": a.display_name or a.account_id,
                  "role": a.role}
                 for a in sorted(self._examples.values(),
                                 key=lambda x: x.account_id)]),
            "unconfigured": decision.unconfigured,
            "actor": caller.actor,
            "reason": decision.reason,
            "account": decision.account.as_public() if decision.account else None,
            "permissions": sorted(caller.permissions),
            "roles": {name: sorted(perms) for name, perms in ROLE_PERMISSIONS.items()},
        }


def _cli(argv: list[str] | None = None) -> int:
    """첫 계정을 만드는 길. 기본 계정을 출하하지 않으므로 이 경로가 유일하다."""
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="FMS console accounts.")
    parser.add_argument("action", choices=("add", "list", "disable"))
    parser.add_argument("account_id", nargs="?")
    parser.add_argument("--role", default="viewer", choices=sorted(ROLE_PERMISSIONS))
    parser.add_argument("--path", default=None)
    parser.add_argument("--display-name", default="")
    args = parser.parse_args(argv)

    store = AccountStore(path=Path(args.path) if args.path else DEFAULT_ACCOUNTS_PATH)
    if args.action == "list":
        for row in store.accounts():
            print(f"{row['account_id']:20s} {row['role']:10s} "
                  f"{'enabled' if row['enabled'] else 'disabled':9s} "
                  f"{len(row['permissions'])} permissions")
        if not store.configured:
            print("계정이 없다. `add` 로 첫 계정을 만든다 — 기본 계정은 출하되지 않는다.")
        return 0
    if not args.account_id:
        parser.error("account_id is required for this action")
    if args.action == "disable":
        store.disable(args.account_id)
        print(f"disabled {args.account_id}")
        return 0

    # 비밀번호는 인자로 받지 않는다 — 셸 이력과 프로세스 목록에 남는다.
    password = getpass.getpass("password: ")
    if password != getpass.getpass("again: "):
        print("passwords do not match")
        return 1
    account = store.add(args.account_id, password, args.role,
                        display_name=args.display_name)
    print(f"created {account.account_id} ({account.role}) at {store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
