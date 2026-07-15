from __future__ import annotations

import argparse
from typing import Any

from fastapi import FastAPI

from agent_factory.local_inference.rocm import inspect_rocm_runtime


app = FastAPI(title="FastAgentFactory Inference Node Telemetry")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/runtime/rocm")
async def rocm_runtime() -> dict[str, Any]:
    return inspect_rocm_runtime(require_available=False).payload()


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose read-only ROCm telemetry for a remote inference node")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8004)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
