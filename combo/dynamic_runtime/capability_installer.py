from __future__ import annotations

from typing import Any, Callable

from combo.dynamic_runtime.mcp_gateway import MCPGateway
from combo.tooling.installers.mcp_config import normalize_mcp_server_config
from combo.tooling.installers.service import SkillPackageInstaller


ChangePublisher = Callable[[], None]


class CapabilityInstallerService:
    """Main-runtime facade for durable Skill and MCP capability installation."""

    def __init__(
        self,
        *,
        skill_packages: SkillPackageInstaller,
        mcp_gateway: MCPGateway,
        refresh_capability_search: ChangePublisher,
    ) -> None:
        self._skill_packages = skill_packages
        self._mcp_gateway = mcp_gateway
        self._refresh_capability_search = refresh_capability_search

    def install_skill(self, package: dict[str, Any]) -> dict[str, Any]:
        return self._skill_packages.install_package(package)

    def install_mcp(self, config: object) -> dict[str, Any]:
        server = normalize_mcp_server_config(config)
        self._mcp_gateway.add_server(
            server,
            expected_registry_digest=self._mcp_gateway.registry_digest(),
        )
        self._refresh_capability_search()
        installed = self._mcp_gateway.server(str(server["server_id"]))
        return {
            "message": f"MCP server installed: {installed.server_id}",
            "installed_server": {
                "server_id": installed.server_id,
                "display_name": str(installed.raw_config.get("display_name") or installed.server_id),
                "tool_count": len(installed.tools),
                "resource_count": len(installed.catalog.resources),
                "resource_template_count": len(installed.catalog.resource_templates),
                "prompt_count": len(installed.catalog.prompts),
            },
            "restart_required": False,
        }


