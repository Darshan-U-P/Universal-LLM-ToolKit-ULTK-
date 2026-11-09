# Approval, Audit and Workflow Orchestration

This increment adds persistent approval decisions, a tamper-evident audit trail, and dependency-aware workflows. It does not provide an OS sandbox or replace host-level access controls.

## Exact-argument approval

Wrap an existing policy in `ApprovalPolicy` and configure capability names requiring a human decision:

```python
from ultk.approvals import ApprovalPolicy, SQLiteApprovalStore
from ultk.permissions import AllowListPolicy

store = SQLiteApprovalStore("./state/approvals.sqlite3", ttl_seconds=600)
policy = ApprovalPolicy(
    AllowListPolicy({"filesystem.write_file", "development.deploy"}),
    store,
    approval_capabilities={"filesystem:write", "development:deploy"},
)
```

The first invocation creates a pending request and returns an error result containing `approval_id`. A trusted application surface displays the request to an authorized person and calls `store.decide(id, approved=True, actor="...")`. The model retries the same tool with the exact arguments. Approval is one-time, session-bound, tool-bound, argument-digest-bound and expires. Changed arguments require new approval. The library deliberately exposes no approval-decision tool to the model.

The approval store persists hashes and metadata, not raw argument values. The application must present a safe, redacted summary and authenticate the approving actor.

## Audit trail

Attach `SQLiteAuditLogger` to `ToolDispatcher` or configure it through `ToolEngine`. Each event records tool, session, outcome, argument digest, argument key names, capability names and approval reference. Raw argument values and tool outputs are not written. `verify()` checks the append-only hash chain.

The hash chain is tamper-evident, not tamper-proof: an attacker able to rewrite the database and recompute every hash can forge it. Protect the database with OS permissions and backups; production deployments should forward events to an independently protected log service.

## Workflow DAG

`WorkflowEngine` executes a static directed acyclic graph. Independent ready steps run concurrently up to a configured limit. Dependencies are explicit, and outputs are referenced using a whole-value object such as `{"$ref": "step_id#/field"}`; references are never evaluated as code or interpolated into arbitrary strings. Cycles, unknown dependencies and invalid references fail closed. Failed dependencies cause dependent steps to be skipped. Each actual tool call passes through normal schema, policy, approval, timeout and audit gates.

Workflow steps are static data, not a programming language. External side effects are not transactional; use idempotent tools and compensating actions where needed.

## Remaining security verification

- Authenticate and authorize the human approval UI/API; the library only stores the actor label supplied by the host.
- Protect approval and audit databases with restrictive OS permissions and encrypted backups where required.
- Validate concurrency, cancellation, retries and failure recovery under load.
- Add OS/container isolation for untrusted commands, compilers, package installation, browser sessions and deployment scripts.
- Add process-wide rate limits, resource quotas and distributed coordination before multi-worker production use.
