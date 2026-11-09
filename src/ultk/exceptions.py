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


class ApprovalRequiredError(ToolPermissionError):
    """A valid approval is required before this invocation can execute."""

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(f"Human approval required: {approval_id}")


class ToolExecutionError(ULTKError):
    """A tool failed during execution."""


class AgentStepLimitError(ULTKError):
    """The agent exceeded its configured tool-call step limit."""


class WorkflowError(ULTKError):
    """A workflow definition is invalid or cannot be executed."""
