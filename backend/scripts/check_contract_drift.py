"""OpenAPI <-> shared client contract drift check.

Two independent checks run here:

1. **Artifact freshness**: the committed ``openapi.json`` must equal the schema
   generated from the running FastAPI app, so a forgotten regeneration is a hard
   failure instead of a silent contract drift.
2. **Client alignment**: every field declared by the desktop client's Zod
   contract (``packages/contracts/src/index.ts``) must be present in the matching
   OpenAPI component with a JSON type the client accepts (see DECISIONS.md
   D-009: the client is authoritative for these shapes). A frozen snapshot of
   that contract lives in ``tests/fixtures/client_contract.ts`` so this check
   can run on a branch where ``packages/contracts`` is not present.

Usage::

    python -m backend.scripts.check_contract_drift
    python -m backend.scripts.check_contract_drift --write   # refresh openapi.json

Exits non-zero and prints a report when drift is found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.main import app

DEFAULT_OPENAPI = Path("openapi.json")
DEFAULT_ZOD_SOURCES: tuple[Path, ...] = (
    Path("packages/contracts/src/index.ts"),
    Path("tests/fixtures/client_contract.ts"),
)

# Zod schema name -> OpenAPI component schema name.
ZOD_TO_OPENAPI: dict[str, str] = {
    "EventProvenanceSchema": "EventProvenance",
    "EventEnvelopeSchema": "EventEnvelope",
    "EventBatchRequestSchema": "EventBatchRequest",
    "EventBatchResponseSchema": "EventBatchResponse",
    "TaskSchema": "ClientTask",
    "CurrentStateSchema": "ClientCurrentState",
    "PlanItemSchema": "ClientPlanItem",
    "PlanSchema": "ClientPlan",
    "FocusSessionSchema": "ClientFocusSession",
    # M4 agent contract (D-034, slice A1). Keys verified against B1's
    # actual exports on feature/m4-b1-contract-zod (PR #51): B1 exports
    # PendingActionReadSchema / AgentRunReadSchema — NOT the shorter names
    # first staged here (batch-coordination defect caught in review).
    "DecisionBasisSchema": "DecisionBasis",
    "PendingActionReadSchema": "PendingActionRead",
    "AgentRunReadSchema": "AgentRunRead",
    "ChatSessionSchema": "ChatSessionRead",
    "ChatMessageSchema": "ChatMessageRead",
    "NotificationPreferencesSchema": "NotificationPreferencesRead",
    "ChatMessageSendResponseSchema": "ChatMessageSendResponse",
}

# Direction of the contract:
# - "request": the client sends these shapes and the Backend must accept them.
# - "response": the Backend sends these shapes and the client validates them.
# Only base JSON types are compared (null widening is ignored) because the
# Backend uses `| None = None` for optional fields while the client expresses
# absence as `.optional()`; the runtime shape is covered by
# `tests/integration/test_client_contract.py`.
ZOD_DIRECTION: dict[str, str] = {
    "EventProvenanceSchema": "request",
    "EventEnvelopeSchema": "request",
    "EventBatchRequestSchema": "request",
    "EventBatchResponseSchema": "response",
    "TaskSchema": "response",
    "CurrentStateSchema": "response",
    "PlanItemSchema": "response",
    "PlanSchema": "response",
    "FocusSessionSchema": "response",
    "DecisionBasisSchema": "response",
    "PendingActionReadSchema": "response",
    "AgentRunReadSchema": "response",
    "ChatSessionSchema": "response",
    "ChatMessageSchema": "response",
    "NotificationPreferencesSchema": "response",
    "ChatMessageSendResponseSchema": "response",
}

_BRACKETS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = frozenset(_BRACKETS.values())
_SCHEMA_RE = re.compile(r"export const (\w+Schema)\s*=\s*z\.object\(\{")
_CONST_RE = re.compile(r"^const (\w+)\s*=\s*([^\n;]+);", re.MULTILINE)


@dataclass
class ZType:
    """Expected JSON types (and nested shape) declared by a Zod field."""

    types: frozenset[str]
    ref: str | None = None
    fields: dict[str, ZType] | None = None
    items: ZType | None = None
    enum: tuple[str, ...] | None = None
    is_datetime: bool = False
    minimum: int | float | None = None
    optional: bool = False


@dataclass
class DriftReport:
    artifact: list[str] = field(default_factory=list)
    client: list[str] = field(default_factory=list)
    zod_sources: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.artifact or self.client)


# --------------------------------------------------------------------------- #
# Zod parsing
# --------------------------------------------------------------------------- #


def _match_delim(text: str, open_index: int) -> int:
    """Return the index of the bracket matching ``text[open_index]``."""

    stack: list[str] = []
    in_string: str | None = None
    index = open_index
    while index < len(text):
        char = text[index]
        if in_string is not None:
            if char == "\\":
                index += 2
                continue
            if char == in_string:
                in_string = None
        elif char in "\"'`":
            in_string = char
        elif char in _BRACKETS:
            stack.append(_BRACKETS[char])
        elif stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return index
        index += 1
    raise ValueError(f"Unbalanced delimiter at index {open_index}")


def _call_body(expr: str, prefix: str) -> str | None:
    if not expr.startswith(prefix):
        return None
    open_index = len(prefix) - 1
    return expr[open_index + 1 : _match_delim(expr, open_index)]


def _split_top_level(body: str) -> list[tuple[str, str]]:
    """Split ``key: value`` pairs at bracket depth zero."""

    chunks: list[str] = []
    current: list[str] = []
    depth = 0
    in_string: str | None = None
    index = 0
    while index < len(body):
        char = body[index]
        if in_string is not None:
            current.append(char)
            if char == "\\" and index + 1 < len(body):
                current.append(body[index + 1])
                index += 2
                continue
            if char == in_string:
                in_string = None
        elif char in "\"'`":
            in_string = char
            current.append(char)
        elif char in _BRACKETS:
            depth += 1
            current.append(char)
        elif char in _CLOSERS:
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            chunks.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    if current:
        chunks.append("".join(current))

    pairs: list[tuple[str, str]] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        name, separator, value = chunk.partition(":")
        if separator:
            pairs.append((name.strip(), value.strip()))
    return pairs


def _collect_consts(source: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2).strip()
        for match in _CONST_RE.finditer(source)
        if not match.group(1).endswith("Schema")
    }


def _ztype(expr: str, consts: dict[str, str], *, depth: int = 0) -> ZType:
    expr = expr.strip()
    if depth > 20:
        return ZType(frozenset())

    identifier = re.match(r"^([A-Za-z_]\w*)", expr)
    if identifier and identifier.group(1) in consts:
        expanded = consts[identifier.group(1)] + expr[identifier.end() :]
        return _ztype(expanded, consts, depth=depth + 1)

    nullable = ".nullable()" in expr
    # `.optional()` allows the key to be absent; `.default(...)` lets Zod fill
    # it in, so an omitted key is still valid.
    optional = ".optional()" in expr or ".default(" in expr
    types: set[str] = set()
    ref: str | None = None
    fields: dict[str, ZType] | None = None
    items: ZType | None = None
    enum_values: tuple[str, ...] | None = None
    is_datetime = False
    minimum: int | float | None = None

    array_body = _call_body(expr, "z.array(")
    object_body = _call_body(expr, "z.object(")
    if array_body is not None:
        types.add("array")
        items = _ztype(array_body, consts, depth=depth + 1)
    elif object_body is not None:
        types.add("object")
        inner = object_body.strip()
        if inner.startswith("{"):
            inner = inner[1 : _match_delim(inner, 0)]
        fields = {
            name: _ztype(value, consts, depth=depth + 1) for name, value in _split_top_level(inner)
        }
    elif expr.startswith("z.record("):
        types.add("object")
    elif expr.startswith("z.enum("):
        types.add("string")
        body = _call_body(expr, "z.enum(")
        if body is not None:
            enum_values = tuple(
                first or second for first, second in re.findall(r"\"([^\"]*)\"|'([^']*)'", body)
            )
    elif expr.startswith("z.string"):
        types.add("string")
        is_datetime = ".datetime(" in expr
    elif expr.startswith("z.number"):
        types.add("integer" if ".int()" in expr else "number")
        if ".nonnegative()" in expr:
            minimum = 0
    elif expr.startswith("z.boolean"):
        types.add("boolean")
    else:
        reference = re.match(r"^(\w+Schema)\b", expr)
        if reference:
            types.add("object")
            ref = reference.group(1)

    if nullable:
        types.add("null")

    return ZType(
        frozenset(types),
        ref=ref,
        fields=fields,
        items=items,
        enum=enum_values,
        is_datetime=is_datetime,
        minimum=minimum,
        optional=optional,
    )


def _strip_line_comments(source: str) -> str:
    """Blank out ``//`` line comments while preserving string literals.

    ``_split_top_level`` splits on commas, so a comment containing a comma
    inside a schema body used to be misparsed as a field name — the reason
    comments were conventionally kept above schema definitions. Stripping
    comments first (string-aware, so a ``//`` inside a quoted literal such as
    a URL string survives) makes that convention a style choice instead of a
    load-bearing rule (PR #10 review follow-up).

    Known limitation: a regex literal containing consecutive slashes (a
    ``https`` URL pattern, for instance) would still be misread as a
    comment — distinguishing regex literals from division requires a full
    JS lexer. Neither contract source uses that shape (``sensitiveKey``'s
    alternation has no ``//`` run), and the frozen snapshot is reviewed on
    every change, so the limitation is accepted rather than half-parsed.
    """

    chars: list[str] = []
    in_string: str | None = None
    index = 0
    while index < len(source):
        char = source[index]
        if in_string is not None:
            chars.append(char)
            if char == "\\" and index + 1 < len(source):
                chars.append(source[index + 1])
                index += 2
                continue
            if char == in_string:
                in_string = None
        elif char in "\"'`":
            in_string = char
            chars.append(char)
        elif char == "/" and index + 1 < len(source) and source[index + 1] == "/":
            while index < len(source) and source[index] != "\n":
                index += 1
            chars.append(" ")
            continue
        else:
            chars.append(char)
        index += 1
    return "".join(chars)


def parse_zod_schemas(source: str) -> dict[str, dict[str, ZType]]:
    """Parse ``export const XSchema = z.object({...})`` declarations."""

    source = _strip_line_comments(source)
    consts = _collect_consts(source)
    schemas: dict[str, dict[str, ZType]] = {}
    for match in _SCHEMA_RE.finditer(source):
        name = match.group(1)
        open_brace = match.end() - 1
        close_brace = _match_delim(source, open_brace)
        body = source[open_brace + 1 : close_brace]
        schemas[name] = {
            field_name: _ztype(field_value, consts)
            for field_name, field_value in _split_top_level(body)
        }
    return schemas


# --------------------------------------------------------------------------- #
# OpenAPI alignment
# --------------------------------------------------------------------------- #


def _single_non_null_branch(node: Any) -> Any | None:
    """The unique non-null ``anyOf`` branch, when all others are null-typed.

    Pydantic v2 renders ``SomeModel | None`` as ``anyOf: [$ref, {type: null}]``
    in OpenAPI 3.1; a nullable object reference must still resolve to its
    component for the nested field comparison (M4 read shapes are the first
    contract schemas with nullable object members).
    """

    branches = node.get("anyOf")
    if not isinstance(branches, list) or not branches:
        return None
    non_null = [
        branch
        for branch in branches
        if not (isinstance(branch, dict) and branch.get("type") == "null")
    ]
    # Exactly one non-null branch; every other branch is a null type.
    return non_null[0] if len(non_null) == 1 else None


def _resolve(node: Any, schemas: dict[str, Any]) -> Any:
    seen = 0
    while isinstance(node, dict) and seen < 20:
        if "$ref" in node:
            node = schemas.get(str(node["$ref"]).rsplit("/", 1)[-1])
        else:
            branch = _single_non_null_branch(node)
            if branch is None:
                break
            node = branch
        seen += 1
    return node


def _openapi_json_types(node: Any, schemas: dict[str, Any]) -> set[str]:
    node = _resolve(node, schemas)
    if not isinstance(node, dict):
        return set()
    if "anyOf" in node:
        types: set[str] = set()
        for branch in node["anyOf"]:
            types |= _openapi_json_types(branch, schemas)
        return types
    declared = node.get("type")
    if isinstance(declared, list):
        return {str(item) for item in declared}
    if isinstance(declared, str):
        return {declared}
    if "properties" in node or "additionalProperties" in node:
        return {"object"}
    if "items" in node:
        return {"array"}
    return set()


class _Alignment:
    def __init__(
        self,
        zod_schemas: dict[str, dict[str, ZType]],
        components: dict[str, Any],
    ) -> None:
        self.zod = zod_schemas
        self.components = components
        self.errors: list[str] = []

    def check_mapping(self, zod_name: str, openapi_name: str, direction: str) -> None:
        if zod_name not in self.zod:
            self.errors.append(
                f"{zod_name}: declared in ZOD_TO_OPENAPI but not found in the Zod contract"
            )
            return
        component = self.components.get(openapi_name)
        if component is None:
            self.errors.append(f"{openapi_name}: OpenAPI component not found")
            return
        self._check_object(openapi_name, self.zod[zod_name], component, direction)

    def _check_object(self, path: str, fields: dict[str, ZType], node: Any, direction: str) -> None:
        resolved = _resolve(node, self.components)
        properties = resolved.get("properties") if isinstance(resolved, dict) else None
        if not isinstance(properties, dict):
            self.errors.append(f"{path}: OpenAPI component has no object properties")
            return
        for name, expected in fields.items():
            child_path = f"{path}.{name}"
            if name not in properties:
                self.errors.append(f"{child_path}: missing from OpenAPI")
                continue
            self._check_field(child_path, expected, properties[name], direction)

    def _check_field(self, path: str, expected: ZType, node: Any, direction: str) -> None:
        resolved = _resolve(node, self.components)

        if expected.items is not None:
            if not isinstance(resolved, dict) or resolved.get("type") != "array":
                self.errors.append(f"{path}: client declares an array")
            else:
                self._check_field(f"{path}[]", expected.items, resolved.get("items", {}), direction)

        if expected.fields is not None:
            self._check_object(path, expected.fields, resolved, direction)
        elif expected.ref is not None:
            nested = self.zod.get(expected.ref)
            if nested is None:
                self.errors.append(f"{path}: Zod schema {expected.ref} not found")
            else:
                self._check_object(path, nested, resolved, direction)

        if not expected.types:
            return
        zod_types = {kind for kind in expected.types if kind != "null"}
        openapi_types = _openapi_json_types(resolved, self.components) - {"null"}
        if direction == "response":
            # The Backend must not send a base type the client rejects.
            unexpected = openapi_types - zod_types
        else:
            # The Backend must accept every base type the client sends.
            unexpected = zod_types - openapi_types
        if unexpected:
            self.errors.append(
                f"{path}: OpenAPI declares {sorted(openapi_types)} but the client expects "
                f"{sorted(expected.types)}"
            )


# --------------------------------------------------------------------------- #
# Checks and CLI
# --------------------------------------------------------------------------- #


def generate_openapi() -> dict[str, Any]:
    return app.openapi()


_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_SCALAR_KEYWORDS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
)


def _schema_signature(node: Any, schemas: dict[str, Any]) -> Any:
    """Structural (version-robust) signature of an OpenAPI schema node.

    Comparing raw JSON makes the check sensitive to FastAPI/Pydantic formatting
    and metadata changes. Only contract-relevant structure is kept, so a real
    shape change fails while a regenerated-but-equivalent schema does not.
    """

    node = _resolve(node, schemas)
    if not isinstance(node, dict):
        return None
    signature: dict[str, Any] = {}
    declared = node.get("type")
    if isinstance(declared, list):
        signature["type"] = sorted(str(item) for item in declared)
    elif declared is not None:
        signature["type"] = declared
    for keyword in ("format", "default", *_SCALAR_KEYWORDS):
        if keyword in node:
            signature[keyword] = node[keyword]
    for keyword in ("required", "enum"):
        value = node.get(keyword)
        if isinstance(value, list):
            signature[keyword] = sorted(str(item) for item in value)
    if "items" in node:
        signature["items"] = _schema_signature(node["items"], schemas)
    properties = node.get("properties")
    if isinstance(properties, dict):
        signature["properties"] = {
            name: _schema_signature(value, schemas) for name, value in sorted(properties.items())
        }
    additional = node.get("additionalProperties")
    if isinstance(additional, bool):
        signature["additionalProperties"] = additional
    elif additional is not None:
        signature["additionalProperties"] = _schema_signature(additional, schemas)
    for keyword in ("anyOf", "oneOf", "allOf"):
        branches = node.get(keyword)
        if isinstance(branches, list):
            signature[keyword] = sorted(
                (_schema_signature(branch, schemas) for branch in branches),
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )
    return signature


def _media_signature(content: Any, schemas: dict[str, Any]) -> Any:
    if not isinstance(content, dict):
        return None
    return {
        media_type: _schema_signature(
            payload.get("schema") if isinstance(payload, dict) else None, schemas
        )
        for media_type, payload in sorted(content.items())
    }


def _operation_signature(operation: Any, schemas: dict[str, Any]) -> Any:
    if not isinstance(operation, dict):
        return None
    parameters: list[dict[str, Any]] = []
    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        parameters.append(
            {
                "name": parameter.get("name"),
                "in": parameter.get("in"),
                "required": parameter.get("required", False),
                "schema": _schema_signature(parameter.get("schema"), schemas),
            }
        )
    parameters.sort(key=lambda item: (str(item["name"]), str(item["in"])))
    request_body = operation.get("requestBody")
    responses = operation.get("responses")
    signatures: dict[str, Any] = {}
    if isinstance(responses, dict):
        signatures["responses"] = {
            str(code): _media_signature(
                response.get("content") if isinstance(response, dict) else None, schemas
            )
            for code, response in sorted(responses.items())
        }
    return {
        "parameters": parameters,
        "requestBody": (
            _media_signature(request_body.get("content"), schemas)
            if isinstance(request_body, dict)
            else None
        ),
        **signatures,
    }


def openapi_signature(schema: dict[str, Any]) -> dict[str, Any]:
    schemas = schema.get("components", {}).get("schemas", {})
    operations: dict[str, Any] = {}
    paths = schema.get("paths", {})
    if isinstance(paths, dict):
        for path, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method, operation in item.items():
                if method.lower() not in _HTTP_METHODS:
                    continue
                operations[f"{method.upper()} {path}"] = _operation_signature(operation, schemas)
    components = {name: _schema_signature(node, schemas) for name, node in sorted(schemas.items())}
    return {"operations": operations, "components": components}


def compare_artifact(committed: dict[str, Any], generated: dict[str, Any]) -> list[str]:
    committed_signature = openapi_signature(committed)
    generated_signature = openapi_signature(generated)
    if committed_signature == generated_signature:
        return []
    messages = [
        "openapi.json is out of date; run `python -m backend.scripts.check_contract_drift --write`"
    ]
    committed_operations = committed_signature["operations"]
    generated_operations = generated_signature["operations"]
    for operation in sorted(set(generated_operations) - set(committed_operations)):
        messages.append(f"  operation only in generated: {operation}")
    for operation in sorted(set(committed_operations) - set(generated_operations)):
        messages.append(f"  operation only in committed: {operation}")
    for operation in sorted(set(committed_operations) & set(generated_operations)):
        if committed_operations[operation] != generated_operations[operation]:
            messages.append(f"  operation changed: {operation}")

    committed_schemas = committed_signature["components"]
    generated_schemas = generated_signature["components"]
    for name in sorted(set(generated_schemas) - set(committed_schemas)):
        messages.append(f"  schema only in generated: {name}")
    for name in sorted(set(committed_schemas) - set(generated_schemas)):
        messages.append(f"  schema only in committed: {name}")
    for name in sorted(set(committed_schemas) & set(generated_schemas)):
        if committed_schemas[name] != generated_schemas[name]:
            messages.append(f"  schema changed: {name}")
    return messages


def check_client_alignment(zod_source: str, openapi: dict[str, Any]) -> list[str]:
    zod_schemas = parse_zod_schemas(zod_source)
    components = openapi.get("components", {}).get("schemas", {})
    alignment = _Alignment(zod_schemas, components)
    for zod_name, openapi_name in ZOD_TO_OPENAPI.items():
        alignment.check_mapping(zod_name, openapi_name, ZOD_DIRECTION.get(zod_name, "response"))
    return alignment.errors


# --------------------------------------------------------------------------- #
# Runtime payload validation against the parsed Zod contract
# --------------------------------------------------------------------------- #


def _validate_object(
    value: Any,
    fields: dict[str, ZType],
    path: str,
    schemas: dict[str, dict[str, ZType]],
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    for name, expected in fields.items():
        child = f"{path}.{name}"
        if name not in value:
            if not expected.optional:
                errors.append(f"{child}: missing")
            continue
        _validate_value(value[name], expected, child, schemas, errors)


def _validate_value(
    value: Any,
    expected: ZType,
    path: str,
    schemas: dict[str, dict[str, ZType]],
    errors: list[str],
) -> None:
    if value is None:
        if "null" not in expected.types:
            errors.append(f"{path}: null is not allowed")
        return
    if expected.ref is not None:
        nested = schemas.get(expected.ref)
        if nested is None:
            errors.append(f"{path}: Zod schema {expected.ref} not found")
        else:
            _validate_object(value, nested, path, schemas, errors)
        return
    if expected.fields is not None:
        _validate_object(value, expected.fields, path, schemas, errors)
        return
    if expected.items is not None:
        if not isinstance(value, list):
            errors.append(f"{path}: expected an array")
            return
        for index, item in enumerate(value):
            _validate_value(item, expected.items, f"{path}[{index}]", schemas, errors)
        return

    allowed = {kind for kind in expected.types if kind != "null"}
    if "string" in allowed:
        if not isinstance(value, str):
            errors.append(f"{path}: expected a string")
            return
        if expected.is_datetime:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path}: {value!r} is not an ISO-8601 datetime")
        if expected.enum is not None and value not in expected.enum:
            errors.append(f"{path}: {value!r} is not one of {sorted(expected.enum)}")
    elif "boolean" in allowed:
        if not isinstance(value, bool):
            errors.append(f"{path}: expected a boolean")
    elif "integer" in allowed or "number" in allowed:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: expected a number")
        elif "integer" in allowed and not isinstance(value, int):
            errors.append(f"{path}: expected an integer")
        elif expected.minimum is not None and value < expected.minimum:
            errors.append(f"{path}: {value} is below the minimum {expected.minimum}")
    elif "object" in allowed:
        if not isinstance(value, dict):
            errors.append(f"{path}: expected an object")
    elif "array" in allowed and not isinstance(value, list):
        errors.append(f"{path}: expected an array")


def validate_client_value(payload: Any, zod_source: str, schema_name: str) -> list[str]:
    """Validate a runtime JSON payload against a Zod object schema.

    This is the strongest check possible without a JS runtime: it enforces the
    client's declared fields, nullability, base JSON types, ISO-8601 datetimes,
    enum members and numeric bounds for one snapshot schema, following nested
    references to other Zod schemas recursively.
    """

    schemas = parse_zod_schemas(zod_source)
    fields = schemas.get(schema_name)
    if fields is None:
        return [f"{schema_name}: not found in the Zod contract"]
    errors: list[str] = []
    _validate_object(payload, fields, schema_name, schemas, errors)
    return errors


def _read_artifact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run(
    *,
    openapi_path: Path,
    zod_sources: list[Path],
    write: bool,
    require_zod: bool,
) -> DriftReport:
    report = DriftReport()
    generated = generate_openapi()

    if write:
        openapi_path.write_text(
            json.dumps(generated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    else:
        committed = _read_artifact(openapi_path)
        if committed is None:
            report.artifact.append(f"{openapi_path} does not exist")
        else:
            report.artifact = compare_artifact(committed, generated)

    existing = [source for source in zod_sources if source.is_file()]
    if not existing:
        if require_zod:
            report.client.append(f"no Zod contract found in {[str(s) for s in zod_sources]}")
        return report
    for source in existing:
        report.zod_sources.append(str(source))
        report.client.extend(
            f"{source}: {message}"
            for message in check_client_alignment(source.read_text(encoding="utf-8"), generated)
        )
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", type=Path, default=DEFAULT_OPENAPI)
    parser.add_argument(
        "--zod",
        type=Path,
        action="append",
        dest="zod_sources",
        help="Zod contract source (repeatable); defaults to the client + frozen snapshot",
    )
    parser.add_argument("--write", action="store_true", help="Regenerate openapi.json in place")
    parser.add_argument(
        "--require-zod",
        action="store_true",
        help="Fail when no Zod contract source can be found",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    zod_sources = list(args.zod_sources) if args.zod_sources else list(DEFAULT_ZOD_SOURCES)
    report = run(
        openapi_path=args.openapi,
        zod_sources=zod_sources,
        write=args.write,
        require_zod=args.require_zod,
    )

    if report.zod_sources:
        print(f"Checked client contract against: {', '.join(report.zod_sources)}")
    else:
        print("Warning: no Zod contract source found; checked openapi.json freshness only")

    for label, messages in (
        ("OpenAPI artifact drift", report.artifact),
        ("OpenAPI/Zod drift", report.client),
    ):
        for message in messages:
            print(f"[{label}] {message}")

    if report.has_drift:
        print("Contract drift detected.")
        return 1
    print("No contract drift detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
