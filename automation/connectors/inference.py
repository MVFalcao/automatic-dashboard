"""Deterministic inspection of representative JSON responses."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from automation.connectors.models import ApiField, ApiFieldMapping, ApiInspection


def _path_get(value: Any, path: str) -> Any:
    for part in path.split(".") if path else []:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_records(payload: Any, records_path: str | None = None) -> tuple[list[dict[str, Any]], str | None, str]:
    """Find the record collection without assuming a business domain."""
    if records_path:
        payload = _path_get(payload, records_path)
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
        return records, records_path, "array"
    if isinstance(payload, dict):
        for candidate in ("data", "results", "items", "records"):
            value = payload.get(candidate)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)], records_path or candidate, "object-array"
        return [payload], records_path, "object"
    return [], records_path, type(payload).__name__


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            result.update(_flatten(item, path))
        else:
            result[path] = item
    return result


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "datetime"
        except ValueError:
            return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _label(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("_", " ").replace("-", " ").strip().title()


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def infer_api_schema(
    sample: Any,
    *,
    source_id: str = "sample",
    records_path: str | None = None,
    target_fields: dict[str, str] | None = None,
) -> ApiInspection:
    records, detected_path, shape = extract_records(sample, records_path)
    values: dict[str, list[Any]] = {}
    for record in records:
        for path, value in _flatten(record).items():
            values.setdefault(path, []).append(value)
    fields: list[ApiField] = []
    for path in sorted(values):
        non_null = [item for item in values[path] if item is not None]
        types = Counter(_type(item) for item in non_null)
        kind = types.most_common(1)[0][0] if types else "string"
        if len(types) > 1 and kind != "string":
            kind = "string"
        fields.append(ApiField(
            path=path,
            name=_label(path),
            type=kind,
            nullable=len(non_null) != len(values[path]),
            sample_count=len(non_null),
            evidence=f"Inferred from {len(records)} representative JSON record(s)",
        ))
    targets = target_fields or {}
    by_normal = {_normal(path): (path, name) for path, name in targets.items()}
    mappings: list[ApiFieldMapping] = []
    for field in fields:
        source_normal = _normal(field.path)
        target = by_normal.get(source_normal)
        if target is None:
            mappings.append(ApiFieldMapping(
                source_path=field.path,
                target_field=field.path,
                confidence="unmapped",
                explanation=f"No approved dashboard field matches {field.name}; review before use.",
            ))
        else:
            mappings.append(ApiFieldMapping(
                source_path=field.path,
                target_field=target[0],
                confidence="high",
                explanation=f"The API field {field.name} matches the approved field {target[1]}.",
            ))
    issues = [] if records else ["The representative response did not contain JSON object records"]
    return ApiInspection(
        source_id=source_id,
        fields=fields,
        mappings=mappings,
        record_shape=shape,
        records_path=detected_path,
        validation_issues=issues,
        inspected_at=datetime.now(timezone.utc),
    )


def infer_openapi_schema(
    document: dict[str, Any],
    *,
    source_id: str = "openapi",
    target_fields: dict[str, str] | None = None,
) -> ApiInspection:
    """Extract a response contract from OpenAPI/Swagger without calling it.

    The parser deliberately handles the common JSON ``schema.properties``
    shape and follows local ``#/components/schemas``/``#/definitions`` refs.
    Unsupported constructs remain an explicit validation issue for review.
    """
    components = document.get("components", {}).get("schemas", {})
    if not components:
        components = document.get("definitions", {})
    fields: dict[str, str] = {}
    unresolved = False

    def walk(schema: Any, prefix: str = "") -> None:
        nonlocal unresolved
        if not isinstance(schema, dict):
            unresolved = True
            return
        ref = schema.get("$ref")
        if ref:
            name = str(ref).rsplit("/", 1)[-1]
            resolved = components.get(name)
            if resolved is None:
                unresolved = True
            else:
                walk(resolved, prefix)
            return
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for name, child in properties.items():
                path = f"{prefix}.{name}" if prefix else str(name)
                if isinstance(child, dict) and "properties" in child:
                    walk(child, path)
                else:
                    fields[path] = str(child.get("type", "string")) if isinstance(child, dict) else "string"
        elif prefix:
            fields[prefix] = str(schema.get("type", "string"))

    # Prefer a JSON response schema from the first declared operation.
    response_schema: Any = None
    for path_item in (document.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses", {})
            for response in responses.values():
                content = response.get("content", {}) if isinstance(response, dict) else {}
                json_content = content.get("application/json", {}) if isinstance(content, dict) else {}
                if isinstance(json_content, dict) and json_content.get("schema"):
                    response_schema = json_content["schema"]
                    break
            if response_schema is not None:
                break
        if response_schema is not None:
            break
    if response_schema is None:
        unresolved = True
    else:
        if isinstance(response_schema, dict) and response_schema.get("type") == "array":
            response_schema = response_schema.get("items", {})
        walk(response_schema)
    fields_list = [ApiField(
        path=path,
        name=_label(path),
        type=kind,
        nullable=True,
        sample_count=0,
        evidence="Inferred from the supplied OpenAPI/Swagger response schema",
    ) for path, kind in sorted(fields.items())]
    targets = target_fields or {}
    by_normal = {_normal(path): (path, name) for path, name in targets.items()}
    mappings = [ApiFieldMapping(
        source_path=field.path,
        target_field=by_normal.get(_normal(field.path), (field.path, field.name))[0],
        confidence="high" if _normal(field.path) in by_normal else "unmapped",
        explanation=(f"The API field {field.name} matches the approved field {by_normal[_normal(field.path)][1]}."
                     if _normal(field.path) in by_normal else
                     f"No approved dashboard field matches {field.name}; review before use."),
    ) for field in fields_list]
    issues = ["The OpenAPI document does not expose a supported JSON response schema"] if unresolved else []
    return ApiInspection(
        source_id=source_id,
        fields=fields_list,
        mappings=mappings,
        record_shape="openapi-schema",
        records_path=None,
        validation_issues=issues,
        inspected_at=datetime.now(timezone.utc),
    )


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    return _flatten(record)
