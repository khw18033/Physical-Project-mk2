"""implements: AI-C-19, AI-B-02
covers: no default credentials, permissions are capabilities not role names,
        a disabled account's session dies with it, the store never keeps plaintext
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

CONSOLE_DIR = Path(__file__).resolve().parents[1] / "tools" / "fms_console"
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

from accounts import (  # noqa: E402
    ALL_PERMISSIONS,
    AUTH_BAD_CREDENTIALS,
    DENY_ACCOUNT_DISABLED,
    DENY_NO_ACCOUNTS_CONFIGURED,
    DENY_NO_SESSION,
    DENY_SESSION_EXPIRED,
    NO_ACCOUNT_PERMISSIONS,
    PERM_COMMAND,
    PERM_CORRECT,
    PERM_DEPLOY_MODEL,
    PERM_LABEL,
    PERM_MANAGE_ACCOUNTS,
    PERM_SEE_INTERNALS,
    PERM_VIEW,
    ROLE_PERMISSIONS,
    Account,
    AccountError,
    AccountStore,
)

GOOD_PASSWORD = "a-long-enough-pass"


@pytest.fixture()
def store(tmp_path):
    return AccountStore(path=tmp_path / "accounts.json")


@pytest.fixture()
def admin(store):
    store.add("admin-1", GOOD_PASSWORD, "admin")
    session, _ = store.login("admin-1", GOOD_PASSWORD)
    return session


# --- 기본 계정을 출하하지 않는다 --------------------------------------------


def test_a_fresh_install_has_no_real_accounts_only_example_rows(store):
    """AI-B-02: 자격증명을 이미지·저장소에 포함하지 않는다. 기본 계정도 포함이다.

    예시 자세에서는 관리자 화면이 다룰 대상이 있어야 하므로 예시 계정을 **메모리에만**
    둔다. 그 행들은 `example: True` 를 달고 나가고, `configured` 에는 들어가지 않는다 —
    들어가면 예시 계정이 생기자마자 역할 선택이 닫혀 버린다.
    """
    rows = store.accounts()

    assert rows, "관리자 화면이 다룰 행이 있어야 예시가 성립한다"
    assert all(row["example"] for row in rows)
    assert store.configured is False
    assert store.path.exists() is False, "예시 계정은 디스크에 쓰이지 않는다"


def test_examples_can_be_turned_off_for_a_real_deployment(tmp_path):
    store = AccountStore(path=tmp_path / "accounts.json", seed_examples=False)

    assert store.accounts() == ()
    assert store.configured is False


def test_a_fresh_install_allows_looking_but_not_acting(store):
    """잠긴 문을 열어 두는 것보다 들어갈 수 없다고 말하는 쪽이 옳다."""
    assert store.authorize(None, PERM_VIEW).allowed is True
    assert store.authorize(None, PERM_COMMAND).allowed is False
    assert NO_ACCOUNT_PERMISSIONS == (PERM_VIEW,)


def test_a_fresh_install_says_it_is_unconfigured_rather_than_denying_silently(store):
    decision = store.authorize(None, PERM_VIEW)

    assert decision.unconfigured is True
    assert decision.reason == DENY_NO_ACCOUNTS_CONFIGURED


def test_once_an_account_exists_anonymous_viewing_stops(store):
    store.add("someone", GOOD_PASSWORD, "viewer")

    assert store.authorize(None, PERM_VIEW).allowed is False
    assert store.authorize(None, PERM_VIEW).reason == DENY_NO_SESSION


# --- 비밀은 저장되지 않는다 --------------------------------------------------


def test_the_stored_file_never_contains_the_password(store):
    store.add("someone", GOOD_PASSWORD, "viewer")

    assert GOOD_PASSWORD not in store.path.read_text(encoding="utf-8")


def test_two_accounts_with_the_same_password_get_different_hashes(store):
    """salt 가 사용자마다 달라야 한 해시가 두 계정을 열지 않는다."""
    a = store.add("a", GOOD_PASSWORD, "viewer")
    b = store.add("b", GOOD_PASSWORD, "viewer")

    assert a.password_hash != b.password_hash
    assert a.salt_hex != b.salt_hex


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX-only")
def test_the_account_file_is_written_unreadable_by_others(store):
    store.add("someone", GOOD_PASSWORD, "viewer")

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX-only")
def test_a_loosely_permissioned_account_file_is_refused(tmp_path):
    first = AccountStore(path=tmp_path / "accounts.json")
    first.add("someone", GOOD_PASSWORD, "viewer")
    os.chmod(first.path, 0o644)

    with pytest.raises(AccountError):
        AccountStore(path=first.path)


def test_a_short_password_is_refused_at_creation(store):
    with pytest.raises(AccountError):
        store.add("someone", "short", "viewer")


def test_a_corrupt_account_file_is_refused_rather_than_treated_as_empty(tmp_path):
    """빈 것으로 읽으면 잠긴 설치가 조용히 열린 설치가 된다."""
    path = tmp_path / "accounts.json"
    path.write_text("{not json", encoding="utf-8")
    os.chmod(path, 0o600)

    with pytest.raises(AccountError):
        AccountStore(path=path)


# --- 로그인 ------------------------------------------------------------------


def test_a_wrong_password_and_an_unknown_account_give_the_same_answer(store):
    """구분하면 어느 계정이 존재하는지 알려 주는 창구가 된다."""
    store.add("someone", GOOD_PASSWORD, "viewer")

    _, wrong = store.login("someone", "not-the-password")
    _, missing = store.login("nobody-here", "not-the-password")

    assert wrong == missing == AUTH_BAD_CREDENTIALS


def test_a_successful_login_issues_an_unguessable_token(store):
    store.add("someone", GOOD_PASSWORD, "viewer")

    first, _ = store.login("someone", GOOD_PASSWORD)
    second, _ = store.login("someone", GOOD_PASSWORD)

    assert first.token != second.token
    assert len(first.token) >= 32


def test_logging_out_invalidates_that_token_only(store):
    store.add("someone", GOOD_PASSWORD, "viewer")
    first, _ = store.login("someone", GOOD_PASSWORD)
    second, _ = store.login("someone", GOOD_PASSWORD)

    assert store.logout(first.token) is True

    assert store.authorize(first.token, PERM_VIEW).allowed is False
    assert store.authorize(second.token, PERM_VIEW).allowed is True


def test_an_expired_session_is_refused_with_that_reason(tmp_path):
    clock = [1000.0]
    store = AccountStore(path=tmp_path / "accounts.json", session_ttl_s=60.0,
                         clock=lambda: clock[0])
    store.add("someone", GOOD_PASSWORD, "viewer")
    session, _ = store.login("someone", GOOD_PASSWORD)
    clock[0] += 61.0

    decision = store.authorize(session.token, PERM_VIEW)

    assert decision.allowed is False
    assert decision.reason == DENY_SESSION_EXPIRED


def test_a_disabled_account_cannot_log_in(store):
    store.add("someone", GOOD_PASSWORD, "viewer")
    store.disable("someone")

    session, reason = store.login("someone", GOOD_PASSWORD)

    assert session is None
    assert reason == DENY_ACCOUNT_DISABLED


def test_disabling_an_account_also_kills_its_live_session(store):
    """막았는데 들어와 있으면 막은 것이 아니다."""
    store.add("someone", GOOD_PASSWORD, "operator")
    session, _ = store.login("someone", GOOD_PASSWORD)
    assert store.authorize(session.token, PERM_COMMAND).allowed is True

    store.disable("someone")

    assert store.authorize(session.token, PERM_VIEW).allowed is False


def test_disabling_the_last_account_locks_the_console_rather_than_opening_it(store):
    """막는 행위가 문을 여는 일은 없어야 한다.

    `configured` 를 "쓸 수 있는 계정이 있는가" 로 두었을 때 실제로 그렇게 됐다 —
    마지막 계정을 막으면 설치가 다시 "계정 없음" 으로 보이고 익명 조회가 열렸다.
    잠겨 버린 콘솔은 셸에서 복구할 수 있지만 실수로 열린 콘솔은 그렇지 않다.
    """
    store.add("only-one", GOOD_PASSWORD, "admin")
    store.disable("only-one")

    decision = store.authorize(None, PERM_VIEW)

    assert decision.allowed is False
    assert decision.unconfigured is False


def test_disabling_keeps_the_account_so_its_records_keep_an_author(store):
    """지우면 그 계정이 만든 기록의 작성자가 사라진다(AI-L-03)."""
    store.add("someone", GOOD_PASSWORD, "labeler")

    store.disable("someone")

    rows = {row["account_id"]: row for row in store.accounts()}
    assert rows["someone"]["enabled"] is False


# --- 권한은 능력이고 역할 이름이 아니다 --------------------------------------


def test_every_role_is_a_named_bundle_of_known_capabilities():
    """역할이 능력 목록으로만 정의되면 새 역할은 표 한 줄이고 코드 변경이 아니다."""
    for role, permissions in ROLE_PERMISSIONS.items():
        unknown = set(permissions) - set(ALL_PERMISSIONS)
        assert unknown == set(), f"{role} declares unknown capabilities: {unknown}"


def test_every_role_can_at_least_look(store):
    for role in ROLE_PERMISSIONS:
        store_role = AccountStore(path=store.path.with_name(f"{role}.json"))
        store_role.add("x", GOOD_PASSWORD, role)
        session, _ = store_role.login("x", GOOD_PASSWORD)
        assert store_role.authorize(session.token, PERM_VIEW).allowed is True


def test_a_labeler_may_create_ground_truth_but_not_move_a_robot(store):
    """라벨 작업자와 로봇을 움직이는 사람은 보통 다른 사람이다."""
    store.add("labeler-1", GOOD_PASSWORD, "labeler")
    session, _ = store.login("labeler-1", GOOD_PASSWORD)

    assert store.authorize(session.token, PERM_LABEL).allowed is True
    assert store.authorize(session.token, PERM_CORRECT).allowed is True
    assert store.authorize(session.token, PERM_COMMAND).allowed is False
    assert store.authorize(session.token, PERM_DEPLOY_MODEL).allowed is False


def test_an_operator_may_command_but_not_see_contract_internals(store):
    store.add("op-1", GOOD_PASSWORD, "operator")
    session, _ = store.login("op-1", GOOD_PASSWORD)

    assert store.authorize(session.token, PERM_COMMAND).allowed is True
    assert store.authorize(session.token, PERM_SEE_INTERNALS).allowed is False


def test_only_an_admin_may_manage_accounts(store):
    for role in ("viewer", "labeler", "operator", "developer"):
        store.add(role, GOOD_PASSWORD, role)
        session, _ = store.login(role, GOOD_PASSWORD)
        assert store.authorize(session.token, PERM_MANAGE_ACCOUNTS).allowed is False


def test_a_denied_check_names_the_missing_capability(store):
    store.add("viewer-1", GOOD_PASSWORD, "viewer")
    session, _ = store.login("viewer-1", GOOD_PASSWORD)

    decision = store.authorize(session.token, PERM_COMMAND)

    assert decision.reason == f"missing_permission:{PERM_COMMAND}"


def test_an_extra_capability_opens_one_person_without_widening_a_role(store):
    store.add("viewer-plus", GOOD_PASSWORD, "viewer",
              extra_permissions=(PERM_LABEL,))
    session, _ = store.login("viewer-plus", GOOD_PASSWORD)

    assert store.authorize(session.token, PERM_LABEL).allowed is True
    # 그 역할 자체는 넓어지지 않았다.
    assert PERM_LABEL not in ROLE_PERMISSIONS["viewer"]


def test_an_unknown_capability_is_refused_at_account_creation(store):
    with pytest.raises(AccountError):
        store.add("x", GOOD_PASSWORD, "viewer", extra_permissions=("may_do_anything",))


def test_an_unknown_role_is_refused(store):
    with pytest.raises(AccountError):
        store.add("x", GOOD_PASSWORD, "superuser")


def test_asking_about_an_unknown_capability_is_a_programming_error(store, admin):
    """오타난 능력 이름이 조용히 False 가 되면 그 문은 영원히 닫힌 채 잊힌다."""
    with pytest.raises(AccountError):
        store.authorize(admin.token, "may_do_whatever")


# --- 기록의 작성자 ------------------------------------------------------------


def test_the_actor_recorded_in_a_ledger_is_the_account_not_the_role(store):
    store.add("jny", GOOD_PASSWORD, "admin")
    session, _ = store.login("jny", GOOD_PASSWORD)

    assert store.authorize(session.token, PERM_LABEL).actor == "jny"


def test_an_unauthenticated_decision_says_so_rather_than_naming_a_role(store):
    assert store.authorize(None, PERM_VIEW).actor == "unauthenticated"


# --- 화면이 묻는 것 -----------------------------------------------------------


def test_identify_tells_the_screen_who_is_here_and_what_they_may_do(store):
    store.add("jny", GOOD_PASSWORD, "admin", display_name="진나영")
    session, _ = store.login("jny", GOOD_PASSWORD)

    body = store.identify(session.token)

    assert body["authenticated"] is True
    assert body["account"]["display_name"] == "진나영"
    assert set(body["permissions"]) == set(ALL_PERMISSIONS)
    assert "password_hash" not in json.dumps(body), "해시가 화면으로 나가면 안 된다"
    assert "salt_hex" not in json.dumps(body)


def test_identify_on_a_fresh_install_says_unconfigured(store):
    body = store.identify(None)

    assert body["unconfigured"] is True
    assert body["permissions"] == list(NO_ACCOUNT_PERMISSIONS)


def test_the_public_view_of_an_account_carries_no_secret(store):
    account = store.add("jny", GOOD_PASSWORD, "admin")

    public = json.dumps(account.as_public())

    assert account.password_hash not in public
    assert account.salt_hex not in public


def test_an_account_round_trips_through_its_stored_form(tmp_path):
    first = AccountStore(path=tmp_path / "accounts.json")
    created = first.add("jny", GOOD_PASSWORD, "admin", display_name="진나영",
                        extra_permissions=(PERM_LABEL,))

    reloaded = AccountStore(path=first.path)
    session, reason = reloaded.login("jny", GOOD_PASSWORD)

    assert session is not None, reason
    assert reloaded.accounts()[0]["display_name"] == created.display_name


def test_a_duplicate_account_id_is_refused_rather_than_overwriting(store):
    store.add("jny", GOOD_PASSWORD, "viewer")

    with pytest.raises(AccountError):
        store.add("jny", "a-different-long-pass", "admin")


def test_an_account_can_carry_the_backends_own_subject_without_rejudging_it(store):
    """운영 전체의 authoritative 인가는 백엔드가 한다 — 여기서 복제하지 않는다."""
    account = Account.create("jny", GOOD_PASSWORD, "admin",
                             external_subject="be-subject-42")

    assert account.external_subject == "be-subject-42"
