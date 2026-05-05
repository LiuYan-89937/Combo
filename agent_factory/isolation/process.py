from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin


class AgentIPCRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    package_path: Path
    user_input: str
    session_id: str = "default"
    approved_tool_call_id: str | None = None


class AgentIPCResponse(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentProcessManager:
    def run(self, request: AgentIPCRequest, *, timeout_seconds: int = 60) -> AgentIPCResponse:
        command = [sys.executable, "-m", "agent_factory.agent.worker"]
        completed = subprocess.run(
            command,
            input=request.model_dump_json() + "\n",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            return AgentIPCResponse(ok=False, error=completed.stderr.strip() or completed.stdout)
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            return AgentIPCResponse.model_validate_json(line)
        return AgentIPCResponse(ok=False, error="Agent worker returned no response.")
