# Roadmap

## Milestone 0 — Repository and architecture
- [x] Establish repository baseline and project vision
- [x] Document architecture, security, tool domains, and roadmap
- [ ] Agree initial contracts and package metadata

## Milestone 1 — Core contracts
- [ ] Shared types, config, and typed result/error envelopes
- [ ] Provider adapter protocol and mock provider
- [ ] Tool protocol, metadata, JSON Schema validation
- [ ] Registry and deterministic discovery
- [ ] Authorization and human-approval interfaces
- [ ] Dispatcher with deadlines, cancellation, resource/output limits
- [ ] Unit tests and CI

## Milestone 2 — End-to-end runtime
- [ ] First hosted provider and second provider
- [ ] Bounded tool-calling loop
- [ ] Provider schema translation
- [ ] Read-only web fetch and filesystem tools
- [ ] Sandboxed code execution prototype
- [ ] Structured tracing and usage events

## Milestone 3 — Integrations
- [ ] Browser automation, documents, structured data
- [ ] SQL database adapters and Git/development tools
- [ ] Plugin packaging, discovery, compatibility validation

## Milestone 4 — Advanced runtime
- [ ] Parallel and dependency-aware workflows
- [ ] Persistent checkpoints and resumable tasks
- [ ] Human approvals, agent delegation, scheduled tasks
- [ ] Replayable traces and budget controls

## Milestone 5 — Ecosystem
- [ ] TypeScript SDK and REST API
- [ ] Plugin catalog and developer documentation
- [ ] Distributed workers and additional integrations

Roadmap items are not considered implemented until code, tests, and documentation are merged.
