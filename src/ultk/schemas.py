"""JSON Schema validation helpers."""

from typing import Any, Mapping

from jsonschema import Draft202012Validator, SchemaError, ValidationError

from ultk.exceptions import ToolSchemaError


def validate_schema(schema: Mapping[str, Any]) -> None:
    """Raise ToolSchemaError when a declared tool schema is invalid."""
    try:
        Draft202012Validator.check_schema(dict(schema))
    except SchemaError as exc:
        raise ToolSchemaError(f"Invalid JSON Schema: {exc.message}") from exc


def validate_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> None:
    """Validate arguments against a tool's JSON Schema."""
    validate_schema(schema)
    try:
        Draft202012Validator(dict(schema)).validate(dict(arguments))
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ToolSchemaError(f"Invalid arguments at {location}: {exc.message}") from exc
