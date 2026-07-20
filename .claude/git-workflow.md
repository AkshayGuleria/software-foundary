# Git Workflow Guide

Single-operator + subagent-driven-development workflow — one worktree and branch per
implementation plan (a milestone or sub-milestone), not per task. This is the pattern
actually used to ship M0 durable core; keep using it.

---

## Branch strategy

**One branch per plan, not per task.** A plan (`docs/superpowers/plans/YYYY-MM-DD-<slug>.md`)
covers a milestone's worth of tasks; all of them land on one branch, one commit per task
(plus extra `fix:` commits from review rounds), then the whole branch merges to master
at once after the final whole-branch review passes.

**Branch name = plan slug:** `<slug>` from the plan filename, e.g. `m0-durable-core`.

**Never commit directly to master** for anything beyond a trivial one-line doc/config fix.
Everything that touches `src/` or `tests/` goes through a plan branch.

---

## Workflow

### 1. Start a plan

```bash
# superpowers:writing-plans produces docs/superpowers/plans/YYYY-MM-DD-<slug>.md
# superpowers:using-git-worktrees creates the isolated workspace:
#   - native EnterWorktree if available (creates .claude/worktrees/<name>/ on a new branch)
#   - else: git worktree add .worktrees/<slug> -b <slug>
```

### 2. Work the plan (subagent-driven-development)

Per task: dispatch implementer subagent → task passes its own tests → task review
(spec compliance + code quality) → fix loop if Important/Critical findings → commit.

```bash
git add <files-for-this-task>
git commit -m "feat(scope): what this task added

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**Commit types:** `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`. Scope in
parens when it clarifies (`feat(store):`, `fix(orchestrator):`).

**Fix-round commits are separate commits**, not amended into the task's original commit
— the review history should stay legible (`git log` shows what a reviewer actually
caught and what was done about it).

### 3. Final whole-branch review

After every task's own review is clean, run one more review across the entire branch
diff (`base..HEAD`) before merging. This catches integration bugs no single task's
diff could show. If it finds Important/Critical issues, one more fix commit, one
re-review, then proceed.

### 4. Merge to master

```bash
# From the main checkout (never from inside the worktree being merged):
git checkout master
git pull                      # if a remote exists and is in use
git merge <slug> --no-edit    # regular merge — keep the task-by-task commit history
uv run pytest -v              # re-verify on the merged result before cleanup
```

If master has drifted with uncommitted local changes that conflict, resolve them first
(inspect with `git status`/`git diff`, never blind-discard) — see "Handling a dirty
master" below.

### 5. Clean up

```bash
git worktree remove .claude/worktrees/<slug>   # or .worktrees/<slug> for the git-fallback path
git worktree prune
git branch -d <slug>
```

Use `superpowers:finishing-a-development-branch` to drive steps 4-5 interactively —
it presents merge/PR/keep/discard as an explicit choice rather than assuming.

---

## Handling a dirty master

If `git merge` aborts because local uncommitted changes in master would be overwritten:
1. `git status` / `git diff <file>` — identify whose change it is and whether it's
   superseded by what's incoming.
2. If it's stray/superseded: `git restore <file>`.
3. If it's real in-progress work: commit or `git stash push -u -m "<label>"` it first,
   never discard without checking.

---

## Quick reference

```bash
# Start a plan
# (writing-plans skill writes the plan, using-git-worktrees creates the branch)

# Per task
git add <files>
git commit -m "feat(scope): summary"

# Merge (from main checkout)
git checkout master
git merge <slug> --no-edit
uv run pytest -v

# Clean up
git worktree remove <path> && git worktree prune
git branch -d <slug>
```

## Golden rules

1. Never commit directly to master for non-trivial changes.
2. One branch per plan; one commit per task within it.
3. Fix-round commits are new commits, never amends.
4. Run the final whole-branch review before merging, even if every task review was clean.
5. Verify tests on the merged result, not just on the branch, before cleanup.
6. `cd` to the main checkout before `git worktree remove` — never run it from inside
   the worktree being removed.
