# Architecture

## Components

### Toolkit facade
Application-facing interface for configuration, initialization, enabled tools, task execution, and structured results.

### Provider adapters
Own provider authentication, request/response translation, tool-schema adaptation, streaming, capability reporting, and retry classification. The orchestrator depends only on internal contracts. Model capabilities must be negotiated rather than assumed.

### Agent orchestrator
Owns the bounded task loop: assemble context, select eligible tools, call the model, parse proposed calls, request execution, return results, and decide whether to continue, stop, or request human input.

### Tool registry
Stores stable tool ID, version, description, input/output schemas, capability declarations, configuration requirements, execution mode, and metadata. Discovery is separate from execution.

### Policy and permission gate
Evaluates application/user grants, tool capabilities, argument-level constraints, approval rules, and execution context before dispatch.

### Execution runtime
Runs tools with deadlines, cancellation, concurrency/resource controls, normalized errors, and structured telemetry. Local, remote, and sandboxed execution are separate modes.

### Memory and persistence
Optional interfaces for conversation state, checkpoints, and retrieval. Memory is scoped and is never an implicit authorization source.

## Tool contract

A tool definition includes:
- stable namespaced identifier and version;
- human-readable description;
- JSON-Schema-compatible input and output contracts;
- declared capability requirements;
- credential/configuration references, never raw secret values;
- execution mode and resource limits;
- sensitivity classification.

An invocation includes call ID, tool ID/version, validated arguments, caller/session context, deadline, and cancellation signal.

A result is a typed success/error envelope with call ID, bounded content, structured metadata, and safe-to-log diagnostics.

## State machine

`PROPOSED -> VALIDATED -> AUTHORIZED -> AWAITING_APPROVAL (optional) -> RUNNING -> SUCCEEDED | FAILED | CANCELLED | TIMED_OUT`

Invalid or denied calls terminate before execution. Tool output is untrusted data and must be bounded and labeled.

## Plugin boundary

Registration, enablement, configuration, and authorization are separate steps. Installing or discovering a plugin does not grant its capabilities. Validate plugin versions and dependencies before activation; prefer out-of-process execution for third-party code.

## Execution modes

- **In-process:** trusted, short-running operations only.
- **Subprocess/container:** untrusted or resource-intensive code with filesystem, network, CPU, memory, time, and output restrictions.
- **Remote:** separately authenticated services with transport security, timeouts, and narrow scopes.

Execution mode is chosen by runtime policy and tool requirements, not by the model.
