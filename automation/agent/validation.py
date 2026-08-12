"""Validate every structured result before the application consumes it."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError


T = TypeVar("T", bound=BaseModel)


class StructuredResponseError(ValueError):
    pass


class StructuredResponseValidator:
    """Pydantic-backed validator for model responses and tool payloads."""

    @staticmethod
    def validate(payload: Any, response_type: type[T]) -> T:
        if not isinstance(payload, dict):
            raise StructuredResponseError("Hermes structured response must be a JSON object")
        try:
            return response_type.model_validate(payload)
        except ValidationError as exc:
            raise StructuredResponseError("Hermes response failed its declared schema") from exc

    @staticmethod
    def validate_json(payload: Any, schema: dict[str, Any]) -> dict[str, Any]:
        """Validate a JSON-compatible object against a caller-provided schema."""

        try:
            result = TypeAdapter(dict[str, Any]).validate_python(payload)
        except ValidationError as exc:
            raise StructuredResponseError("Hermes response is not a JSON object") from exc
        # JSON Schema validation is optional to keep the core package lightweight;
        # pydantic models remain the preferred, strict contract.  Support the
        # common object properties/required subset for generated tool contracts.
        required = set(schema.get("required", []))
        missing = required - set(result)
        if missing:
            raise StructuredResponseError(f"Hermes response is missing required fields: {sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(result) - set(properties)
            if unknown:
                raise StructuredResponseError(f"Hermes response contains unknown fields: {sorted(unknown)}")
        for key, definition in properties.items():
            if key not in result:
                continue
            expected = definition.get("type")
            value = result[key]
            if expected == "string" and not isinstance(value, str):
                raise StructuredResponseError(f"Hermes response field {key!r} must be a string")
            if expected == "object" and not isinstance(value, dict):
                raise StructuredResponseError(f"Hermes response field {key!r} must be an object")
            if expected == "array" and not isinstance(value, list):
                raise StructuredResponseError(f"Hermes response field {key!r} must be an array")
            if expected == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise StructuredResponseError(f"Hermes response field {key!r} must be a number")
        return result

