from __future__ import annotations

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from web_frontend.backend.attachment_upload_store import (
    AttachmentUploadError,
    attachment_upload_store,
)


def create_attachment_router() -> APIRouter:
    router = APIRouter(prefix="/api/attachments", tags=["attachments"])

    @router.post("")
    async def upload_attachment(
        file: UploadFile = File(...),
        principal_id: str = Header(alias="X-Combo-Principal"),
    ) -> dict:
        try:
            staged = await attachment_upload_store().stage(file, principal_id=principal_id)
        except AttachmentUploadError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        finally:
            await file.close()
        return {"attachment": staged.frontend_payload()}

    @router.get("/{attachment_id}")
    async def read_attachment(
        attachment_id: str,
        principal_id: str = Header(alias="X-Combo-Principal"),
    ) -> FileResponse:
        try:
            staged = attachment_upload_store().resolve(attachment_id)
        except AttachmentUploadError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if staged.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="attachment not found")
        return FileResponse(
            staged.path,
            media_type=staged.mime_type or "application/octet-stream",
            filename=staged.name,
            content_disposition_type="inline",
        )

    return router
