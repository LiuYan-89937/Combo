from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory.primitive_normalizer import normalize_primitives_candidate
from agent_factory.factory.primitive_planner import PrimitivePlanner
from agent_factory.factory.primitive_repair import PrimitiveRepair
from agent_factory.factory.types import FactoryCreateOptions, FactoryError, FactoryPrimitiveDraft
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.model import ModelService
from agent_factory.specs import AgentPackagePrimitives


class FactoryAgent:
    def __init__(
        self,
        model_service: ModelService,
        *,
        planner: PrimitivePlanner | None = None,
        repairer: PrimitiveRepair | None = None,
        writer: PackageWriter | None = None,
    ) -> None:
        self.model_service = model_service
        self.planner = planner or PrimitivePlanner(model_service)
        self.repairer = repairer or PrimitiveRepair(model_service)
        self.writer = writer or PackageWriter()

    async def create_primitives(
        self,
        requirement: str,
        context: FactoryRunContext,
        *,
        options: FactoryCreateOptions | None = None,
    ) -> FactoryPrimitiveDraft:
        options = options or FactoryCreateOptions()
        result = await self.planner.plan(context, requirement=requirement)
        if result.error:
            return FactoryPrimitiveDraft(
                requirement=requirement,
                error=FactoryError(
                    code=result.error.type,
                    message=result.error.message,
                ),
            )
        raw_data = result.data
        draft = self._validate_raw(requirement, raw_data, repair_attempts=0)
        if draft.ok:
            return draft

        attempts = 0
        while attempts < options.repair_attempts:
            attempts += 1
            repair_result = await self.repairer.repair(
                context,
                requirement=requirement,
                raw_model_data=raw_data,
                validation_errors=draft.error.message if draft.error else "unknown validation error",
            )
            if repair_result.error:
                return FactoryPrimitiveDraft(
                    requirement=requirement,
                    raw_model_data=_raw_mapping(raw_data),
                    repair_attempts=attempts,
                    error=FactoryError(
                        code=repair_result.error.type,
                        message=repair_result.error.message,
                    ),
                )
            raw_data = repair_result.data
            draft = self._validate_raw(requirement, raw_data, repair_attempts=attempts)
            if draft.ok:
                return draft
        return draft

    async def create_package(
        self,
        requirement: str,
        output_dir: str | Path,
        context: FactoryRunContext,
        *,
        options: FactoryCreateOptions | None = None,
    ) -> FactoryPrimitiveDraft:
        draft = await self.create_primitives(requirement, context, options=options)
        if not draft.ok or draft.primitives is None:
            return draft
        report = self.writer.write_primitives(output_dir, draft.primitives)
        return draft.model_copy(
            update={
                "validation_report": report,
                "output_path": Path(output_dir),
                "error": None
                if report.ok
                else FactoryError(code="package_validation_failed", message="Generated package failed validation."),
            }
        )

    @staticmethod
    def _validate_raw(
        requirement: str,
        raw_data: object,
        *,
        repair_attempts: int,
    ) -> FactoryPrimitiveDraft:
        raw_data = normalize_primitives_candidate(raw_data)
        try:
            primitives = AgentPackagePrimitives.model_validate(raw_data)
            return FactoryPrimitiveDraft(
                requirement=requirement,
                primitives=primitives,
                raw_model_data=_raw_mapping(raw_data),
                repair_attempts=repair_attempts,
            )
        except ValidationError as error:
            return FactoryPrimitiveDraft(
                requirement=requirement,
                raw_model_data=_raw_mapping(raw_data),
                repair_attempts=repair_attempts,
                error=FactoryError(
                    code="primitive_schema_validation_failed",
                    message=str(error),
                ),
            )


def _raw_mapping(raw_data: object) -> dict[str, Any] | list[Any] | None:
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, list):
        return raw_data
    return None
