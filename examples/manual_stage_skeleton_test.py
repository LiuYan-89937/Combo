from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_factory.application import CreateAgentRequest, CreateAgentService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the 14-stage LangGraph skeleton stage by stage.")
    parser.add_argument("--input", "-i", required=True, help="Natural language requirement.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = CreateAgentService()
    rows = []
    for stage in service.available_stages():
        result = service.create_agent(CreateAgentRequest(prompt=args.input, stop_after_stage=stage))
        rows.append(
            {
                "stage": stage,
                "status": result.status,
                "breakpoint": result.breakpoint_details,
                "stage_history": result.stage_history,
            }
        )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for row in rows:
        print(f"{row['stage']}: {row['status']}")
        print(f"  history={row['stage_history']}")
        if row["breakpoint"]:
            print(f"  breakpoint={json.dumps(row['breakpoint'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
