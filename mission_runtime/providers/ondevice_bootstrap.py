"""최초 1회 비밀번호 접속 → 키 설치 → 이후 키 인증.

implements: AI-B-02, AI-C-04, AI-B-09, AI-B-10

사용자가 원하는 것은 "주소와 비밀번호를 넣으면 바로 배포"다. 그런데 비밀번호를
계속 쓰면 그 비밀번호가 배포할 때마다 프로세스 환경을 지나간다.
`providers/ondevice_ssh.py`의 docstring이 이미 답을 적어 뒀다 — "a password is
handed to `sshpass -e` through the environment, which is why key auth is
installed on first contact and used from then on." 이 모듈이 그 "first contact"
한 번을 실제로 수행하는 부분이고, 그 전까지는 문서에만 있던 단계다.

지키는 선 네 개:

1. **비밀번호는 argv에 없다.** `SshRunner`가 이미 `sshpass -e`(환경변수)로
   넘긴다. 이 모듈은 그 경로를 그대로 쓰고 다른 경로를 새로 만들지 않는다.
2. **공개키도 argv로 보내지 않는다.** 비밀이 아니지만 원격 셸의 인용 규칙에
   기대는 순간 개행·따옴표가 있는 키가 깨지므로 stdin으로 보낸다.
3. **sudo 없음.** 전부 사용자 홈의 `~/.ssh` 안에서 끝난다.
4. **비밀번호는 저장소에 남기지 않는다.** 설치·검증이 끝나면 등록된 자격증명을
   키로 교체하고(`DeviceRegistry.set_credential`), 비밀번호 항목은 저장 대상에
   넣지 않는다. 실패했을 때만 비밀번호가 메모리에 남고, 그것도 호출자가
   버리면 끝이다.

키 설치가 실패해도 **비밀번호로는 이미 접속이 됐다**는 사실은 남는다. 그래서
`BootstrapResult`는 `reachable`과 `key_installed`를 따로 들고 있다 — "장치에
못 닿았다"와 "닿았지만 키를 못 심었다"는 다음 행동이 다르다(AI-O-04가 업무
평면과 관측 평면을 구분하라고 하는 것과 같은 이유다).
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mission_runtime.registry.device_registry import (
    AUTH_KEY,
    AUTH_PASSWORD,
    DeviceCredential,
    DeviceRegistry,
    DeviceRegistryError,
)

#: 통제 어휘. `providers/ondevice_ssh.py`의 거절 사유와 같은 규약(':' 앞이 토큰).
REASON_NO_PASSWORD = "bootstrap_password_missing"
REASON_SSHPASS_MISSING = "password_auth_unavailable:sshpass_missing"
REASON_KEYGEN_MISSING = "keygen_unavailable"
REASON_KEY_INSTALL_FAILED = "key_install_failed"
REASON_KEY_VERIFY_FAILED = "key_verify_failed"
REASON_UNREACHABLE = "device_unreachable"
REASON_NOT_PERMITTED = "not_permitted"

#: 원격에서 도는 설치 스크립트. 키는 stdin으로 들어온다.
#: `grep -qxF`로 이미 있는 줄을 다시 붙이지 않으므로 여러 번 돌려도 같다.
_INSTALL_SCRIPT = r"""
set -eu
umask 077
mkdir -p "$HOME/.ssh"
key=$(cat)
[ -n "$key" ] || { echo "error:empty_key" >&2; exit 2; }
touch "$HOME/.ssh/authorized_keys"
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/authorized_keys"
if grep -qxF "$key" "$HOME/.ssh/authorized_keys" 2>/dev/null; then
  echo "ok:already_present"
else
  printf '%s\n' "$key" >> "$HOME/.ssh/authorized_keys"
  echo "ok:installed"
fi
"""


@dataclass(frozen=True)
class BootstrapResult:
    """한 번의 부트스트랩 결과. 단계별로 따로 읽을 수 있게 쪼개 둔다."""

    device_id: str
    reachable: bool = False
    key_installed: bool = False
    already_present: bool = False
    key_verified: bool = False
    credential_id: str | None = None
    public_key_path: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.key_installed and self.key_verified

    def as_dict(self) -> dict:
        """화면·로그에 그대로 실어도 되는 모양. 비밀은 애초에 필드가 없다."""
        return {
            "device_id": self.device_id,
            "reachable": self.reachable,
            "key_installed": self.key_installed,
            "already_present": self.already_present,
            "key_verified": self.key_verified,
            "credential_id": self.credential_id,
            "public_key_path": self.public_key_path,
            "reason": self.reason,
            "ok": self.ok,
        }


def ensure_control_keypair(
    private_path: str | Path,
    *,
    comment: str = "mission_runtime-control",
    keygen: str = "ssh-keygen",
) -> tuple[Path, str]:
    """제어 노드의 키쌍을 확보한다. 있으면 그대로 쓰고 없으면 만든다.

    개인키는 0600으로 만들어지며(`ssh-keygen`의 기본), 이 함수는 그 권한을
    한 번 더 확인한다 — 느슨한 개인키는 ssh가 아예 거부하므로 배포가 아니라
    등록 단계에서 드러나는 편이 낫다.
    """
    private = Path(os.path.expanduser(str(private_path)))
    public = private.with_suffix(private.suffix + ".pub") if private.suffix else Path(str(private) + ".pub")
    if not private.exists():
        if shutil.which(keygen) is None:
            raise DeviceRegistryError(REASON_KEYGEN_MISSING)
        private.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(private.parent, 0o700)
        except OSError:
            pass
        proc = subprocess.run(
            [keygen, "-t", "ed25519", "-N", "", "-C", comment, "-f", str(private)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 or not private.exists():
            raise DeviceRegistryError(f"{REASON_KEYGEN_MISSING}:{(proc.stderr or '').strip()[:200]}")
    if not public.exists():
        raise DeviceRegistryError(f"{REASON_KEYGEN_MISSING}:public_key_missing:{public}")
    if os.name == "posix":
        os.chmod(private, 0o600)
        mode = stat.S_IMODE(private.stat().st_mode)
        if mode & 0o077:  # pragma: no cover - chmod above prevents it
            raise DeviceRegistryError(f"private key is group/world accessible (mode {mode:o}): {private}")
    return private, public.read_text(encoding="utf-8").strip()


def install_public_key(runner, public_key: str, *, timeout: int = 30) -> BootstrapResult:
    """공개키 한 줄을 `~/.ssh/authorized_keys`에 멱등하게 넣는다.

    `runner`는 `run(command, stdin=...)`을 가진 무엇이든 된다 — 여기서 ssh를
    이름으로 부르지 않는 이유는 AI-C-04다.
    """
    device_id = getattr(getattr(runner, "device", None), "device_id", "?")
    try:
        # The script travels in argv (it is not a secret and quoting it keeps
        # it one argument); the key travels on stdin, so newlines and quoting
        # in a real key cannot be mangled by the remote shell.
        proc = runner.run(
            "/bin/sh -c " + shlex.quote(_INSTALL_SCRIPT),
            timeout=timeout,
            stdin=public_key + "\n",
        )
    except subprocess.TimeoutExpired:
        return BootstrapResult(device_id, reason=REASON_UNREACHABLE)
    except Exception as error:
        return BootstrapResult(device_id, reason=f"{REASON_KEY_INSTALL_FAILED}:{type(error).__name__}")
    stdout = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        lowered = stdout.lower()
        if "permission denied" in lowered or "authentication fail" in lowered:
            return BootstrapResult(device_id, reason=REASON_NOT_PERMITTED)
        if proc.returncode == 255:
            return BootstrapResult(device_id, reason=REASON_UNREACHABLE)
        return BootstrapResult(device_id, reachable=True, reason=REASON_KEY_INSTALL_FAILED)
    return BootstrapResult(
        device_id,
        reachable=True,
        key_installed=True,
        already_present="ok:already_present" in stdout,
    )


def bootstrap_key_auth(
    registry: DeviceRegistry,
    device_id: str,
    *,
    password: str,
    key_path: str | Path,
    credential_id: str | None = None,
    persist: bool = True,
) -> BootstrapResult:
    """"주소 + 비밀번호로 등록" → "이후로는 키로 접속"까지 한 번에.

    순서가 곧 보장이다. 비밀번호는 (1) 이 호출 안에서만 존재하는 임시
    자격증명으로 만들어지고, (2) 키 설치 1회에만 쓰이고, (3) 키 인증이 실제로
    되는 것을 확인한 다음에야 등록이 키로 교체된다. 검증 전에 교체하면
    "키는 안 심겼는데 비밀번호도 잊은" 장치가 생긴다.

    실패하면 등록은 손대지 않는다 — 실패한 부트스트랩이 기존 접속 수단을
    빼앗아 가면 안 된다(AI-B-05의 "새 버전 적용 실패 시 마지막 정상 상태
    유지"와 같은 규칙).
    """
    from mission_runtime.providers.ondevice_ssh import SshRunner

    device = registry.get(device_id)
    if device is None:
        raise DeviceRegistryError(f"unknown device: {device_id}")
    if not password:
        return BootstrapResult(device_id, reason=REASON_NO_PASSWORD)
    if shutil.which("sshpass") is None:
        return BootstrapResult(device_id, reason=REASON_SSHPASS_MISSING)

    private, public_key = ensure_control_keypair(key_path)

    bootstrap_credential = DeviceCredential(
        credential_id=f"{device_id}-bootstrap",
        auth_method=AUTH_PASSWORD,
        secret=password,
    )
    installed = install_public_key(SshRunner(device, bootstrap_credential), public_key)
    if not installed.key_installed:
        return installed

    key_credential = DeviceCredential(
        credential_id=credential_id or f"{device_id}-key",
        auth_method=AUTH_KEY,
        key_path=str(private),
    )
    verified = _verify_key_auth(SshRunner(device, key_credential))
    if not verified:
        # 키가 안 먹는데 등록을 바꾸면 접속 수단을 잃는다. 비밀번호 등록을
        # 그대로 두고 사유만 돌려준다.
        return BootstrapResult(
            device_id,
            reachable=True,
            key_installed=True,
            already_present=installed.already_present,
            public_key_path=str(private) + ".pub",
            reason=REASON_KEY_VERIFY_FAILED,
        )

    registry.set_credential(device_id, key_credential)
    if persist:
        registry.save_credentials()
    return BootstrapResult(
        device_id,
        reachable=True,
        key_installed=True,
        already_present=installed.already_present,
        key_verified=True,
        credential_id=key_credential.credential_id,
        public_key_path=str(private) + ".pub",
    )


def _verify_key_auth(runner) -> bool:
    """키만으로 정말 붙는지 확인한다. 키 인증 runner는 BatchMode=yes라
    비밀번호로 조용히 되돌아가지 않는다 — 그래서 이 확인이 의미가 있다."""
    try:
        return runner.run("true", timeout=20).returncode == 0
    except Exception:
        return False
