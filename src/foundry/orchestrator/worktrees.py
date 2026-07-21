from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Environment variables git uses to pin repo/worktree/index discovery. Git sets
# these (GIT_DIR in particular) when invoking hooks from a linked worktree, so
# that the hook script operates on the right worktree — but that means any
# subprocess a hook spawns (e.g. `pytest`, and in turn a test that shells out
# to `git -C <some other repo>`) inherits them too, and `-C` does NOT override
# an inherited GIT_DIR: git prefers the env var over the `-C`-discovered repo.
# Without stripping these, every `git -C project_path ...` call below would
# silently operate on whatever repo the *calling* process happened to be
# inside, not `project_path` — this bit us for real once (a leaked GIT_DIR
# from this repo's own pre-commit hook caused a WorktreeManager test to run
# `git worktree add`/`git commit` against this repo instead of a throwaway
# tmp repo). Always pass `env=_git_env()` so `-C` is authoritative.
_REPO_SCOPED_GIT_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_PREFIX",
)


def _git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _REPO_SCOPED_GIT_ENV_VARS}


class WorktreeManager:
    """Thin, synchronous wrapper over local `git worktree` operations.

    Each unit that runs a `writes=true` step gets its own git worktree, checked
    out on a dedicated branch `foundry/<run_id>/<unit_id>`, so concurrent units
    never contend over the same working tree. No network calls are made — this
    is purely local git plumbing against `project_path`.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def create(self, project_path: str, run_id: str, unit_id: str) -> str:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = self.base_dir / run_id / unit_id
        branch = f"foundry/{run_id}/{unit_id}"
        subprocess.run(
            ["git", "-C", project_path, "worktree", "add", str(worktree_path), "-b", branch],
            check=True,
            capture_output=True,
            env=_git_env(),
        )
        return str(worktree_path)

    def remove(self, project_path: str, worktree_path: str) -> None:
        # The branch name must be looked up *before* `worktree remove` runs —
        # once the worktree is removed, `git worktree list` no longer has an
        # entry to resolve it from.
        branch = self._branch_for(project_path, worktree_path)
        subprocess.run(
            ["git", "-C", project_path, "worktree", "remove", "--force", worktree_path],
            check=True,
            capture_output=True,
            env=_git_env(),
        )
        if branch is not None:
            subprocess.run(
                ["git", "-C", project_path, "branch", "-D", branch],
                check=False,
                capture_output=True,
                env=_git_env(),
            )

    def _branch_for(self, project_path: str, worktree_path: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", project_path, "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        blocks = result.stdout.split("\n\n")
        # git reports worktree paths canonicalized (symlinks resolved) in this
        # output -- e.g. on macOS, /var is itself a symlink to /private/var, so
        # a path built from a `tmp_path`-style fixture under /var/folders/...
        # comes back from git as /private/var/folders/.... Comparing the raw,
        # unresolved `worktree_path` against that would never match, silently
        # skipping branch deletion below -- which left a stale branch behind
        # and made every *second* `create()` for the same run_id/unit_id (the
        # exact case a gate-rejection rework hits, once the worktree from the
        # first attempt has already been cleaned up) fail with "fatal: a
        # branch named '...' already exists". Resolve both sides so the
        # comparison is symlink-agnostic.
        target = str(Path(worktree_path).resolve())
        for block in blocks:
            lines = block.splitlines()
            if not lines or not lines[0].startswith("worktree "):
                continue
            reported_path = Path(lines[0].removeprefix("worktree "))
            if str(reported_path.resolve()) != target:
                continue
            for line in lines:
                if line.startswith("branch refs/heads/"):
                    return line.removeprefix("branch refs/heads/")
        return None
