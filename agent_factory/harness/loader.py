from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from agent_factory.factory.package_verification import VerificationIssue
from agent_factory.harness.scenario import HarnessSpec


class HarnessLoadError(Exception):
    def __init__(self, issues: list[VerificationIssue]):
        super().__init__("Harness spec could not be loaded")
        self.issues = issues


class HarnessLoader:
    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def load(self, package_path: str | Path) -> HarnessSpec:
        root = Path(package_path)
        path = root / "harness.yaml"
        issues: list[VerificationIssue] = []
        if not path.exists():
            raise HarnessLoadError(
                [
                    VerificationIssue(
                        code="harness_yaml_missing",
                        message="harness.yaml is required before test-agent can run.",
                        path="harness.yaml",
                    )
                ]
            )
        try:
            data = self._yaml.load(path.read_text(encoding="utf-8"))
        except Exception as error:
            raise HarnessLoadError(
                [
                    VerificationIssue(
                        code="harness_yaml_parse_error",
                        message=str(error),
                        path="harness.yaml",
                    )
                ]
            ) from error
        if not isinstance(data, dict):
            raise HarnessLoadError(
                [
                    VerificationIssue(
                        code="harness_yaml_invalid",
                        message="harness.yaml root must be a mapping.",
                        path="harness.yaml",
                    )
                ]
            )
        try:
            return HarnessSpec.model_validate(data)
        except ValidationError as error:
            for item in error.errors():
                location = ".".join(str(part) for part in item.get("loc", ()))
                issues.append(
                    VerificationIssue(
                        code="harness_schema_validation_error",
                        message=str(item.get("msg", "schema validation failed")),
                        path=f"harness.yaml:{location}" if location else "harness.yaml",
                    )
                )
            raise HarnessLoadError(issues) from error
