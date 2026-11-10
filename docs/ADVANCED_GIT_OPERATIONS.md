# Advanced Git Operations Tool Pack

The optional advanced Git pack extends the existing development tools with bounded, structured
history operations, stashes, worktrees, submodules, conflict inspection/resolution and pull-request
integration.

## Installation

    from ultk.engine import ToolEngine

    engine = ToolEngine(policy=your_policy)
    engine.install_advanced_git_tools(
        project_root="/workspace/project",
        worktree_root="/workspace/project-worktrees",
        allowed_submodule_hosts=("github.com", "gitlab.com"),
        pull_request_adapter=your_trusted_pr_adapter,  # optional
    )

Git must be installed and available on the host PATH. No GitPython dependency is required. The
pack uses Python's subprocess API with fixed Git argument arrays and never invokes a shell.
The configured project root must be the repository root. The default worktree directory is a
sibling of the repository, named <repo>.ultk-worktrees.

## Tool surface

| Tool | Operations |
|---|---|
| git.history | Rebase, rebase continue/abort/skip, cherry-pick one or more commits, cherry-pick continue/abort/skip, revert one or more commits, revert continue/abort/skip |
| git.stash | Push, list, show, apply and pop |
| git.stash_drop | Drop one explicitly selected stash |
| git.worktree | List, add, move, lock, unlock and prune |
| git.worktree_remove | Remove one explicitly selected worktree; no force removal |
| git.submodule | Status, add from an allowlisted host, update using checkout strategy, sync |
| git.submodule_deinit | Deinitialize one explicitly selected submodule |
| git.conflict_inspect | List unmerged paths and inspect index stages |
| git.conflict_resolve | Select ours/theirs/current working-file content and stage that path |
| git.pull_request_read | Inspect PR, list reviews/comments and inspect checks |
| git.pull_request_write | Create/update/comment/review/close; does not merge |
| git.pull_request_merge | Merge with an expected head SHA to prevent stale-head merges |

Rebase supports standard non-interactive rebase and optional --rebase-merges. Interactive
rebase todo editing is intentionally not exposed. There is no force-push operation. Cherry-pick
and revert accept up to 20 explicit commit revisions per call. History-changing starts require a
clean worktree and index and reject conflicting in-progress Git operations. Continue/skip/abort
actions are accepted only when the corresponding operation is detected.

Conflict resolution only selects and stages a path. It does not claim semantic correctness or
automatically continue the rebase/merge/cherry-pick/revert. The caller must inspect the resulting
diff and explicitly continue the operation.

## Pull-request adapter

ULTK does not bundle GitHub/GitLab credentials or a network client. The host may inject a trusted
callable with this contract:

    def pull_request_adapter(action: str, payload: dict) -> dict:
        # Perform an allowlisted provider API operation and return JSON-compatible data.
        ...

Read actions are inspect, list_reviews, list_comments, and checks. Write actions are
create, update, comment, review, and close. Merge is a separate action and tool.
The adapter must enforce provider permissions, repository allowlists, payload validation,
pagination and rate limits. It must treat PR content, comments, review text and check output as
untrusted data. The merge tool supplies an expected 40-character head SHA; the adapter must use
the provider's compare-and-swap/expected-head mechanism where available.

## Capabilities

- git:history:mutate
- git:stash:mutate
- git:destructive — stash drop, worktree removal and submodule deinitialization
- git:worktree:mutate
- git:submodule:mutate
- git:conflict:read
- git:conflict:resolve
- git:pull_request:read
- git:pull_request:write
- git:pull_request:merge

Use a deny-by-default policy. The host policy should require explicit human approval bound to the
exact repository, operation and arguments for destructive actions and PR merges. Do not grant the
destructive or merge capabilities merely because the model requested them.

## Safety boundaries

- All paths for submodule and worktree operations are confined to host-configured roots. Worktree
  add/move destinations must not already exist.
- Submodule add and update validate direct .gitmodules URLs against exact host allowlists.
  Recursive submodule fetching is deliberately not enabled; nested submodules require a separate
  review and operation.
- History starts refuse a dirty index/worktree rather than silently stashing or discarding changes.
- Stash drop, worktree remove and submodule deinit are separate destructive tools.
- Git output is capped. Commands have fixed timeouts and do not accept shell strings.
- Git hooks, filters, credential helpers, external diff/merge drivers and other repository/user
  Git configuration may execute code with the host user's privileges. This pack is not a sandbox.
  Use a disposable container/VM and restrict network access for untrusted repositories.
- Git's own safety checks remain authoritative for locked, dirty or currently checked-out worktrees.
- A successful Git process exit code does not prove a change is correct; inspect status and diff.
- The PR adapter is trusted host code. Protect its credentials, restrict its repository scope,
  enforce rate limits and require approval for merge/close/review operations as appropriate.

## Not implemented

- Interactive rebase todo construction/editing.
- Force push, hard reset, clean, branch deletion or automatic recovery from arbitrary repository
  corruption.
- Automatic semantic conflict resolution.
- PR merge queue management, branch protection bypass, reviewer identity impersonation or
  approval-policy bypass.
- A built-in GitHub/GitLab HTTP client or credential vault.
- OS/container sandboxing for Git hooks, filters, submodule code or external helpers.

## Validation status

Focused tests are authored in tests/test_git_operations.py. Under the current implementation
phase, tests and CI are deferred; no passing result is claimed. Validate Git-version differences,
rebase/cherry-pick/revert conflicts, linked worktree lifecycle, Windows path behavior, submodule
host enforcement, Git hooks/configuration, and live PR adapter permissions before production use.
