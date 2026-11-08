"""Backup download. The page does not change recipes or plans."""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from app.config import get_settings
from app.services.backup import write_timestamped_backup
from app.templating import templates

router = APIRouter()


@router.get("/settings")
def settings_page(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"active": "settings"},
    )


@router.get("/settings/backup")
def download_backup() -> FileResponse:
    path = write_timestamped_backup(get_settings().database_url)
    return FileResponse(
        path,
        media_type="application/vnd.sqlite3",
        filename=path.name,
    )
