# Allowlisted REST Integrations

ULTK can expose configured REST APIs and webhook endpoints without allowing the model to supply arbitrary hosts, credentials or request headers.

## Configure from trusted host code

```python
engine.install_rest_tools(
    {
        "crm": {
            "base_url": "https://api.example.com/v1",
            "allowed_path_prefixes": ["contacts", "accounts"],
            "write_methods": ["POST", "PATCH"],
            "token_env": "CRM_API_TOKEN",
        }
    },
    allow_writes=False,
)
```

For each configured endpoint, ULTK registers a GET tool. Mutation tools are registered only when the host sets `allow_writes=True` and explicitly configures allowed methods from POST, PUT, PATCH and DELETE. The matching capabilities are `integration:http:read` and `integration:http:write`.

Credentials are read from host environment variables at execution time. The model cannot provide authorization headers or override fixed host-configured headers. Request paths are relative to the configured HTTPS base URL and must match configured path prefixes. Redirects must remain on the same host, port and allowed path scope. Environment proxies are disabled for these requests. Request bodies and response payloads are size-bounded.

## Limitations

- This is a generic REST/webhook transport, not a complete OAuth authorization-code/refresh-token implementation or vendor-specific connector.
- The host is responsible for storing and rotating credentials securely and granting tool capabilities narrowly.
- Hostname checks and redirect restrictions are defense in depth; they do not pin DNS resolutions or replace network egress policy.
- No automatic retries are performed for non-idempotent operations.
- API-specific pagination, rate-limit handling, webhook signature verification and schema discovery remain future work.
