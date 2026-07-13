from __future__ import annotations

from backend.services.upload_document import UploadDocumentService


async def parse_document_text_task(text: str, session_id: str | None = None):
    return await UploadDocumentService().process_text(text=text, session_id=session_id)
