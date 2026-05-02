from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from agent_factory.package import PackageValidator
from agent_factory.specs import AgentPackagePrimitives


PRIMITIVE_FILE_MAP = {
    "instructions": "instructions.yaml",
    "output": "output.yaml",
    "conversation": "conversation.yaml",
    "run_context": "run_context.yaml",
    "toolsets": "toolsets.yaml",
    "knowledge": "knowledge.yaml",
    "guardrails": "guardrails.yaml",
    "handoffs": "handoffs.yaml",
    "observability": "observability.yaml",
}


class PackageWriter:
    def __init__(self, validator: PackageValidator | None = None) -> None:
        self.validator = validator or PackageValidator()
        self.yaml = YAML()
        self.yaml.default_flow_style = False

    def write_primitives(
        self,
        output_dir: str | Path,
        primitives: AgentPackagePrimitives,
    ):
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        dumped = primitives.model_dump(mode="json", by_alias=True, exclude_none=True)
        for field_name, filename in PRIMITIVE_FILE_MAP.items():
            with (root / filename).open("w", encoding="utf-8") as handle:
                self.yaml.dump(dumped[field_name], handle)
        return self.validator.validate_primitives(root)
