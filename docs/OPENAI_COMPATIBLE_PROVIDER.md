# OpenAI-Compatible Provider Adapter

ULTK includes an adapter for OpenAI-compatible chat-completions endpoints. It can connect to hosted APIs and local inference servers that implement the same request/response contract.

## Hosted provider

```python
from ultk import OpenAICompatibleProvider, ToolKit

provider = OpenAICompatibleProvider(
    base_url="https://api.openai.com/v1",
    model="your-model",
    api_key_env="OPENAI_API_KEY",
)
toolkit = ToolKit(provider, policy=...)
```

## Local inference server

```python
provider = OpenAICompatibleProvider(
    base_url="http://127.0.0.1:11434/v1",
    model="your-local-model",
)
```

Only HTTPS remote endpoints and explicit loopback HTTP hosts are accepted. API keys are read from a host environment variable; the model cannot select the provider host or authorization header. Requests and responses are size-bounded, proxy environment settings are disabled, redirects are restricted to the same origin, and tool-call arguments are parsed into ULTK's provider-neutral `ToolCallRequest` contract. Tool schemas use the registry's OpenAI-compatible projection.

## Limitations

- Implements non-streaming chat completions only; no Responses API, streaming, vision payloads, audio, embeddings or provider-specific extensions.
- Provider-specific parameters and tool-choice modes are not yet negotiated.
- Local HTTP is accepted only for loopback; remote self-hosted servers must use HTTPS.
- No retries are performed. Rate-limit/backoff, token-usage accounting and provider capability discovery remain future work.
- A provider response is untrusted input; the normal ULTK schema, policy and approval gates still validate every proposed tool call.
