from __future__ import annotations

import json
import sys
from typing import Any


TOOLS = [
    {
        "name": "search_policy",
        "description": "Search the MVP customer-service policy knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
]


def handle(request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        return {"serverInfo": {"name": "customer-kb-mock", "version": "0.1.0"}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        arguments = params.get("arguments") or {}
        query = str(arguments.get("query") or "")
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Policy search result for: {query}. Refunds and repairs require confirmation.",
                }
            ],
            "documents": [
                {
                    "id": "policy-refund-repair",
                    "title": "Refund and repair policy",
                    "text": "High-risk customer-service actions must be confirmed by a human.",
                }
            ],
        }
    raise ValueError(f"Unsupported MCP method: {method}")


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            result = handle(request)
            response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        except Exception as error:
            response = {"jsonrpc": "2.0", "id": request.get("id"), "error": str(error)}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
