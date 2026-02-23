"""Materials management API endpoints."""

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from auth.google_oauth import credentials_from_token_row, refresh_if_needed, token_expiry_iso
from config import settings
from materials.extractor import extract_text_from_bytes

logger = logging.getLogger("meeting-proxy.materials")

router = APIRouter(tags=["materials"])

ALLOWED_UPLOAD_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}
ALLOWED_EXTENSIONS = {"pdf", "md", "txt", "markdown"}
MAX_MATERIAL_SIZE = 20 * 1024 * 1024  # 20 MB


def _get_repo(request: Request) -> Any:
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return repo


async def _ensure_meeting_exists(repo: Any, meeting_id: str) -> dict[str, Any]:
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.get("/meetings/{meeting_id}/materials")
async def list_materials(request: Request, meeting_id: str) -> JSONResponse:
    """List all materials for a meeting."""
    repo = _get_repo(request)
    await _ensure_meeting_exists(repo, meeting_id)
    materials = await repo.list_materials(meeting_id)
    return JSONResponse({"meeting_id": meeting_id, "materials": materials})


@router.post("/meetings/{meeting_id}/materials/upload")
async def upload_material(
    request: Request,
    meeting_id: str,
    file: UploadFile,
) -> JSONResponse:
    """Upload a PDF/MD/TXT file as meeting material."""
    repo = _get_repo(request)
    await _ensure_meeting_exists(repo, meeting_id)

    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_MATERIAL_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20MB)")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    extracted = await run_in_threadpool(extract_text_from_bytes, content, filename)

    upload_dir = Path(settings.materials_upload_dir) / meeting_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    file_path.write_bytes(content)

    material_id = await repo.add_material(
        {
            "meeting_id": meeting_id,
            "source_type": "upload",
            "filename": filename,
            "mime_type": file.content_type,
            "drive_file_id": None,
            "drive_file_type": None,
            "extracted_text": extracted,
            "file_path": str(file_path),
            "status": "extracted" if extracted else "error",
        }
    )

    logger.info("Material uploaded: %s (id=%d, %d chars extracted)", filename, material_id, len(extracted))
    return JSONResponse(
        {
            "id": material_id,
            "filename": filename,
            "extracted_length": len(extracted),
            "status": "extracted" if extracted else "error",
        }
    )


@router.post("/meetings/{meeting_id}/materials/drive")
async def link_drive_material(request: Request, meeting_id: str) -> JSONResponse:
    """Link a Google Drive file as meeting material."""
    repo = _get_repo(request)
    await _ensure_meeting_exists(repo, meeting_id)

    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="file_id is required")

    token_row = await repo.get_token()
    if not token_row:
        raise HTTPException(status_code=401, detail="Google account not linked")

    creds = credentials_from_token_row(token_row)
    refreshed, creds = refresh_if_needed(creds)
    if refreshed:
        await repo.update_token("default", creds.token, token_expiry_iso(creds))

    from materials.drive_client import build_drive_service, export_file_text, get_drive_file_type, get_file_metadata

    service = build_drive_service(creds)
    metadata = await run_in_threadpool(get_file_metadata, service, file_id)

    drive_mime = metadata.get("mimeType", "")
    drive_type = get_drive_file_type(drive_mime)

    extracted = ""
    if drive_type:
        extracted = await run_in_threadpool(export_file_text, service, file_id, drive_mime)

    material_id = await repo.add_material(
        {
            "meeting_id": meeting_id,
            "source_type": "google_drive",
            "filename": metadata.get("name", file_id),
            "mime_type": drive_mime,
            "drive_file_id": file_id,
            "drive_file_type": drive_type,
            "extracted_text": extracted,
            "file_path": None,
            "status": "extracted" if extracted else "pending",
        }
    )

    logger.info("Drive material linked: %s (id=%d)", metadata.get("name"), material_id)
    return JSONResponse(
        {
            "id": material_id,
            "filename": metadata.get("name", file_id),
            "drive_file_type": drive_type,
            "extracted_length": len(extracted),
            "status": "extracted" if extracted else "pending",
        }
    )


@router.delete("/meetings/{meeting_id}/materials/{material_id}")
async def delete_material(request: Request, meeting_id: str, material_id: int) -> JSONResponse:
    """Delete a meeting material."""
    repo = _get_repo(request)
    material = await repo.get_material(material_id)
    if not material or material["meeting_id"] != meeting_id:
        raise HTTPException(status_code=404, detail="Material not found")

    if material.get("file_path"):
        try:
            os.remove(material["file_path"])
        except OSError:
            logger.warning("Could not delete file: %s", material["file_path"])

    await repo.delete_material(material_id)
    logger.info("Material deleted: id=%d", material_id)
    return JSONResponse({"detail": "Material deleted", "id": material_id})
