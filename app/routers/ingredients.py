"""Ingredient and purchase-option pages."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.formatting import format_gbp_input, format_local, format_quantity_input
from app.models import PurchaseOption, Shop, Unit
from app.services.ingredients import (
    DuplicateIngredient,
    FieldValidationError,
    collect_ingredient_errors,
    create_ingredient,
    get_ingredient,
    list_ingredients,
    purchase_option_views,
    set_default_purchase_option,
    set_ingredient_active,
    update_ingredient,
)
from app.services.parsing import (
    InvalidPriceError,
    parse_gbp_to_pence,
    parse_pack_quantity,
)
from app.services.purchase_options import (
    change_purchase_option,
    create_purchase_option,
    list_price_history,
)
from app.services.shops import shop_choices
from app.services.unit_catalog import units_by_family
from app.services.units import InvalidQuantityError
from app.templating import templates

router = APIRouter()


@router.get("/ingredients")
def ingredient_list(
    request: Request,
    q: str = "",
    status: str = "active",
    session: Session = Depends(get_db),
) -> Response:
    if status not in {"active", "archived", "all"}:
        status = "active"
    context = _list_context(session, query=q, status=status)
    template = (
        "partials/ingredient_results.html"
        if _htmx(request)
        else "ingredients/list.html"
    )
    return templates.TemplateResponse(request, template, context)


@router.get("/ingredients/new")
def new_ingredient(request: Request, session: Session = Depends(get_db)) -> Response:
    return _ingredient_page(
        request, session, title="New ingredient", action="/ingredients"
    )


@router.get("/ingredients/form")
def ingredient_form_partial(
    request: Request, line: str = "", session: Session = Depends(get_db)
) -> Response:
    return _ingredient_form(
        request,
        session,
        action="/ingredients",
        embed=True,
        values=_blank_ingredient(),
        errors={},
        line=line,
    )


@router.post("/ingredients")
def post_ingredient(
    request: Request,
    name: str = Form(""),
    canonical_unit_id: str = Form(""),
    notes: str = Form(""),
    confirm_duplicate: str = Form(""),
    embed: str = Form(""),
    line: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    return _save_ingredient(
        request,
        session,
        ingredient=None,
        name=name,
        canonical_unit_id=canonical_unit_id,
        notes=notes,
        confirm_duplicate=confirm_duplicate == "yes",
        embed=embed == "1"
        or (_htmx(request) and request.query_params.get("embed") == "1"),
        line=line,
    )


@router.get("/ingredients/{ingredient_id}")
def ingredient_detail(
    request: Request, ingredient_id: int, session: Session = Depends(get_db)
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    return templates.TemplateResponse(
        request,
        "ingredients/detail.html",
        {
            "active": "ingredients",
            "ingredient": ingredient,
            "options": purchase_option_views(ingredient),
        },
    )


@router.get("/ingredients/{ingredient_id}/edit")
def edit_ingredient(
    request: Request, ingredient_id: int, session: Session = Depends(get_db)
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    return _ingredient_page(
        request,
        session,
        title=f"Edit {ingredient.name}",
        action=f"/ingredients/{ingredient.id}",
        values=_ingredient_values(ingredient),
        unit_locked=_unit_locked(session, ingredient.id),
        locked_unit=ingredient.canonical_unit,
    )


@router.post("/ingredients/{ingredient_id}")
def post_edit_ingredient(
    request: Request,
    ingredient_id: int,
    name: str = Form(""),
    canonical_unit_id: str = Form(""),
    notes: str = Form(""),
    confirm_duplicate: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    return _save_ingredient(
        request,
        session,
        ingredient=ingredient,
        name=name,
        canonical_unit_id=canonical_unit_id,
        notes=notes,
        confirm_duplicate=confirm_duplicate == "yes",
        embed=False,
    )


@router.post("/ingredients/{ingredient_id}/archive")
def archive_ingredient(
    ingredient_id: int, session: Session = Depends(get_db)
) -> RedirectResponse:
    ingredient = _require_ingredient(session, ingredient_id)
    set_ingredient_active(session, ingredient, active=False)
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.post("/ingredients/{ingredient_id}/restore")
def restore_ingredient(
    ingredient_id: int, session: Session = Depends(get_db)
) -> RedirectResponse:
    ingredient = _require_ingredient(session, ingredient_id)
    set_ingredient_active(session, ingredient, active=True)
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.get("/ingredients/{ingredient_id}/options/new")
def new_option(
    request: Request, ingredient_id: int, session: Session = Depends(get_db)
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    return _option_page(
        request,
        session,
        ingredient=ingredient,
        title="Add purchase option",
        action=f"/ingredients/{ingredient.id}/options",
        values=_blank_option(),
        errors={},
    )


@router.post("/ingredients/{ingredient_id}/options")
def post_option(
    request: Request,
    ingredient_id: int,
    shop_id: str = Form(""),
    pack_quantity: str = Form(""),
    pack_label: str = Form(""),
    price: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    parsed, errors = _parse_option(
        session,
        shop_id=shop_id,
        pack_quantity=pack_quantity,
        pack_label=pack_label,
        price=price,
        unit_symbol=ingredient.canonical_unit.symbol,
    )
    if errors or parsed is None:
        return _option_page(
            request,
            session,
            ingredient=ingredient,
            title="Add purchase option",
            action=f"/ingredients/{ingredient.id}/options",
            values=_posted_option(shop_id, pack_quantity, pack_label, price),
            errors=errors,
        )
    create_purchase_option(
        session,
        ingredient=ingredient,
        shop=parsed["shop"],
        pack_quantity=parsed["pack_quantity"],
        pack_label=parsed["pack_label"],
        price_pence=parsed["price_pence"],
    )
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.get("/ingredients/{ingredient_id}/options/{option_id}/edit")
def edit_option(
    request: Request,
    ingredient_id: int,
    option_id: int,
    session: Session = Depends(get_db),
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    option = _require_option(ingredient, option_id)
    return _option_page(
        request,
        session,
        ingredient=ingredient,
        title=f"Edit {option.pack_label}",
        action=f"/ingredients/{ingredient.id}/options/{option.id}",
        values=_option_values(option),
        errors={},
    )


@router.post("/ingredients/{ingredient_id}/options/{option_id}")
def post_edit_option(
    request: Request,
    ingredient_id: int,
    option_id: int,
    shop_id: str = Form(""),
    pack_quantity: str = Form(""),
    pack_label: str = Form(""),
    price: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    option = _require_option(ingredient, option_id)
    parsed, errors = _parse_option(
        session,
        shop_id=shop_id,
        pack_quantity=pack_quantity,
        pack_label=pack_label,
        price=price,
        unit_symbol=ingredient.canonical_unit.symbol,
    )
    action = f"/ingredients/{ingredient.id}/options/{option.id}"
    if errors or parsed is None:
        return _option_page(
            request,
            session,
            ingredient=ingredient,
            title=f"Edit {option.pack_label}",
            action=action,
            values=_posted_option(shop_id, pack_quantity, pack_label, price),
            errors=errors,
        )
    change_purchase_option(
        session,
        option,
        shop=parsed["shop"],
        pack_quantity=parsed["pack_quantity"],
        pack_label=parsed["pack_label"],
        price_pence=parsed["price_pence"],
    )
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.post("/ingredients/{ingredient_id}/options/{option_id}/archive")
def archive_option(
    ingredient_id: int, option_id: int, session: Session = Depends(get_db)
) -> RedirectResponse:
    ingredient = _require_ingredient(session, ingredient_id)
    option = _require_option(ingredient, option_id)
    change_purchase_option(session, option, is_active=False)
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.post("/ingredients/{ingredient_id}/options/{option_id}/default")
def choose_recipe_default(
    ingredient_id: int, option_id: int, session: Session = Depends(get_db)
) -> RedirectResponse:
    ingredient = _require_ingredient(session, ingredient_id)
    option = _require_option(ingredient, option_id)
    set_default_purchase_option(ingredient, option)
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.post("/ingredients/{ingredient_id}/options/{option_id}/default/clear")
def clear_recipe_default(
    ingredient_id: int, option_id: int, session: Session = Depends(get_db)
) -> RedirectResponse:
    ingredient = _require_ingredient(session, ingredient_id)
    _require_option(ingredient, option_id)
    set_default_purchase_option(ingredient, None)
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.post("/ingredients/{ingredient_id}/options/{option_id}/restore")
def restore_option(
    ingredient_id: int, option_id: int, session: Session = Depends(get_db)
) -> RedirectResponse:
    ingredient = _require_ingredient(session, ingredient_id)
    option = _require_option(ingredient, option_id)
    change_purchase_option(session, option, is_active=True)
    return RedirectResponse(f"/ingredients/{ingredient.id}", status_code=303)


@router.get("/ingredients/{ingredient_id}/options/{option_id}/history")
def option_history(
    request: Request,
    ingredient_id: int,
    option_id: int,
    session: Session = Depends(get_db),
) -> Response:
    ingredient = _require_ingredient(session, ingredient_id)
    option = _require_option(ingredient, option_id)
    timezone_name = get_settings().app_timezone
    history = list_price_history(session, option)
    oldest_first = list(reversed(history))
    context = {
        "active": "ingredients",
        "ingredient": ingredient,
        "option": option,
        "history": history,
        "timezone_name": timezone_name,
        "chart": {
            "labels": [
                format_local(row.recorded_at, timezone_name) for row in oldest_first
            ],
            "pence": [row.price_pence for row in oldest_first],
        },
    }
    template = (
        "partials/price_history.html" if _htmx(request) else "ingredients/history.html"
    )
    return templates.TemplateResponse(request, template, context)


def _save_ingredient(
    request: Request,
    session: Session,
    *,
    ingredient: object,
    name: str,
    canonical_unit_id: str,
    notes: str,
    confirm_duplicate: bool,
    embed: bool,
    line: str = "",
) -> Response:
    from app.models import Ingredient

    current = ingredient if isinstance(ingredient, Ingredient) else None
    unit, unit_errors = _unit_from_form(session, canonical_unit_id)
    errors = collect_ingredient_errors(name=name, notes=notes, unit=unit)
    errors.update(unit_errors)
    values = {
        "name": name,
        "canonical_unit_id": canonical_unit_id,
        "notes": notes,
    }
    action = "/ingredients" if current is None else f"/ingredients/{current.id}"
    title = "New ingredient" if current is None else f"Edit {current.name}"
    if errors or unit is None:
        return _ingredient_page(
            request,
            session,
            title=title,
            action=action,
            values=values,
            errors=errors,
            embed=embed,
            line=line,
            unit_locked=current is not None and _unit_locked(session, current.id),
            locked_unit=None if current is None else current.canonical_unit,
        )
    try:
        if current is None:
            result = create_ingredient(
                session,
                name=name,
                canonical_unit=unit,
                notes=notes,
                allow_duplicate=confirm_duplicate,
            )
        else:
            result = update_ingredient(
                session,
                current,
                name=name,
                canonical_unit=unit,
                notes=notes,
                allow_duplicate=confirm_duplicate,
            )
    except DuplicateIngredient as exc:
        return _ingredient_page(
            request,
            session,
            title=title,
            action=action,
            values=values,
            errors={},
            duplicate_warning=exc.warning,
            embed=embed,
            line=line,
            unit_locked=current is not None and _unit_locked(session, current.id),
            locked_unit=None if current is None else current.canonical_unit,
        )
    except FieldValidationError as exc:
        return _ingredient_page(
            request,
            session,
            title=title,
            action=action,
            values=values,
            errors={exc.field: str(exc)},
            embed=embed,
            line=line,
            unit_locked=current is not None and _unit_locked(session, current.id),
            locked_unit=None if current is None else current.canonical_unit,
        )
    if embed and line.strip().isdigit():
        from app.services.meals import line_form_for_ingredient, unit_catalog

        return templates.TemplateResponse(
            request,
            "partials/recipe_line_created.html",
            {
                "line": line_form_for_ingredient(
                    result.ingredient, int(line), unit_catalog(session)
                )
            },
        )
    if embed:
        return templates.TemplateResponse(
            request,
            "partials/ingredient_created.html",
            {"ingredient": result.ingredient},
        )
    return RedirectResponse(f"/ingredients/{result.ingredient.id}", status_code=303)


def _list_context(session: Session, *, query: str, status: str) -> dict[str, object]:
    return {
        "active": "ingredients",
        "items": list_ingredients(session, query=query, status=status),
        "query": query,
        "status": status,
    }


def _ingredient_page(
    request: Request,
    session: Session,
    *,
    title: str,
    action: str,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    duplicate_warning: str | None = None,
    embed: bool = False,
    line: str = "",
    unit_locked: bool = False,
    locked_unit: Unit | None = None,
) -> Response:
    return _ingredient_form(
        request,
        session,
        action=action,
        embed=embed,
        values=values or _blank_ingredient(),
        errors=errors or {},
        duplicate_warning=duplicate_warning,
        title=title,
        line=line,
        unit_locked=unit_locked,
        locked_unit=locked_unit,
    )


def _ingredient_form(
    request: Request,
    session: Session,
    *,
    action: str,
    embed: bool,
    values: dict[str, str],
    errors: dict[str, str],
    duplicate_warning: str | None = None,
    title: str = "New ingredient",
    line: str = "",
    unit_locked: bool = False,
    locked_unit: Unit | None = None,
) -> Response:
    context = {
        "active": "ingredients",
        "title": title,
        "action": action,
        "embed": embed,
        "line": line,
        "values": values,
        "errors": errors,
        "duplicate_warning": duplicate_warning,
        "unit_groups": units_by_family(session),
        "unit_locked": unit_locked,
        "locked_unit": locked_unit,
    }
    template = "partials/ingredient_form.html" if embed else "ingredients/form.html"
    return templates.TemplateResponse(request, template, context)


def _option_page(
    request: Request,
    session: Session,
    *,
    ingredient: object,
    title: str,
    action: str,
    values: dict[str, str],
    errors: dict[str, str],
) -> Response:
    from app.models import Ingredient

    current = ingredient if isinstance(ingredient, Ingredient) else None
    if current is None:
        raise HTTPException(status_code=404)
    selected = int(values["shop_id"]) if values.get("shop_id", "").isdigit() else None
    return templates.TemplateResponse(
        request,
        "ingredients/option_form.html",
        {
            "active": "ingredients",
            "title": title,
            "action": action,
            "ingredient": current,
            "values": values,
            "errors": errors,
            "shops": shop_choices(session, selected_id=selected),
        },
    )


def _parse_option(
    session: Session,
    *,
    shop_id: str,
    pack_quantity: str,
    pack_label: str,
    price: str,
    unit_symbol: str,
) -> tuple[dict[str, object] | None, dict[str, str]]:
    errors: dict[str, str] = {}
    shop: Shop | None = None
    if not shop_id.strip():
        errors["shop_id"] = "Choose a shop, or add a new one."
    else:
        try:
            shop = session.get(Shop, int(shop_id))
        except ValueError:
            shop = None
        if shop is None:
            errors["shop_id"] = "Choose a shop from the list."
    try:
        quantity = parse_pack_quantity(pack_quantity, unit_symbol=unit_symbol)
    except InvalidQuantityError as exc:
        errors["pack_quantity"] = str(exc)
        quantity = None
    label = pack_label.strip()
    if not label:
        errors["pack_label"] = "Describe the pack, such as 1kg bag or 6 pack."
    elif len(label) > 200:
        errors["pack_label"] = "Use a pack label of 200 characters or fewer."
    try:
        price_pence = parse_gbp_to_pence(price)
    except InvalidPriceError as exc:
        errors["price"] = str(exc)
        price_pence = None
    if errors or shop is None or quantity is None or price_pence is None:
        return None, errors
    return {
        "shop": shop,
        "pack_quantity": quantity,
        "pack_label": label,
        "price_pence": price_pence,
    }, {}


def _unit_from_form(
    session: Session, raw_id: str
) -> tuple[Unit | None, dict[str, str]]:
    if not raw_id.strip():
        return None, {"canonical_unit_id": "Choose a unit, such as g or slice."}
    try:
        unit = session.get(Unit, int(raw_id))
    except ValueError:
        unit = None
    if unit is None:
        return None, {"canonical_unit_id": "Choose a unit from the list."}
    return unit, {}


def _require_ingredient(session: Session, ingredient_id: int) -> object:
    ingredient = get_ingredient(session, ingredient_id)
    if ingredient is None:
        raise HTTPException(status_code=404)
    return ingredient


def _require_option(ingredient: object, option_id: int) -> PurchaseOption:
    from app.models import Ingredient

    if not isinstance(ingredient, Ingredient):
        raise HTTPException(status_code=404)
    for option in ingredient.purchase_options:
        if option.id == option_id:
            return option
    raise HTTPException(status_code=404)


def _unit_locked(session: Session, ingredient_id: int) -> bool:
    from app.services.ingredients import ingredient_in_use

    return ingredient_in_use(session, ingredient_id)


def _blank_ingredient() -> dict[str, str]:
    return {"name": "", "canonical_unit_id": "", "notes": ""}


def _ingredient_values(ingredient: object) -> dict[str, str]:
    from app.models import Ingredient

    if not isinstance(ingredient, Ingredient):
        return _blank_ingredient()
    return {
        "name": ingredient.name,
        "canonical_unit_id": str(ingredient.canonical_unit_id),
        "notes": ingredient.notes or "",
    }


def _blank_option() -> dict[str, str]:
    return {"shop_id": "", "pack_quantity": "", "pack_label": "", "price": ""}


def _posted_option(
    shop_id: str, pack_quantity: str, pack_label: str, price: str
) -> dict[str, str]:
    return {
        "shop_id": shop_id,
        "pack_quantity": pack_quantity,
        "pack_label": pack_label,
        "price": price,
    }


def _option_values(option: PurchaseOption) -> dict[str, str]:
    return {
        "shop_id": str(option.shop_id),
        "pack_quantity": format_quantity_input(option.pack_quantity),
        "pack_label": option.pack_label,
        "price": format_gbp_input(option.price_pence),
    }


def _htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
