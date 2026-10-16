from __future__ import annotations

from collections.abc import Iterator


def exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Walk explicit causes, unsuppressed contexts and exception-group members."""
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))
        cause = current.__cause__
        if cause is None and not current.__suppress_context__:
            cause = current.__context__
        if cause is not None:
            pending.append(cause)


def exception_leaf_messages(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        messages = [
            message
            for nested in exc.exceptions
            for message in exception_leaf_messages(nested)
        ]
        return list(dict.fromkeys(messages))
    message = str(exc).strip()
    return [f"{type(exc).__name__}: {message}" if message else type(exc).__name__]


def exception_contains(exc: BaseException, exception_type: type[BaseException]) -> bool:
    if isinstance(exc, exception_type):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(exception_contains(nested, exception_type) for nested in exc.exceptions)
    return False


def exception_summary(exc: BaseException) -> str:
    return "; ".join(exception_leaf_messages(exc))
