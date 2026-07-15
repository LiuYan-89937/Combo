from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_factory.benchmarking import BenchmarkRunSpec, BenchmarkService


def create_benchmark_router(service: BenchmarkService) -> APIRouter:
    router = APIRouter(prefix="/api/benchmarks")

    @router.get("")
    async def list_runs(limit: int = 100):
        return {
            "runs": [run.model_dump(mode="json") for run in service.list_runs(limit=limit)]
        }

    @router.get("/{run_id}")
    async def get_run(run_id: str):
        try:
            run = service.require_run(run_id)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"run": run.model_dump(mode="json")}

    @router.post("")
    async def start_run(payload: dict):
        try:
            run = await service.start_run(BenchmarkRunSpec.model_validate(payload))
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"run": run.model_dump(mode="json")}

    @router.post("/{run_id}/cancel")
    async def cancel_run(run_id: str):
        try:
            run = await service.cancel_run(run_id)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"run": run.model_dump(mode="json")}

    @router.delete("/{run_id}")
    async def delete_run(run_id: str):
        try:
            deleted = service.delete_run(run_id)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"deleted": deleted}

    return router


def _http_error(exc: Exception) -> HTTPException:
    detail = f"{type(exc).__name__}: {exc}"
    if str(exc).startswith("unknown benchmark run:"):
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=400, detail=detail)
