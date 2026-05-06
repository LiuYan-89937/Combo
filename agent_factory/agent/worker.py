from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_factory.isolation import AgentIPCRequest, AgentIPCResponse
from agent_factory.runtime import AgentInstanceRuntime, AgentRunRequest


def main() -> None:
    line = sys.stdin.readline()
    try:
        ipc_request = AgentIPCRequest.model_validate_json(line)
        result = AgentInstanceRuntime(env_file=_factory_env_file(ipc_request.package_path)).run(
            AgentRunRequest(
                package_path=ipc_request.package_path,
                user_input=ipc_request.user_input,
                session_id=ipc_request.session_id,
                process_isolated=True,
                approved_tool_call_id=ipc_request.approved_tool_call_id,
            )
        )
        response = AgentIPCResponse(ok=True, payload=result.model_dump(mode="json"))
    except Exception as error:
        response = AgentIPCResponse(ok=False, error=str(error))
    print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False), flush=True)


def _factory_env_file(package_path: Path) -> Path:
    for parent in [package_path, *package_path.parents]:
        if parent.name == ".agentfactory":
            return parent.parent / ".env"
    return Path(".env")


if __name__ == "__main__":
    main()
