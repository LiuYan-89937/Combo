from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from agent_factory.tooling.builtins.browser.runtime import BrowserRuntime


def create_browser_view_router(logger: logging.Logger, runtime: BrowserRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/browser", tags=["browser"])

    @router.delete("/views/{view_id}/pages/{page_id}")
    async def close_browser_page(view_id: str, page_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                runtime.close_view_page,
                view_id=view_id,
                page_id=page_id,
            )
        except KeyError:
            return {
                "closed": False,
                "already_closed": True,
                "remaining_pages": 0,
                "browser_view_id": view_id,
                "closed_page_id": page_id,
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.websocket("/views/{view_id}/pages/{page_id}")
    async def browser_view(websocket: WebSocket, view_id: str, page_id: str) -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)

        def publish(frame: dict[str, Any]) -> None:
            def enqueue() -> None:
                if frames.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        frames.get_nowait()
                frames.put_nowait(frame)

            loop.call_soon_threadsafe(enqueue)

        try:
            subscription_id = await asyncio.to_thread(
                runtime.subscribe_view,
                view_id=view_id,
                page_id=page_id,
                callback=publish,
            )
        except KeyError:
            await websocket.send_json(
                {
                    "type": "closed",
                    "browser_view_id": view_id,
                    "page_id": page_id,
                    "reason": "page_not_found",
                }
            )
            await websocket.close(code=4404)
            return
        except Exception as exc:
            await websocket.send_json({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            await websocket.close(code=4404)
            return

        async def send_frames() -> None:
            while True:
                event = await frames.get()
                if event.get("type") != "frame":
                    await websocket.send_json(event)
                    continue
                encoded = str(event.pop("data", "") or "")
                try:
                    frame_bytes = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    logger.warning("Browser view emitted an invalid frame for %s/%s", view_id, page_id)
                    continue
                await websocket.send_json({**event, "type": "frame_metadata"})
                await websocket.send_bytes(frame_bytes)

        sender = asyncio.create_task(send_frames(), name=f"browser-view-{view_id[:8]}")
        try:
            while True:
                event = await websocket.receive_json()
                if not isinstance(event, dict):
                    continue
                await asyncio.to_thread(
                    runtime.dispatch_view_input,
                    view_id=view_id,
                    page_id=page_id,
                    event=event,
                )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("Browser view input failed: %s: %s", type(exc).__name__, exc)
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
            with contextlib.suppress(Exception):
                await asyncio.to_thread(runtime.unsubscribe_view, subscription_id)

    return router
