from __future__ import annotations

from combo.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


CAPABILITY_INSTALLER_RESOURCE = "capability_installer_runtime"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"


def get_mcp_installer_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="mcp_installer",
            description=(
                "Install one MCP server from a complete standard client configuration after obtaining it "
                "from an authoritative source. JSON/YAML text and decoded configuration objects are accepted. "
                "Few-shot: Official documentation provides "
                "{\"mcpServers\":{\"amap\":{\"url\":\"https://example.com/mcp\"}}} -> pass the complete "
                "document as server_config. Only a service name is known -> do not guess a command, URL, headers, "
                "or environment values; find the official executable configuration first."
            ),
            entrypoint="combo.tooling.builtins.mcp_installer.tool:run",
            input_schema={
                "type": "object",
                "properties": {
                    "server_config": {
                        "description": "完整 MCP 配置对象，或包含该对象的 JSON/YAML 文本。",
                        "oneOf": [
                            {"type": "object"},
                            {"type": "string", "minLength": 1},
                        ],
                    }
                },
                "required": ["server_config"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            resources={
                CAPABILITY_INSTALLER_RESOURCE: CAPABILITY_INSTALLER_RESOURCE,
                RUNTIME_IDENTITY_RESOURCE: RUNTIME_IDENTITY_RESOURCE,
            },
            risk_level="high",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="combo.tooling.builtins.mcp_installer.tool:evaluate_risk",
            ),
            concurrent=False,
            max_parallel_calls=1,
            sensitive_argument_paths=["/server_config"],
            effects=["write", "network", "process", "credential", "external_side_effect"],
            system_available=True,
        )
    ]
