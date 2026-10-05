"""Gemini's function-declaration rules, checked before anything reaches the API.

Gemini rejects the whole request (HTTP 400 INVALID_ARGUMENT, before the model runs) when any declared tool breaks
them, so one bad schema stops every question. Sources:
- Gemini API `FunctionDeclaration` / `Schema` reference (ai.google.dev/api/generate-content; Vertex AI Schema
  reference): every name in `required` must be defined in `properties`; `type` is a single value (nullable is
  separate); no `$ref`/`$defs`; arrays declare `items`; enums are strings.
- Gemini CLI 0.62 (`generateValidName`): function names start with a letter or underscore, use only
  `a-zA-Z0-9_.:-`, and stay under 64 characters (longer names are mangled). The CLI sends an MCP tool's
  `inputSchema` unchanged as `parametersJsonSchema`.
- Parameter names: start with a letter or underscore, then `a-zA-Z0-9_`, at most 64 characters.
"""
from __future__ import annotations

import re
from typing import Any

FUNCTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:\-]{0,62}$")
PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
UNSUPPORTED = ("$ref", "$defs", "definitions", "$schema", "oneOf", "allOf", "not", "if", "then", "else",
               "patternProperties", "dependentSchemas", "unevaluatedProperties")
TYPES = {"object", "array", "string", "number", "integer", "boolean"}
# Gemini's documented JSON Schema keywords (structured-output docs), anyOf (its Schema type), and the Gemini-specific
# nullable/propertyOrdering. A keyword outside this set is a risk of a 400 for every request.
DOCUMENTED = {"type", "title", "description", "properties", "required", "additionalProperties", "enum", "format",
              "minimum", "maximum", "items", "prefixItems", "minItems", "maxItems", "anyOf", "nullable",
              "propertyOrdering"}


def function_problems(name: str, schema: Any) -> list[str]:
    """Every rule violation for one function declaration (name plus parameter schema); empty when Gemini accepts it."""
    problems = [] if FUNCTION_NAME.match(name) else [f"{name}: function name must match {FUNCTION_NAME.pattern}"]
    if not isinstance(schema, dict) or str(schema.get("type", "")).lower() != "object":
        return [*problems, f"{name}: parameters must be an object schema"]
    return problems + _walk(schema, name)


def _walk(node: Any, path: str) -> list[str]:
    if not isinstance(node, dict):
        return [f"{path}: schema must be an object"]
    problems = [f"{path}: unsupported keyword {key}" for key in UNSUPPORTED if key in node]
    problems += [f"{path}: keyword {key} is not in Gemini's documented schema support" for key in node
                 if key not in DOCUMENTED and key not in UNSUPPORTED]
    kind = node.get("type")
    if isinstance(kind, list):
        problems.append(f"{path}: type must be a single value, not {kind} (use nullable)")
        kind = None
    if "anyOf" in node:
        options = node["anyOf"] if isinstance(node["anyOf"], list) else []
        if any(isinstance(o, dict) and o.get("type") == "null" for o in options):
            problems.append(f"{path}: anyOf with null (collapse Optional[X] to X)")
        for index, option in enumerate(options):
            problems += _walk(option, f"{path}.anyOf[{index}]")
        return problems
    if kind is None:
        return [*problems, f"{path}: missing type"]
    kind = str(kind).lower()
    if kind not in TYPES:
        problems.append(f"{path}: unknown type {kind}")
    if "enum" in node and not all(isinstance(v, str) for v in node["enum"]):
        problems.append(f"{path}: enum values must be strings")
    if kind == "object":
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            return [*problems, f"{path}: properties must be a map"]
        for name in properties:
            if not PARAMETER_NAME.match(name):
                problems.append(f"{path}: parameter name {name!r} must match {PARAMETER_NAME.pattern}")
        for name in node.get("required", []):
            if name not in properties:
                problems.append(f"{path}: required property {name!r} is not defined in properties")
        for name, child in properties.items():
            problems += _walk(child, f"{path}.{name}")
    if kind == "array":
        if "items" not in node:
            problems.append(f"{path}: array without items")
        else:
            problems += _walk(node["items"], f"{path}[]")
    return problems
