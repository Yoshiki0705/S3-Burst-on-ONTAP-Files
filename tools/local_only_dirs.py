"""Directories that only exist in a working copy and that tree-walking checks must skip.

Both are gitignored, so a clone and a CI runner never have them. When a check walks the
filesystem instead of asking git, a local run sees them anyway: an agent's workflow notes under
`.agents/` were linted and audited as if they were documentation, and a worktree cut under
`.worktrees/` is a full second copy of the tree, so every finding in it is reported twice. Either
way the gate fails locally and passes in CI for reasons unrelated to the change being checked.

One definition, imported by every walker, so that adding a directory here reaches all of them.
`.markdownlint-cli2.jsonc` cannot import this and lists the same two names; keep it in step.
"""

from __future__ import annotations

LOCAL_ONLY_DIRS = frozenset({".agents", ".worktrees"})
