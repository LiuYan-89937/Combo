from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import ValidationError

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter import FactoryRuntimeAdapter


def main() -> None:
    writer = _JsonLineWriter()
    adapter = FactoryRuntimeAdapter(emit=writer.write)
    writer.write(
        event(
            "runtime_ready",
            producer_type="factory_bridge",
            message="factory runtime bridge ready",
            graph_id="factory_bridge",
        )
    )
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            command = FactoryFrontendCommand.model_validate_json(raw)
        except ValidationError as exc:
            writer.write(event("error", message=f"invalid command: {exc}"))
            continue
        should_continue = adapter.handle(command)
        if not should_continue:
            break


class _JsonLineWriter:
    def write(self, payload: Any) -> None:
        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        sys.stdout.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
