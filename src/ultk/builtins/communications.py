"""Host-configured SMTP email sending with recipient allowlists and mandatory TLS."""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from collections.abc import Iterable
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_address(value: str) -> bool:
    display_name, address = parseaddr(value)
    return not display_name and address == value and bool(_ADDRESS.fullmatch(address))


class SMTPEmailSender:
    """Send plain-text email through a host-configured SMTP server."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        username_env: str | None,
        password_env: str | None,
        allowed_recipients: Iterable[str] = (),
        allowed_domains: Iterable[str] = (),
        use_ssl: bool = True,
        timeout_seconds: int = 20,
    ) -> None:
        if not host or len(host) > 255 or any(char.isspace() for char in host):
            raise ValueError("SMTP host must be a valid host name.")
        if not 1 <= port <= 65535 or not 1 <= timeout_seconds <= 60:
            raise ValueError("SMTP port or timeout is outside allowed bounds.")
        if not _valid_address(from_address):
            raise ValueError("A valid host-configured sender address is required.")
        if bool(username_env) != bool(password_env):
            raise ValueError("SMTP username and password environment names must be configured together.")
        for env_name in (username_env, password_env):
            if env_name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
                raise ValueError("SMTP credential environment variable name is invalid.")
        exact = {address.casefold() for address in allowed_recipients}
        domains = {domain.casefold().lstrip("@") for domain in allowed_domains}
        if any(not _valid_address(address) for address in exact):
            raise ValueError("Recipient allowlist contains an invalid email address.")
        if any(not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain) for domain in domains):
            raise ValueError("Recipient domain allowlist contains an invalid domain.")
        if not exact and not domains:
            raise ValueError("At least one exact recipient or recipient domain must be allowlisted.")
        self.host = host
        self.port = port
        self.from_address = from_address
        self.username_env = username_env
        self.password_env = password_env
        self.allowed_recipients = exact
        self.allowed_domains = domains
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds

    def _check_recipients(self, recipients: list[str]) -> None:
        if not isinstance(recipients, list) or not 1 <= len(recipients) <= 10:
            raise ToolExecutionError("Email must have between 1 and 10 recipients.")
        if len({address.casefold() for address in recipients}) != len(recipients):
            raise ToolExecutionError("Duplicate email recipients are not allowed.")
        for address in recipients:
            if not _valid_address(address):
                raise ToolExecutionError("A recipient email address is invalid.")
            domain = address.rsplit("@", 1)[1].casefold()
            if (
                address.casefold() not in self.allowed_recipients
                and domain not in self.allowed_domains
            ):
                raise ToolExecutionError("A recipient is outside the host-configured allowlist.")

    def send(self, recipients: list[str], subject: str, body: str) -> dict[str, Any]:
        self._check_recipients(recipients)
        if not subject or len(subject) > 200 or "\r" in subject or "\n" in subject:
            raise ToolExecutionError("Email subject must be 1–200 characters without newlines.")
        if not isinstance(body, str) or not body.strip() or len(body) > 20_000:
            raise ToolExecutionError("Plain-text email body must be 1–20000 characters.")
        username = os.environ.get(self.username_env) if self.username_env else None
        password = os.environ.get(self.password_env) if self.password_env else None
        if self.username_env and (not username or not password):
            raise ToolExecutionError("Host-configured SMTP credentials are unavailable.")

        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message["Message-ID"] = make_msgid()
        message.set_content(body)
        context = ssl.create_default_context()
        try:
            if self.use_ssl:
                with smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout_seconds, context=context
                ) as client:
                    if username and password:
                        client.login(username, password)
                    refused = client.send_message(message)
            else:
                with smtplib.SMTP(
                    self.host, self.port, timeout=self.timeout_seconds
                ) as client:
                    client.ehlo()
                    client.starttls(context=context)
                    client.ehlo()
                    if username and password:
                        client.login(username, password)
                    refused = client.send_message(message)
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            raise ToolExecutionError(
                f"SMTP delivery failed ({type(exc).__name__})."
            ) from exc
        accepted_count = len(recipients) - len(refused)
        if accepted_count == 0:
            raise ToolExecutionError("SMTP server refused all configured recipients.")
        return {
            "message_id": message["Message-ID"],
            "accepted_count": accepted_count,
            "refused_count": len(refused),
        }


def create_email_tools(
    *,
    host: str,
    port: int,
    from_address: str,
    username_env: str | None = None,
    password_env: str | None = None,
    allowed_recipients: Iterable[str] = (),
    allowed_domains: Iterable[str] = (),
    use_ssl: bool = True,
    timeout_seconds: int = 20,
) -> tuple[FunctionTool, ...]:
    sender = SMTPEmailSender(
        host=host,
        port=port,
        from_address=from_address,
        username_env=username_env,
        password_env=password_env,
        allowed_recipients=allowed_recipients,
        allowed_domains=allowed_domains,
        use_ssl=use_ssl,
        timeout_seconds=timeout_seconds,
    )
    return (
        FunctionTool(
            "communication.send_email",
            "Send a plain-text email through the host-configured SMTP server to allowlisted recipients.",
            object_schema({
                "recipients": {
                    "type": "array",
                    "items": {"type": "string", "format": "email", "maxLength": 254},
                    "minItems": 1,
                    "maxItems": 10,
                },
                "subject": {"type": "string", "minLength": 1, "maxLength": 200},
                "body": {"type": "string", "minLength": 1, "maxLength": 20000},
            }, ["recipients", "subject", "body"]),
            "communication:email:send",
            sender.send,
            timeout=timeout_seconds + 2,
            output_limit=2000,
        ),
    )
