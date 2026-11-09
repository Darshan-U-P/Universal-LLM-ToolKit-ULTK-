# Plugin Development — Design

The plugin loader and SDK are not implemented yet. This document defines intended conventions.

## Plugin metadata

A plugin should declare:
- unique plugin ID and semantic version;
- summary and supported toolkit API range;
- dependencies and configuration requirements;
- tool definitions, input/output schemas, and capability requirements;
- execution mode, limits, sensitivity, and lifecycle hooks;
- tests and documentation.

## Registration is not permission

Discovery or installation must not enable tools or grant capabilities automatically. The application explicitly enables plugins, supplies credential references, and grants narrow permissions.

## Naming

Use stable namespaced tool IDs such as `filesystem.read_file`, `web.fetch_url`, and `documents.extract_pdf`. Avoid ambiguous names such as `read` or `execute`.

## Compatibility and isolation

Validate metadata and dependencies before loading. Prefer out-of-process execution for third-party or untrusted plugins. Treat plugin outputs as untrusted and apply normalization and size limits.
