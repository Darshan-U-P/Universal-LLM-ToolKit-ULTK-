"""Typed exceptions used by ULTK."""

class ULTKError(Exception):
    """Base exception for framework errors."""


class ConfigurationError(ULTKError):
    """Invalid framework configuration."""


class DuplicateToolError(ULTKError):
    """A tool with the same identifier is already registered."""


class ToolNotFoundError(ULTKError):
    """The requested tool is not registered or enabled."""


class ToolSchemaError(ULTKError):
    """A tool schema or its arguments are invalid."""


class ToolPermissionError(ULTKError):
    """The current policy does not authorize a tool call."""


class ToolExecutionError(ULTKError):
    """A tool failed during execution."""


class AgentStepLimitError(ULTKError):
    """The agent exceeded its configured tool-call step limit."""
