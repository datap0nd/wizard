"""Every Wizard tool must satisfy Gemini's function-declaration rules: one violation makes Google reject every request
with 400 INVALID_ARGUMENT before the model runs (seen on the work PC: `required: ["title"]` with `title` stripped)."""
from __future__ import annotations

import pytest

from wizard_agent.code_assist import gemini_schema
from wizard_connectors.gemini_rules import function_problems
from wizard_connectors.tools import build_registry, build_services

TOOLS = build_registry(build_services()).describe()


@pytest.mark.parametrize("tool", TOOLS, ids=[t["name"] for t in TOOLS])
def test_tool_is_a_valid_gemini_function(tool):
    # gemini-cli: the MCP inputSchema goes unchanged to Google as parametersJsonSchema, named mcp_<tool>.
    assert function_problems(f"mcp_{tool['name']}", tool["inputSchema"]) == []
    # code-assist: the same schema converted to Gemini's OpenAPI subset (`parameters`).
    assert function_problems(tool["name"], gemini_schema(tool["inputSchema"])) == []


def test_a_parameter_named_title_survives_flattening():
    visual = next(t for t in TOOLS if t["name"] == "wizard_render_visual")["inputSchema"]
    assert "title" in visual["required"] and visual["properties"]["title"]["type"] == "string"
    assert "title" not in visual and all("title" not in p for p in visual["properties"].values()), \
        "schema-metadata titles are still dropped"


def test_undocumented_constraints_are_described_not_sent_as_keywords():
    run_report = next(t for t in TOOLS if t["name"] == "nerp_run_report")["inputSchema"]
    report_id = run_report["properties"]["report_id"]
    assert "pattern" not in report_id and "(pattern ^" in report_id["description"]


@pytest.mark.parametrize("schema, expected", [
    ({"type": "object", "properties": {"a": {"type": "string", "minLength": 2}}}, "keyword minLength is not in Gemini's documented"),
    ({"type": "object", "properties": {}, "required": ["title"]}, "required property 'title' is not defined"),
    ({"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}}, "unsupported keyword $ref"),
    ({"type": "object", "properties": {"a": {"type": ["string", "null"]}}}, "type must be a single value"),
    ({"type": "object", "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}, "anyOf with null"),
    ({"type": "object", "properties": {"a": {"type": "array"}}}, "array without items"),
    ({"type": "object", "properties": {"bad name": {"type": "string"}}}, "parameter name"),
    ({"type": "object", "properties": {"a": {"type": "integer", "enum": [1, 2]}}}, "enum values must be strings"),
    ({"type": "object", "properties": {"a": {"description": "no type"}}}, "missing type"),
    ({"type": "string"}, "parameters must be an object schema"),
])
def test_rule_violations_are_named(schema, expected):
    assert any(expected in problem for problem in function_problems("tool", schema))


def test_function_names_follow_the_cli_limits():
    assert function_problems("mcp_nerp_run_report", {"type": "object", "properties": {}}) == []
    assert function_problems("1tool", {"type": "object"})
    assert function_problems("mcp_" + "x" * 60, {"type": "object"}), "the CLI mangles names of 64+ characters"
