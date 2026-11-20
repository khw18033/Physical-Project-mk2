"""배포 브랜치를 만드는 도구의 계약 — `tools/release/make_dist.py`.

implements: AI-B-02, AI-C-16
tests: 공개 목록이 **정본**이다 · 커밋되지 않은 작업은 거절한다 · 작업 트리를
       건드리지 않는다 · 역사를 고치지 않는다 · 꺼낸 트리에 공개 폴더만 있다

진짜 git 저장소를 만들어 돌린다. 가짜로 흉내 내면 `mktree`·`commit-tree` 가 실제로
그 모양을 받는지는 확인되지 않고, 이 도구에서 틀릴 수 있는 것은 전부 그 자리다.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "release" / "make_dist.py"


def _import():
    name = "make_dist_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """공개 폴더 하나와 **공개하지 않는 폴더 둘**을 가진 저장소."""
    root = tmp_path / "work"
    (root / "mission_runtime" / "tools").mkdir(parents=True)
    (root / "internal").mkdir()
    (root / "local").mkdir()
    (root / "mission_runtime" / "pyproject.toml").write_text("[project]\nname='x'\n")
    (root / "mission_runtime" / "tools" / "install_check.sh").write_text("echo ok\n")
    (root / "internal" / "secret-report.md").write_text("내부 기록\n")
    (root / "local" / "weights.bin").write_text("0" * 10)

    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    run(root, "config", "user.email", "t@example.invalid")
    run(root, "config", "user.name", "t")
    run(root, "add", "-A")
    run(root, "commit", "-qm", "first")
    return root


def dist(module, repo: Path, *argv: str) -> int:
    """도구를 그 저장소에서 돌린다. `repo_root()` 를 그 저장소로 바꿔 끼운다."""
    original = module.repo_root
    module.repo_root = lambda start=None: repo
    try:
        return module.main(list(argv))
    finally:
        module.repo_root = original


# --------------------------------------------------------------- 정본

def test_the_tracked_file_list_is_the_source_of_truth(repo: Path):
    """목록을 다시 세우면 두 곳이 갈라지고, 갈라지는 날 **비밀정보가 들어가는 쪽은
    시험이 보지 않는 쪽**이다."""
    module = _import()
    tree = module.public_tree_sha(repo, "HEAD")
    root = module.root_tree_for(repo, tree)
    assert module.verify(repo, root, "HEAD") == 2


def test_only_the_public_folder_is_in_the_exported_tree(repo: Path, tmp_path: Path):
    module = _import()
    root = module.root_tree_for(repo, module.public_tree_sha(repo, "HEAD"))
    target = tmp_path / "out"
    module.export(repo, root, target)

    assert (target / "mission_runtime" / "pyproject.toml").is_file()
    assert not (target / "internal").exists(), "내부 기록은 공개 대상이 아니다"
    assert not (target / "local").exists()


def test_the_exported_tree_has_the_folder_at_its_top(repo: Path, tmp_path: Path):
    """받는 쪽이 `git clone` 하면 그 폴더 하나가 있고 그 안에서 바로 돈다."""
    module = _import()
    root = module.root_tree_for(repo, module.public_tree_sha(repo, "HEAD"))
    target = tmp_path / "out"
    module.export(repo, root, target)
    assert sorted(p.name for p in target.iterdir()) == ["mission_runtime"]


# --------------------------------------------------------------- 거절

def test_uncommitted_work_in_the_public_tree_is_refused(repo: Path, capsys):
    """**지금 올리면 그 변경은 들어가지 않고, 안 들어갔다는 사실도 안 보인다.**"""
    module = _import()
    (repo / "mission_runtime" / "new_module.py").write_text("x = 1\n")

    assert dist(module, repo, "--write") == 2
    printed = capsys.readouterr().out
    assert module.REASON_DIRTY in printed
    assert "new_module.py" in printed, "무엇을 커밋해야 하는지 이름으로 말한다"


def test_a_change_outside_the_public_tree_does_not_block_it(repo: Path):
    """내부 기록을 고치는 중이라고 배포가 막히면 **아무 때도 배포하지 못한다.**"""
    module = _import()
    (repo / "internal" / "note.md").write_text("작업 중\n")
    assert dist(module, repo) == 0


def test_there_is_no_way_to_force_a_dirty_tree(repo: Path):
    """거절은 거절이다 — 억지로 담은 트리는 **어느 커밋에도 없어서** "어디서
    나왔나" 에 답할 수 없다."""
    source = SCRIPT.read_text()
    assert "allow-dirty" not in source and "allow_dirty" not in source
    assert "--force" not in source


def test_an_unknown_source_revision_is_named(repo: Path):
    module = _import()
    with pytest.raises(module.DistError) as raised:
        module.public_tree_sha(repo, "no-such-branch")
    assert module.REASON_UNKNOWN_SOURCE in str(raised.value)


def test_a_commit_without_the_public_folder_is_refused(tmp_path: Path):
    module = _import()
    root = tmp_path / "bare"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    run(root, "config", "user.email", "t@example.invalid")
    run(root, "config", "user.name", "t")
    (root / "readme.md").write_text("empty\n")
    run(root, "add", "-A")
    run(root, "commit", "-qm", "no public dir")

    with pytest.raises(module.DistError) as raised:
        module.public_tree_sha(root, "HEAD")
    assert module.REASON_NO_PUBLIC_TREE in str(raised.value)


# --------------------------------------------------------------- 안전

def test_looking_does_not_move_the_branch(repo: Path):
    """`--write` 없이는 아무것도 바뀌지 않는다."""
    module = _import()
    assert dist(module, repo, "--branch", "dist") == 0
    with pytest.raises(subprocess.CalledProcessError):
        run(repo, "rev-parse", "--verify", "refs/heads/dist")


def test_writing_does_not_touch_the_working_tree_or_the_current_branch(repo: Path):
    """`git checkout` 을 하지 않는다 — 돌리는 동안 손에 든 파일이 바뀌지 않는다."""
    module = _import()
    before_head = run(repo, "rev-parse", "HEAD").strip()
    before_status = run(repo, "status", "--porcelain")

    assert dist(module, repo, "--branch", "dist", "--write") == 0

    assert run(repo, "rev-parse", "HEAD").strip() == before_head
    assert run(repo, "status", "--porcelain") == before_status
    assert run(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_the_dist_commit_carries_only_the_public_folder(repo: Path):
    module = _import()
    dist(module, repo, "--branch", "dist", "--write")

    top = run(repo, "ls-tree", "--name-only", "dist").split()
    assert top == ["mission_runtime"]
    files = run(repo, "ls-tree", "-r", "--name-only", "dist").split()
    assert "mission_runtime/pyproject.toml" in files
    assert not any(name.startswith(("internal/", "local/")) for name in files)


def test_the_second_run_stacks_on_top_instead_of_rewriting(repo: Path):
    """옛 배포 커밋은 그대로 남는다(AI-B-05 의 last-known-good 와 같은 규칙)."""
    module = _import()
    dist(module, repo, "--branch", "dist", "--write")
    first = run(repo, "rev-parse", "dist").strip()

    (repo / "mission_runtime" / "second.py").write_text("y = 2\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "second")
    dist(module, repo, "--branch", "dist", "--write")
    second = run(repo, "rev-parse", "dist").strip()

    assert second != first
    assert run(repo, "rev-parse", "dist^").strip() == first, "앞 커밋이 부모로 남는다"
    assert "mission_runtime/second.py" in run(repo, "ls-tree", "-r", "--name-only", "dist")


def test_the_message_says_which_commit_it_came_from(repo: Path):
    module = _import()
    dist(module, repo, "--branch", "dist", "--write")
    source = run(repo, "rev-parse", "--short", "HEAD").strip()
    assert source in run(repo, "log", "-1", "--format=%B", "dist")


def test_it_prints_how_to_undo(repo: Path, capsys):
    """되돌리는 길을 적지 않으면 **옮긴 뒤에 찾아야 한다.**"""
    module = _import()
    dist(module, repo, "--branch", "dist", "--write")
    capsys.readouterr()
    (repo / "mission_runtime" / "third.py").write_text("z = 3\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "third")
    dist(module, repo, "--branch", "dist", "--write")

    printed = capsys.readouterr().out
    assert "update-ref" in printed and "되돌리기" in printed


def test_it_does_not_push(repo: Path):
    """푸시는 **사람이 하는 일**이다 — 밖으로 나가는 동작을 도구가 대신 하지 않는다."""
    source = SCRIPT.read_text()
    assert '"push"' not in source and "git push" not in source


def test_naming_a_revision_explicitly_does_not_refuse_but_says_what_is_left_out(
        repo: Path, capsys):
    """`--from <브랜치>` 는 그 리비전을 담는 것이 맞다 — 다만 사람이 기대하는 것은
    보통 지금 고치고 있는 내용이므로 **다르다고 말한다.**"""
    module = _import()
    (repo / "mission_runtime" / "edited.py").write_text("x = 1\n")

    assert dist(module, repo, "--from", "main", "--branch", "dist", "--write") == 0
    printed = capsys.readouterr().out
    assert "담지 않는다" in printed and "같은 커밋이다" in printed
    assert "edited.py" not in run(repo, "ls-tree", "-r", "--name-only", "dist")
