# Secure SMTP Email Tool

ULTK includes a host-configured SMTP sender for plain-text email. The model supplies recipients, subject and body; SMTP host, sender identity, TLS mode, credentials and recipient allowlists are controlled by the host application.

## Configure

```python
engine.install_email_tools(
    host="smtp.example.com",
    port=465,
    from_address="notifications@example.com",
    username_env="SMTP_USERNAME",
    password_env="SMTP_PASSWORD",
    allowed_recipients={"operator@example.com"},
    allowed_domains={"example.com"},
    use_ssl=True,
)
```

The tool is `communication.send_email` and requires capability `communication:email:send`. It supports SMTP-over-TLS (typically port 465) or mandatory STARTTLS (typically port 587). Credentials are read from environment variables at execution time. Recipients must match the host-configured exact-address or domain allowlist. Messages are plain text, limited to 10 recipients, a 200-character subject and a 20,000-character body. Attachments, HTML, CC/BCC and arbitrary SMTP headers are not exposed.

For production, wrap the policy with `ApprovalPolicy` for `communication:email:send`; email is externally visible and should require a human approval bound to the exact recipient/subject/body arguments. Keep the SMTP credential environment restricted to the ULTK service account.

## Limitations

- SMTP only; no Gmail/Microsoft Graph API, OAuth flow, inbox reading, attachments or email search.
- No calendar, contacts, SMS, WhatsApp or meeting provider integration in this increment.
- Domain allowlists authorize every address at that domain; prefer exact recipient allowlists where possible.
- SMTP delivery acceptance is not proof of inbox delivery. The tool reports accepted/refused recipient counts only.
- Validate STARTTLS downgrade behavior, SMTP provider compatibility, credential rotation and approval integration in the deferred verification phase.
