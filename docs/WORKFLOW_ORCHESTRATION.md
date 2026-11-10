# Workflow Orchestration

ULTK workflows are static, bounded directed acyclic graphs (DAGs). They run through the same ToolDispatcher used by direct tool calls, so schema validation, capability policy, tool timeouts, and normalized results are retained. The workflow engine is LLM-independent.

## Quick start

    from ultk import ToolEngine, WorkflowStep

    engine = ToolEngine(policy=my_policy)
    workflow = engine.create_workflow_engine(
        database='./state/workflows.sqlite3', max_steps=100, max_concurrency=4
    )
    run_id = workflow.submit([
        WorkflowStep('lookup', 'data.lookup', {'query': 'release notes'}),
        WorkflowStep(
            'summarize', 'documents.summarize',
            {'document': {'$ref': 'lookup#/document'}},
            depends_on=('lookup',), max_attempts=3, retry_delay_seconds=1.0,
        ),
    ])
    result = await workflow.run(run_id, session_id='session-123',
        granted_capabilities=frozenset({'data:read', 'documents:read'}))

## Execution model

- Each step has a unique ID, registered tool name, JSON-compatible arguments, explicit dependencies, retry limit (1–10 attempts), and bounded retry delay (0–300 seconds).
- A step becomes eligible only after every dependency succeeds. Independent ready steps run concurrently up to configured concurrency (1–64).
- Failed dependencies cause downstream steps to be skipped. Independent branches continue unless fail_fast=True.
- Argument references use the explicit object form {"$ref": "step-id#/json/pointer"}. References must point to an ancestor declared in depends_on; expressions and code evaluation are never supported.
- Tool calls use the normal dispatcher, including schema validation, authorization, timeout and output normalization.

## Persistence, recovery and replay

SQLite stores the immutable workflow definition, each step's status/attempt count/output/error, run status, and ordered event history. Inspect progress with get(run_id) and get_events(run_id), request cooperative cancellation with cancel(run_id), or recover a run after process interruption with recover(run_id).

recover resets orphaned running steps to pending. This is at-least-once recovery: a process can crash after a tool has performed an external side effect but before its result is checkpointed. That step may execute again. Use idempotent tools or tool/provider idempotency keys for external mutations. Recovery must only be called after the previous worker is known to have stopped; distributed worker leasing/coordination is not implemented.

replay(run_id) creates a new run from the saved definition and executes the tools again. It is not deterministic playback of recorded side effects. The event log is an execution trace for inspection, not a guarantee that external systems can be rolled back.

## Cancellation and failure semantics

Cancellation is cooperative at workflow scheduling boundaries. Already-running tool calls are allowed to finish; the engine then marks remaining work cancelled. Tool-level deadlines still apply. Retries use bounded exponential backoff and are persisted between attempts. A retry does not make a non-idempotent operation safe.

A workflow is successful only when all steps succeed. Failed steps or dependency-skipped steps produce a failed run. A workflow that is cancelled is marked cancelled.

## Security and operational boundaries

- Workflows cannot bypass the dispatcher's policy or capabilities.
- The workflow definition is data, not executable code. No arbitrary Python, shell, or expression evaluation is provided.
- The workflow database contains tool arguments and outputs, which may contain sensitive data. Protect its filesystem permissions, retention, backups, and encryption at rest at the host layer.
- The engine does not create a daemon or background worker. The host explicitly submits, runs, resumes, and monitors workflows.
- Human approval UI, distributed workers, global rate limiting, resource quotas, compensation transactions, and exactly-once external side effects are not provided by this increment.

## Validation status

Tests are authored in tests/test_orchestration.py. As required by the current project policy, tests, Ruff, packaging, and integration checks are deferred and must not be reported as passing.