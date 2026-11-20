"""배포 브랜치를 **현재 공개 범위 그대로** 만든다.

implements: AI-B-02 (실행환경 패키징·재현성), AI-C-16 (폐쇄망 조달 — 받는 쪽이
            외부 연결 없이 트리를 갖는다)
관련: AI-B-05 (last-known-good — 옛 배포 커밋은 지우지 않는다)
tests: tests/test_make_dist.py

## 무엇을 하나

공개 범위는 `.gitignore` 가 아니라 **푸시 범위**가 정한다 — `mission_runtime/` 만
올린다(CLAUDE.md §0). 그래서 다른 기계가 받는 트리는 "작업 저장소에서 폴더 하나만
떼어낸 것" 이고, 그 떼어내는 일을 손으로 하면 매번 다르게 떼어낸다. 이 도구는
그것을 한 가지 방법으로 고정한다.

**정본을 새로 만들지 않는다.** 무엇이 공개 대상인지는 `git ls-files mission_runtime`
가 이미 답하고 있고(`tests/test_publishable_surface.py` 가 같은 것을 본다), 이
도구는 그 목록이 가리키는 트리를 그대로 옮긴다. 목록을 다시 세우면 두 곳이 갈라지고,
갈라지는 날 비밀정보가 들어가는 쪽은 언제나 시험이 보지 않는 쪽이다.

## 커밋되지 않은 작업은 **거절한다**

배포 트리는 `HEAD` 의 `mission_runtime/` 에서 나온다. 작업 트리에 커밋되지 않은
변경이 있으면 그것은 배포 커밋에 들어가지 않고, **들어가지 않았다는 사실도 보이지
않는다** — 받는 쪽은 "최신" 이라고 믿는다. 그래서 더럽히지 않고 거절하고, 무엇이
남았는지 센다. 억지로 담을 수 있게 하지 않은 이유는 그렇게 만든 트리가 작업 저장소의
어느 커밋에도 없어서 "어디서 나왔나" 에 답할 수 없기 때문이다.

## 역사를 고치지 않는다

새 커밋을 배포 브랜치 **위에** 올린다(parent = 그 브랜치의 현재 머리). 옛 배포
커밋은 그대로 남고, 되돌리는 것은 `git update-ref` 한 줄이다 — 이 도구는 움직이기
전 SHA 를 찍는다.

## 작업 트리를 건드리지 않는다

`git checkout` 을 하지 않는다. 임시 색인(`GIT_INDEX_FILE`)과 plumbing
(`mktree` · `commit-tree` · `update-ref`)만 쓰므로, 돌리는 동안 손에 들고 있던
파일이 바뀌지 않는다. 브랜치를 옮기는 것은 `--write` 를 **명시해야** 한다.

    python tools/release/make_dist.py                  # 무엇을 할지 보기만 한다
    python tools/release/make_dist.py --export /tmp/d  # 그 트리를 꺼내 본다
    python tools/release/make_dist.py --write          # 브랜치를 옮긴다(푸시는 안 한다)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

#: 공개 대상 폴더. 하나다 — 늘어나면 CLAUDE.md §0 의 푸시 범위가 먼저 바뀐다.
PUBLIC_DIR = "mission_runtime"
#: 공개 트리가 올라가는 브랜치. 팀 저장소의 `jny_AI` 가 **`mission_runtime/` 하나만**
#: 담고 있고, 이 도구가 그 모양 그대로 새 커밋을 올린다. 2026-11-20 까지는 별도
#: `jny_opensource-dist` 브랜치가 그 일을 했는데, 같은 트리를 담는 브랜치가 둘이면
#: 받는 쪽이 어느 것을 봐야 하는지 알 수 없어서 지웠다 — 받는 쪽은 `jny_AI` 하나다.
#: 로컬에서는 그 원격 브랜치를 가리키는 이름을 쓴다(`git branch upstream-jny_AI
#: upstream/jny_AI`).
DEFAULT_BRANCH = "upstream-jny_AI"

#: 거절 사유. 문구가 아니라 토큰이다.
REASON_DIRTY = "uncommitted_changes_in_public_tree"
REASON_NO_PUBLIC_TREE = "public_dir_not_in_source_commit"
REASON_UNKNOWN_SOURCE = "source_revision_not_found"
REASON_LIST_MISMATCH = "tree_does_not_match_tracked_file_list"


class DistError(RuntimeError):
    """만들 수 없다. **조용히 좁은 쪽을 쓰지 않는다.**"""


def git(*args: str, repo: Path, stdin: str | None = None,
        env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin, capture_output=True, text=True,
        env={**os.environ, **(env or {})},
    )
    if done.returncode != 0:
        raise DistError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def repo_root(start: Path | None = None) -> Path:
    here = start or Path(__file__).resolve().parents[2]
    return Path(git("rev-parse", "--show-toplevel", repo=here).strip())


def dirty_paths(repo: Path) -> tuple[str, ...]:
    """공개 폴더 안의 커밋되지 않은 변경. **이름을 돌려준다** — 수만 세면 무엇을
    커밋해야 하는지 알 수 없다."""
    out = git("status", "--porcelain", "--", PUBLIC_DIR, repo=repo)
    return tuple(line[3:].strip() for line in out.splitlines() if line.strip())


def names_head(repo: Path, source: str) -> bool:
    """그 리비전이 지금 `HEAD` 와 같은 커밋인가.

    `--from jny_AI` 처럼 **현재 브랜치를 이름으로** 주는 것이 흔한 실수다. 이름을
    주었으니 작업 트리는 무관한 것이 맞지만, 그때 사람이 기대하는 것은 보통 지금
    고치고 있는 내용이다 — 그래서 거절하지는 않고 **다르다고 말한다.**
    """
    try:
        return (git("rev-parse", source, repo=repo).strip()
                == git("rev-parse", "HEAD", repo=repo).strip())
    except DistError:
        return False


def public_tree_sha(repo: Path, source: str) -> str:
    """그 커밋의 `mission_runtime/` 트리 SHA."""
    try:
        git("rev-parse", "--verify", f"{source}^{{commit}}", repo=repo)
    except DistError as error:
        raise DistError(f"{REASON_UNKNOWN_SOURCE}:{source}") from error
    rows = git("ls-tree", source, PUBLIC_DIR, repo=repo).splitlines()
    for row in rows:
        meta, _, name = row.partition("\t")
        if name.strip() == PUBLIC_DIR:
            mode, kind, sha = meta.split()
            if kind != "tree":
                raise DistError(f"{REASON_NO_PUBLIC_TREE}:{kind}")
            return sha
    raise DistError(f"{REASON_NO_PUBLIC_TREE}:{source}")


def root_tree_for(repo: Path, tree_sha: str) -> str:
    """`mission_runtime/` **하나만** 담은 뿌리 트리를 만든다.

    배포 브랜치의 모양이 그렇다 — 받는 쪽이 `git clone` 하면 그 폴더 하나가 있고,
    그 안에서 `pyproject.toml` 과 `tools/install_check.sh` 가 바로 돈다.
    """
    return git("mktree", repo=repo,
               stdin=f"040000 tree {tree_sha}\t{PUBLIC_DIR}\n").strip()


def tracked_files(repo: Path, source: str) -> tuple[str, ...]:
    """공개 목록의 **정본**. 이 도구가 다시 세지 않는다."""
    out = git("ls-tree", "-r", "--name-only", source, PUBLIC_DIR, repo=repo)
    return tuple(sorted(line for line in out.splitlines() if line.strip()))


def verify(repo: Path, root_tree: str, source: str) -> int:
    """만든 트리가 공개 목록과 **글자 하나까지** 같은지 본다."""
    made = tuple(sorted(
        line for line in
        git("ls-tree", "-r", "--name-only", root_tree, repo=repo).splitlines()
        if line.strip()))
    expected = tracked_files(repo, source)
    if made != expected:
        only_made = sorted(set(made) - set(expected))[:5]
        only_expected = sorted(set(expected) - set(made))[:5]
        raise DistError(f"{REASON_LIST_MISMATCH}: +{only_made} -{only_expected}")
    return len(made)


def export(repo: Path, root_tree: str, target: Path) -> int:
    """그 트리를 디렉터리로 꺼낸다. **작업 트리를 쓰지 않는다** — 임시 색인이다."""
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as hold:
        index = str(Path(hold) / "index")
        git("read-tree", root_tree, repo=repo, env={"GIT_INDEX_FILE": index})
        git("checkout-index", "-a", "-f", f"--prefix={target.as_posix()}/",
            repo=repo, env={"GIT_INDEX_FILE": index})
    return sum(1 for path in target.rglob("*") if path.is_file())


def move_branch(repo: Path, branch: str, root_tree: str, source: str,
                message: str) -> tuple[str | None, str]:
    """배포 브랜치를 새 커밋으로 옮긴다. **푸시하지 않는다.**"""
    try:
        before = git("rev-parse", "--verify", f"refs/heads/{branch}", repo=repo).strip()
    except DistError:
        before = None            # 아직 없는 브랜치를 만드는 것도 정상이다
    args = ["commit-tree", root_tree]
    if before:
        args += ["-p", before]
    new = git(*args, "-m", message, repo=repo).strip()
    git("update-ref", f"refs/heads/{branch}", new, repo=repo)
    return before, new


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--from", dest="source", default="HEAD",
                        help="어느 커밋의 공개 폴더를 담을까 (기본 HEAD)")
    parser.add_argument("--export", type=Path,
                        help="그 트리를 이 디렉터리로 꺼낸다 (브랜치는 건드리지 않는다)")
    parser.add_argument("--write", action="store_true",
                        help="배포 브랜치를 실제로 옮긴다. 푸시는 하지 않는다")
    parser.add_argument("--message", default=None)
    args = parser.parse_args(argv)

    repo = repo_root()
    print(f"저장소     : {repo}")
    print(f"담을 것    : {args.source}:{PUBLIC_DIR}/")

    left = dirty_paths(repo)
    if left and args.source != "HEAD":
        # 리비전을 이름으로 주었으므로 담는 것은 그 리비전이다. 거절하지 않는다.
        same = " (지금 HEAD 와 같은 커밋이다)" if names_head(repo, args.source) else ""
        print(f"[~] 공개 폴더에 커밋되지 않은 변경 {len(left)}건이 있고 "
              f"**담지 않는다**{same} — 담을 것은 {args.source} 다")
        left = ()
    if left:
        print(f"\n[x] {REASON_DIRTY} — 공개 폴더에 커밋되지 않은 변경 {len(left)}건")
        for path in left[:10]:
            print(f"    {path}")
        if len(left) > 10:
            print(f"    … 외 {len(left) - 10}건")
        print("\n배포 트리는 HEAD 에서 나온다. 지금 올리면 이 변경들은 들어가지"
              " 않고,\n들어가지 않았다는 사실도 받는 쪽에 보이지 않는다."
              " 먼저 커밋한다.")
        return 2

    tree = public_tree_sha(repo, args.source)
    root = root_tree_for(repo, tree)
    count = verify(repo, root, args.source)
    print(f"공개 파일  : {count}개 (git ls-files 와 일치)")
    print(f"뿌리 트리  : {root}")

    if args.export:
        wrote = export(repo, root, args.export)
        print(f"꺼냈다     : {args.export} ({wrote}개 파일)")

    if not args.write:
        print("\n[~] 보기만 했다. 브랜치를 옮기려면 --write")
        return 0

    source_sha = git("rev-parse", "--short", args.source, repo=repo).strip()
    message = args.message or (
        f"chore(dist): {PUBLIC_DIR}/ at {source_sha}\n\n"
        f"tools/release/make_dist.py 가 만든 커밋이다. 담은 것은 "
        f"{args.source}({source_sha}) 의 {PUBLIC_DIR}/ 뿐이고 파일 {count}개다.\n"
        f"공개 목록의 정본은 git ls-files 이며 이 도구는 그것을 다시 세지 않는다."
    )
    before, new = move_branch(repo, args.branch, root, args.source, message)
    print(f"\n[o] {args.branch}: {before or '(없었다)'} → {new}")
    print(f"    되돌리기: git update-ref refs/heads/{args.branch} {before}"
          if before else "    되돌리기: git branch -D " + args.branch)
    print("    푸시는 하지 않았다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
