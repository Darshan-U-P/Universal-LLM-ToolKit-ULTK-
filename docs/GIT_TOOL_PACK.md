# Git Tool Pack

ULTK's Git Tool Pack is a repository-scoped Git workflow API. It provides fixed, typed operations instead of arbitrary Git command execution.

## Installation

    from ultk import ToolEngine

    engine = ToolEngine(policy=your_permission_policy)
    engine.install_git_tools(
        repository_root="./my-project",
        allowed_remote_hosts={"github.com", "gitlab.com"},
    )

The configured directory must be the top-level directory of an existing Git working tree. Remote operations are disabled unless the host explicitly supplies an HTTPS hostname allowlist. Credentials are never accepted as tool arguments; configured Git credential helpers remain host-managed.

## Tool families

| Area | Operations |
|---|---|
| Inspection | repository status/metadata, local and remote branches, remotes, tags |
| Branches | create, switch, rename, safely delete (merged branches only) |
| Index and commits | stage selected paths, unstage, commit |
| Diffs | working tree, staged index, commit-to-commit, optional file filter |
| Merge | start non-committing merge, abort, complete after conflict resolution |
| Conflicts | list unmerged paths/index stages; resolve individual paths with ours, theirs or explicit UTF-8 content |
| History | bounded log, commit summary, line blame |
| Remotes | list/add/change/remove; fetch, pull (merge/rebase/ff-only), push |

## Security model

- The repository root is fixed by the host and each file path is repository-relative.
- No raw shell, arbitrary Git subcommand, arbitrary Git option, or caller-selected executable is exposed.
- Git is invoked with argument arrays and shell execution disabled; output and execution time are bounded.
- Git hooks are disabled for tool-invoked operations. External diff/textconv are disabled.
- Remote operations accept HTTPS only, reject embedded URL credentials, and require the hostname to match the host-configured allowlist. Only standard HTTPS port 443 is accepted.
- The host's Git credential manager may still be used for authentication. Treat credential-helper configuration as trusted host configuration.
- Each mutating family has a distinct capability (for example git:commit, git:merge, git:remote:push) so the host can require explicit approval.
- Branch deletion uses safe branch deletion; force deletion, hard reset, clean, cherry-pick, tag mutation and submodule operations are not exposed in this increment.

## Operational cautions

Git is a powerful local executable and repository configuration is executable-adjacent. Do not point this tool pack at untrusted repositories without an OS-level sandbox. Repository-local filters and credential-helper configuration must be treated as trusted host configuration. Remote fetch/pull/push contact external systems and may change local or remote refs. Use human approval for commits, merges, conflict resolutions, remote configuration, pull and push.

The conflict resolver does not invent a semantic merge. Ours and theirs select one side for one file; manual writes explicitly supplied UTF-8 content and stages it. Review the resulting diff before completing the merge.

## Deliberately not included yet

Rebase orchestration, cherry-pick, revert, stash, worktrees, submodules, tag creation/deletion, signed commits, GPG/SSH key management, Git LFS, GitHub/GitLab PR/issue APIs, and graphical merge tooling remain separate future increments.
