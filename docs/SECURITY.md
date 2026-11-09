# Security Model

## Threat model

ULTK processes untrusted user instructions, model-generated tool proposals, plugin metadata/code, remote API responses, and fetched documents. None should bypass application policy. Tool output is data, not privileged instructions.

## Required controls

1. Authorize before execution: validate tool identity, schema, capabilities, user grants, and policy.
2. Apply least privilege: narrow resource scopes and distinguish read from write access.
3. Require human approval for destructive, externally visible, financial, account-changing, or high-impact actions.
4. Isolate untrusted code and risky third-party plugins with filesystem, network, CPU, memory, time, and output limits.
5. Use secret-store/environment references; never serialize secrets into prompts, logs, traces, or source control.
6. Bound input/output sizes, runtime, retries, concurrency, and accumulated context.
7. Treat webpages, documents, and tool outputs as data; defend against prompt injection by maintaining instruction/data separation.
8. Audit actor, tool/version, decision, approval, timestamps, and outcome while redacting sensitive values.
9. Propagate deadlines and cancellation across orchestration and execution.
10. Default to no unrestricted shell, arbitrary code, or broad filesystem/network access.

## Approval is not authentication

A model request does not prove identity or user intent. Approval must come from the application/user control plane and be bound to the exact action and arguments. Any argument change requires a new authorization decision.
