# Contributing

ULTK is at the architecture and foundation stage. Contributions should preserve provider abstraction, stable tool contracts, explicit security boundaries, and testability.

## Expectations

- Discuss substantial design changes before implementing them.
- Keep provider-specific behavior inside provider adapters.
- Keep integrations independently testable and packageable.
- Never execute untrusted model output as code.
- Add tests for validation, authorization, failure paths, cancellation, and limits.
- Never commit credentials, tokens, user data, or generated secret files.
- Update architecture and tool-catalog documentation when contracts change.

## Pull requests

Describe the problem, design, security implications, compatibility impact, and tests run. Distinguish implemented behavior from planned behavior. Keep PRs focused.
