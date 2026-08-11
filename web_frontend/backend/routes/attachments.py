from __future__ import annotations

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from web_frontend.backend.attachment_upload_store import (
    AttachmentUploadError,
    attachment_upload_store,
)


def create_attachment_router() -> APIRouter:
    router = APIRouter(prefix="/api/attachments", tags=["attachments"])

    @router.post("")
    async def upload_attachment(
        file: UploadFile = File(...),
        principal_id: str = Header(alias="X-AgentFactory-Principal"),
    ) -> dict:
        try:
            staged = await attachment_upload_store().stage(file, principal_id=principal_id)
        except AttachmentUploadError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        finally:
            await file.close()
        return {"attachment": staged.frontend_payload()}

    return router
