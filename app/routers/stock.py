"""Stock page and the quick-edit control the shopping list can embed."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.parsing import FieldValidationError
from app.services.stock import (
    StockControl,
    adjust_stock,
    list_stock_controls,
    search_ingredients_for_stock,
    stock_control,
)
from app.templating import templates

router = APIRouter()


@router.get("/stock")
def stock_page(request: Request, session: Session = Depends(get_db)) -> Response:
    return _page(request, session, query="", searched=False, matches=None, editor=None)


@router.get("/stock/search")
def stock_search(
    request: Request, q: str = "", session: Session = Depends(get_db)
) -> Response:
    matches = search_ingredients_for_stock(session, q)
    if _htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/stock_search_results.html",
            {"matches": matches},
        )
    return _page(request, session, query=q, searched=True, matches=matches, editor=None)


@router.get("/stock/ingredients/{ingredient_id}")
def stock_ingredient(
    request: Request, ingredient_id: int, session: Session = Depends(get_db)
) -> Response:
    control = stock_control(session, ingredient_id, placement="editor")
    if control is None:
        raise HTTPException(status_code=404)
    if _htmx(request):
        return templates.TemplateResponse(
            request, "partials/stock_control.html", {"control": control}
        )
    return _page(
        request, session, query="", searched=False, matches=None, editor=control
    )


@router.post("/stock/items")
def post_stock_item(
    request: Request,
    ingredient_id: str = Form(""),
    quantity: str = Form(""),
    unit_id: str = Form(""),
    action: str = Form(""),
    placement: str = Form("list"),
    session: Session = Depends(get_db),
) -> Response:
    where = placement if placement in {"list", "editor"} else "list"
    parsed_id = _ingredient_id(ingredient_id)
    try:
        adjust_stock(
            session,
            ingredient_id=parsed_id,
            action=action,
            quantity=quantity,
            unit_id=unit_id,
        )
    except FieldValidationError as exc:
        return _reject(
            request,
            session,
            parsed_id,
            where,
            quantity,
            unit_id,
            {exc.field: str(exc)},
        )
    if not _htmx(request):
        return RedirectResponse("/stock", status_code=303)
    control = stock_control(session, parsed_id, placement=where)
    if control is None:
        raise HTTPException(status_code=404)
    return _saved(request, session, control)


def _reject(
    request: Request,
    session: Session,
    ingredient_id: int,
    placement: str,
    quantity: str,
    unit_id: str,
    errors: dict[str, str],
) -> Response:
    control = stock_control(
        session,
        ingredient_id,
        placement=placement,
        quantity_input=quantity,
        unit_id=unit_id,
        errors=errors,
    )
    if control is None:
        return templates.TemplateResponse(
            request,
            "partials/stock_missing.html",
            {},
            status_code=200,
        )
    if _htmx(request):
        return templates.TemplateResponse(
            request, "partials/stock_control.html", {"control": control}
        )
    items, editor = _overlay(list_stock_controls(session), control)
    return _render(
        request,
        items=items,
        query="",
        searched=False,
        matches=[],
        editor=editor,
    )


def _saved(request: Request, session: Session, control: StockControl) -> Response:
    if control.placement == "editor":
        return templates.TemplateResponse(
            request,
            "partials/stock_control_update.html",
            {
                "control": control,
                "items": list_stock_controls(session),
                "oob": True,
            },
        )
    echo = stock_control(session, control.ingredient_id, placement="editor")
    return templates.TemplateResponse(
        request,
        "partials/stock_list_saved.html",
        {"control": control, "echo": echo},
    )


def _overlay(
    items: list[StockControl], failed: StockControl
) -> tuple[list[StockControl], StockControl | None]:
    if failed.placement != "list":
        return items, failed
    updated: list[StockControl] = []
    replaced = False
    for item in items:
        if item.ingredient_id == failed.ingredient_id:
            updated.append(failed)
            replaced = True
        else:
            updated.append(item)
    if replaced:
        return updated, None
    return items, failed


def _page(
    request: Request,
    session: Session,
    *,
    query: str,
    searched: bool,
    matches: list[object] | None,
    editor: StockControl | None,
) -> Response:
    found = [] if matches is None else matches
    return _render(
        request,
        items=list_stock_controls(session),
        query=query,
        searched=searched,
        matches=found,
        editor=editor,
    )


def _render(
    request: Request,
    *,
    items: list[StockControl],
    query: str,
    searched: bool,
    matches: list[object],
    editor: StockControl | None,
) -> Response:
    return templates.TemplateResponse(
        request,
        "stock/index.html",
        {
            "active": "stock",
            "items": items,
            "query": query,
            "searched": searched,
            "matches": matches,
            "editor": editor,
        },
    )


def _ingredient_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        return 0


def _htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
