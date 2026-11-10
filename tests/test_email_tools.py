from __future__ import annotations

import smtplib

import pytest

from ultk.builtins.communications import SMTPEmailSender
from ultk.exceptions import ToolExecutionError
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


class FakeSMTP:
    sent_message = None
    logged_in = None
    tls_started = False

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def login(self, username, password):
        self.logged_in = (username, password)

    def ehlo(self):
        return None

    def starttls(self, context):
        self.tls_started = True

    def send_message(self, message):
        self.sent_message = message
        return {}


def make_sender() -> SMTPEmailSender:
    return SMTPEmailSender(
        host="smtp.example.com",
        port=465,
        from_address="robot@example.com",
        username_env="ULTK_SMTP_USER",
        password_env="ULTK_SMTP_PASSWORD",
        allowed_domains={"example.com"},
    )


def test_smtp_email_uses_host_credentials_and_tls(monkeypatch) -> None:
    fake = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: fake)
    monkeypatch.setenv("ULTK_SMTP_USER", "host-user")
    monkeypatch.setenv("ULTK_SMTP_PASSWORD", "host-password")

    result = make_sender().send(
        ["person@example.com"], "Status update", "The job completed."
    )
    assert result["accepted_count"] == 1
    assert fake.sent_message["From"] == "robot@example.com"
    assert fake.sent_message["To"] == "person@example.com"
    assert fake.sent_message["Message-ID"]


def test_smtp_email_rejects_non_allowlisted_recipients() -> None:
    with pytest.raises(ToolExecutionError, match="allowlist"):
        make_sender().send(["outside@attacker.test"], "Subject", "Body")


def test_smtp_email_requires_host_credentials_when_configured(monkeypatch) -> None:
    monkeypatch.delenv("ULTK_SMTP_USER", raising=False)
    monkeypatch.delenv("ULTK_SMTP_PASSWORD", raising=False)
    with pytest.raises(ToolExecutionError, match="credentials"):
        make_sender().send(["person@example.com"], "Subject", "Body")


def test_email_tool_registration_requires_explicit_capability(tmp_path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"communication.send_email"}))
    engine.install_email_tools(
        host="smtp.example.com",
        port=465,
        from_address="robot@example.com",
        allowed_domains={"example.com"},
    )
    tool = engine.registry.get("communication.send_email")
    assert tool.spec.capabilities == frozenset({"communication:email:send"})
