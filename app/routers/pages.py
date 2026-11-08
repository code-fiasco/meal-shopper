"""Placeholder pages for the main areas of the application."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.templating import templates

router = APIRouter()


def _page(request: Request, template_name: str, active: str) -> Response:
    return templates.TemplateResponse(
        request,
        template_name,
        {"active": active},
    )


@router.get("/spending")
def spending(request: Request) -> Response:
    return _page(request, "spending.html", "spending")
