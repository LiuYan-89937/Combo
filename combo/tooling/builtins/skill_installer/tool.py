from __future__ import annotations

from typing import Any

from combo.runtime_protocol import RuntimeExecutionIdentity
from combo.tooling.builtins.skill_installer.specs import (
    CAPABILITY_INSTALLER_RESOURCE,
    RUNTIME_IDENTITY_RESOURCE,
)
from combo.tooling.envelope import tool_envelope
from combo.tooling.installers.service import CapabilityInstallerService


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "ask",
        "risk_level": "high",
        "reasons": ["installing a Skill persistently changes the global capability pool"],
    }


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    service = resources.get(CAPABILITY_INSTALLER_RESOURCE)
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE)
    if not isinstance(service, CapabilityInstallerService):
        raise RuntimeError("capability installer runtime is not configured")
    if not isinstance(identity, RuntimeExecutionIdentity) or identity.runtime_role != "main":
        raise PermissionError("Skill installation is available only to the main Agent")
    package = arguments.get("package")
    if not isinstance(package, dict):
        raise ValueError("Skill package must be an object")
    output = service.install_skill(package)
    return tool_envelope(output, summary=str(output["message"]))
