from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from agent_factory.core.errors import AgentFactoryError

T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: T | None = None
    error: AgentFactoryError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T) -> "Result[T]":
        return cls(value=value)

    @classmethod
    def failure(cls, error: AgentFactoryError) -> "Result[T]":
        return cls(error=error)
