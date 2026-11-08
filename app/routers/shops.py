"""Shop list, rename, archive, and the inline add form."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Shop
from app.services.parsing import FieldValidationError
from app.services.shops import (
    create_shop,
    list_shops,
    rename_shop,
    set_shop_active,
    shop_choices,
)
from app.templating import templates

router = APIRouter()


@router.get("/shops")
def shop_list(
    request: Request,
    status: str = "active",
    session: Session = Depends(get_db),
) -> Response:
    if status not in {"active", "archived", "all"}:
        status = "active"
    return templates.TemplateResponse(
        request,
        "shops/list.html",
        {"active": "ingredients", "shops": _visible(session, status), "status": status},
    )


@router.get("/shops/new")
def new_shop(request: Request) -> Response:
    return _shop_form(request, values={"name": "", "notes": ""}, errors={})


@router.get("/shops/inline")
def inline_shop(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "partials/shop_inline_form.html",
        {"values": {"name": "", "notes": ""}, "errors": {}},
    )


@router.post("/shops")
def post_shop(
    request: Request,
    name: str = Form(""),
    notes: str = Form(""),
    inline: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    try:
        shop = create_shop(session, name=name, notes=notes)
    except FieldValidationError as exc:
        values = {"name": name, "notes": notes}
        errors = {exc.field: str(exc)}
        if inline == "yes":
            return templates.TemplateResponse(
                request,
                "partials/shop_inline_form.html",
                {"values": values, "errors": errors},
            )
        return _shop_form(request, values=values, errors=errors)
    if inline == "yes":
        response = templates.TemplateResponse(
            request,
            "partials/shop_field.html",
            {
                "shops": shop_choices(session, selected_id=shop.id),
                "values": {"shop_id": str(shop.id)},
                "errors": {},
            },
        )
        response.headers["HX-Retarget"] = "#shop-field"
        response.headers["HX-Reswap"] = "outerHTML"
        return response
    return RedirectResponse("/shops", status_code=303)


@router.post("/shops/{shop_id}")
def post_rename_shop(
    request: Request,
    shop_id: int,
    name: str = Form(""),
    notes: str = Form(""),
    status: str = Form("active"),
    session: Session = Depends(get_db),
) -> Response:
    shop = session.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404)
    try:
        rename_shop(session, shop, name=name, notes=notes)
    except FieldValidationError as exc:
        return templates.TemplateResponse(
            request,
            "shops/list.html",
            {
                "active": "ingredients",
                "shops": _visible(session, status),
                "status": status,
                "errors": {shop_id: {exc.field: str(exc)}},
                "posted": {shop_id: {"name": name, "notes": notes}},
            },
            status_code=200,
        )
    return RedirectResponse(f"/shops?status={status}", status_code=303)


@router.post("/shops/{shop_id}/archive")
def archive_shop(shop_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    _set(session, shop_id, active=False)
    return RedirectResponse("/shops?status=archived", status_code=303)


@router.post("/shops/{shop_id}/restore")
def restore_shop(shop_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    _set(session, shop_id, active=True)
    return RedirectResponse("/shops?status=active", status_code=303)


def _shop_form(
    request: Request, *, values: dict[str, str], errors: dict[str, str]
) -> Response:
    return templates.TemplateResponse(
        request,
        "shops/form.html",
        {
            "active": "ingredients",
            "values": values,
            "errors": errors,
            "title": "New shop",
        },
    )


def _visible(session: Session, status: str) -> list[object]:
    if status == "archived":
        return [
            shop
            for shop in list_shops(session, include_archived=True)
            if not shop.is_active
        ]
    if status == "all":
        return list_shops(session, include_archived=True)
    return list_shops(session, include_archived=False)


def _set(session: Session, shop_id: int, *, active: bool) -> None:
    shop = session.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404)
    set_shop_active(session, shop, active=active)
