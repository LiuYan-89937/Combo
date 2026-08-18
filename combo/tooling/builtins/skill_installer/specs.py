from __future__ import annotations

from combo.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


CAPABILITY_INSTALLER_RESOURCE = "capability_installer_runtime"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"


def get_skill_installer_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="skill_installer",
            description=(
                "Install one complete Skill package after you have obtained all of its files. "
                "Few-shot: User asks to install a Skill shown on a web page and you have collected "
                "SKILL.md plus references/guide.md -> call skill_installer with both files in package.files. "
                "User provides only a repository URL and its files have not been read -> do not call yet; "
                "retrieve and assemble the complete package first. Never invent missing package content."
            ),
            entrypoint="combo.tooling.builtins.skill_installer.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                CAPABILITY_INSTALLER_RESOURCE: CAPABILITY_INSTALLER_RESOURCE,
                RUNTIME_IDENTITY_RESOURCE: RUNTIME_IDENTITY_RESOURCE,
            },
            risk_level="high",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="combo.tooling.builtins.skill_installer.tool:evaluate_risk",
            ),
            concurrent=False,
            max_parallel_calls=1,
            sensitive_argument_paths=["/package/files"],
            effects=["write", "external_side_effect"],
            system_available=True,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "package": {
                "type": "object",
                "description": "完整 Skill 包；files 必须包含根目录 SKILL.md 以及它引用的全部资源。",
                "properties": {
                    "files": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": "相对 Skill 包根目录的 POSIX 路径。",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "UTF-8 文本文件的完整内容。",
                                },
                                "content_base64": {
                                    "type": "string",
                                    "description": "二进制文件的完整 Base64 内容。",
                                },
                            },
                            "required": ["path"],
                            "oneOf": [
                                {"required": ["content"], "not": {"required": ["content_base64"]}},
                                {"required": ["content_base64"], "not": {"required": ["content"]}},
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["files"],
                "additionalProperties": False,
            }
        },
        "required": ["package"],
        "additionalProperties": False,
    }
