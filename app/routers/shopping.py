"""Shopping list pages. Line edits swap the list body."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_db
from app.models import Shop, ShoppingList, ShoppingListLine
from app.services.parsing import (
    FieldValidationError,
    InvalidPriceError,
    parse_gbp_to_pence,
    parse_recipe_quantity,
)
from app.services.planner import get_week, local_today, week_start_for
from app.services.shopping import (
    ORDER_NAME,
    ORDER_SHOP,
    ShoppingPage,
    add_manual_line,
    checklist_for,
    choose_purchase_option,
    cover_requirement_with_stock,
    refresh_shopping_list,
    remove_generated_line,
    restore_removed_line,
    set_line_checked,
    set_line_price,
    set_pack_count_override,
    set_quantity_override,
    shopping_page_for,
)
from app.services.shops import list_shops
from app.services.units import InvalidQuantityError
from app.templating import templates

router = APIRouter()


@router.get("/shopping")
def shopping_page(
    request: Request,
    date_value: Annotated[str, Query(alias="date")] = "",
    notice: str = "",
    session: Session = Depends(get_db),
) -> Response:
    today = _today()
    anchor, date_error = _anchor(date_value, today)
    page = shopping_page_for(
        session,
        anchor,
        today=today,
        notice=_clean_notice(notice),
        error=date_error,
    )
    return _full(request, session, page)


@router.post("/shopping/generate")
def post_generate(
    request: Request,
    date_value: Annotated[str, Form(alias="date")] = "",
    session: Session = Depends(get_db),
) -> Response:
    today = _today()
    anchor, date_error = _anchor(date_value, today)
    if date_error is not None:
        page = shopping_page_for(session, anchor, today=today, error=date_error)
        return _full(request, session, page)
    week = get_week(session, anchor)
    if week is None:
        page = shopping_page_for(
            session,
            anchor,
            today=today,
            error="Choose a week that has been planned.",
        )
        return _full(request, session, page)
    _shopping_list, summary = refresh_shopping_list(session, week.id)
    return RedirectResponse(_location(week.week_start_date, summary.label()), 303)


@router.post("/shopping/lines/{line_id}")
def post_line(
    request: Request,
    line_id: int,
    action: str = Form(""),
    option_id: str = Form(""),
    quantity: str = Form(""),
    pack_count: str = Form(""),
    price: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    line = _load_line(session, line_id)
    start = line.shopping_list.week.week_start_date
    notice: str | None = None
    errors: dict[str, str] = {}
    try:
        notice = _apply_line(
            session,
            line,
            action=action,
            option_id=option_id,
            quantity=quantity,
            pack_count=pack_count,
            price=price,
        )
    except FieldValidationError as exc:
        errors = {exc.field: str(exc)}
    page = shopping_page_for(
        session,
        start,
        today=_today(),
        notice=notice,
        line_errors={line.id: errors} if errors else None,
    )
    if _htmx(request):
        return _body(request, session, page)
    if errors:
        return _full(request, session, page)
    return RedirectResponse(_location(start, notice), status_code=303)


@router.post("/shopping/manual")
def post_manual(
    request: Request,
    date_value: Annotated[str, Form(alias="date")] = "",
    description: str = Form(""),
    quantity: str = Form(""),
    unit: str = Form(""),
    price: str = Form(""),
    shop_id: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    today = _today()
    anchor, date_error = _anchor(date_value, today)
    values = {
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "price": price,
        "shop_id": shop_id,
    }
    if date_error is not None:
        page = shopping_page_for(session, anchor, today=today, error=date_error)
        return _full(request, session, page)
    week = get_week(session, anchor)
    shopping_list = _list_for(session, week.id) if week is not None else None
    if shopping_list is None:
        page = shopping_page_for(
            session,
            anchor,
            today=today,
            form_errors={"description": "Generate the list before adding an item."},
            form_values=values,
        )
        return _respond(request, session, page)
    try:
        amount, symbol, pence, shop_name = _manual_fields(
            session, quantity=quantity, unit=unit, price=price, shop_id=shop_id
        )
        add_manual_line(
            session,
            shopping_list,
            description=description,
            quantity=amount,
            unit=symbol,
            price_pence=pence,
            shop_name=shop_name,
        )
    except FieldValidationError as exc:
        page = shopping_page_for(
            session,
            anchor,
            today=today,
            form_errors={exc.field: str(exc)},
            form_values=values,
        )
        return _respond(request, session, page)
    page = shopping_page_for(session, anchor, today=today, notice="Item added.")
    if _htmx(request):
        return _body(request, session, page)
    return RedirectResponse(_location(anchor, "Item added."), status_code=303)


@router.get("/shopping/{list_id}/checklist")
def checklist_page(
    request: Request,
    list_id: int,
    order: str = ORDER_SHOP,
    session: Session = Depends(get_db),
) -> Response:
    shopping_list = _load_list(session, list_id)
    checklist = checklist_for(shopping_list, order=_known_order(order))
    return templates.TemplateResponse(
        request,
        "shopping/checklist.html",
        {"active": "shopping", "checklist": checklist},
    )


@router.get("/shopping/{list_id}/print")
def checklist_print(
    request: Request,
    list_id: int,
    boxes: str = "1",
    session: Session = Depends(get_db),
) -> Response:
    shopping_list = _load_list(session, list_id)
    checklist = checklist_for(
        shopping_list, order=ORDER_SHOP, show_boxes=boxes != "0"
    )
    return templates.TemplateResponse(
        request,
        "shopping/print.html",
        {"checklist": checklist},
    )


@router.post("/shopping/lines/{line_id}/check")
def post_check(
    request: Request,
    line_id: int,
    checked: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    line = _load_line(session, line_id)
    try:
        set_line_checked(line, _is_checked(checked))
    except FieldValidationError as exc:
        if _htmx(request):
            return Response(f"Error: {exc}", status_code=422)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    checklist = checklist_for(line.shopping_list, order=ORDER_SHOP)
    if _htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/checklist_totals.html",
            {"checklist": checklist},
        )
    return RedirectResponse(
        f"/shopping/{line.list_id}/checklist", status_code=303
    )


def _apply_line(
    session: Session,
    line: ShoppingListLine,
    *,
    action: str,
    option_id: str,
    quantity: str,
    pack_count: str,
    price: str,
) -> str | None:
    if action == "option":
        choose_purchase_option(session, line, _option_id(option_id))
        return None
    if action == "quantity":
        symbol = line.unit_snapshot or "units"
        set_quantity_override(line, _quantity(quantity, symbol))
        return None
    if action == "packs":
        set_pack_count_override(line, _packs(pack_count))
        return None
    if action == "price":
        set_line_price(line, _pence(price))
        return None
    if action == "remove":
        remove_generated_line(line)
        return None
    if action == "restore":
        restore_removed_line(line)
        return None
    if action == "have":
        return cover_requirement_with_stock(session, line).label()
    raise HTTPException(status_code=400)


def _manual_fields(
    session: Session,
    *,
    quantity: str,
    unit: str,
    price: str,
    shop_id: str,
) -> tuple[Decimal | None, str | None, int | None, str | None]:
    amount, symbol = _optional_quantity(quantity, unit)
    return amount, symbol, _optional_pence(price), _shop_name(session, shop_id)


def _optional_quantity(quantity: str, unit: str) -> tuple[Decimal | None, str | None]:
    amount = quantity.strip()
    symbol = unit.strip()
    if not amount and not symbol:
        return None, None
    if not amount or not symbol:
        raise FieldValidationError(
            "quantity", "Enter both a quantity and a unit, or leave both blank."
        )
    return _quantity(amount, symbol), symbol


def _quantity(raw: str, unit_symbol: str) -> Decimal:
    try:
        return parse_recipe_quantity(raw, unit_symbol=unit_symbol)
    except InvalidQuantityError as exc:
        raise FieldValidationError("quantity", str(exc)) from exc


def _packs(raw: str) -> int:
    text = raw.strip()
    if not text.isdigit():
        raise FieldValidationError(
            "pack_count", "Enter a whole number of packs, such as 2."
        )
    return int(text)


def _pence(raw: str) -> int:
    try:
        return parse_gbp_to_pence(raw)
    except InvalidPriceError as exc:
        raise FieldValidationError("price", str(exc)) from exc


def _optional_pence(raw: str) -> int | None:
    if not raw.strip():
        return None
    return _pence(raw)


def _option_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise FieldValidationError("option_id", "Choose a pack.") from None


def _shop_name(session: Session, raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    try:
        shop_id = int(text)
    except ValueError:
        raise FieldValidationError("shop_id", "Choose a shop.") from None
    shop = session.get(Shop, shop_id)
    if shop is None or not shop.is_active:
        raise FieldValidationError("shop_id", "Choose a shop.")
    return shop.name


def _load_list(session: Session, list_id: int) -> ShoppingList:
    shopping_list = session.scalar(
        select(ShoppingList)
        .where(ShoppingList.id == list_id)
        .options(
            selectinload(ShoppingList.lines),
            selectinload(ShoppingList.week),
        )
    )
    if shopping_list is None:
        raise HTTPException(status_code=404)
    return shopping_list


def _known_order(raw: str) -> str:
    if raw == ORDER_NAME:
        return ORDER_NAME
    return ORDER_SHOP


def _is_checked(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "on", "yes"}


def _load_line(session: Session, line_id: int) -> ShoppingListLine:
    line = session.scalar(
        select(ShoppingListLine)
        .where(ShoppingListLine.id == line_id)
        .options(
            selectinload(ShoppingListLine.shopping_list).selectinload(ShoppingList.week)
        )
    )
    if line is None or line.shopping_list is None:
        raise HTTPException(status_code=404)
    return line


def _list_for(session: Session, week_id: int) -> ShoppingList | None:
    return session.scalar(
        select(ShoppingList).where(ShoppingList.planner_week_id == week_id)
    )


def _respond(request: Request, session: Session, page: ShoppingPage) -> Response:
    if _htmx(request):
        return _body(request, session, page)
    return _full(request, session, page)


def _full(request: Request, session: Session, page: ShoppingPage) -> Response:
    return templates.TemplateResponse(
        request, "shopping/index.html", _context(session, page)
    )


def _body(request: Request, session: Session, page: ShoppingPage) -> Response:
    return templates.TemplateResponse(
        request, "partials/shopping_body.html", _context(session, page)
    )


def _context(session: Session, page: ShoppingPage) -> dict[str, object]:
    return {"active": "shopping", "page": page, "shops": list_shops(session)}


def _location(day: date, notice: str | None) -> str:
    query = f"/shopping?date={week_start_for(day).isoformat()}"
    if notice:
        query += f"&notice={quote(notice)}"
    return query


def _anchor(raw: str, today: date) -> tuple[date, str | None]:
    if not raw:
        return today, None
    parsed = _parse_date(raw)
    if parsed is None:
        return today, "Choose a valid date."
    return parsed, None


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _clean_notice(raw: str) -> str | None:
    text = " ".join(raw.split())
    if not text or len(text) > 120:
        return None
    return text


def _today() -> date:
    return local_today(get_settings().app_timezone)


def _htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
