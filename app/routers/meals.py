"""Meal list, editor, and recipe costing pages."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Ingredient, Meal
from app.services.ingredients import list_ingredients
from app.services.meals import (
    LineForm,
    RawLine,
    blank_line,
    cost_meal,
    duplicate_meal,
    get_meal,
    historical_planner_entries,
    line_form_for_ingredient,
    line_form_from_raw,
    line_form_from_stored,
    list_meals,
    meal_field_errors,
    prepare_lines,
    save_meal,
    set_meal_active,
    unit_catalog,
)
from app.services.parsing import FieldValidationError
from app.templating import templates

router = APIRouter()


@router.get("/meals")
def meal_list(
    request: Request,
    q: str = "",
    status: str = "active",
    session: Session = Depends(get_db),
) -> Response:
    if status not in {"active", "archived", "all"}:
        status = "active"
    context = {
        "active": "meals",
        "items": list_meals(session, query=q, status=status),
        "query": q,
        "status": status,
    }
    template = "partials/meal_results.html" if _htmx(request) else "meals/list.html"
    return templates.TemplateResponse(request, template, context)


@router.get("/meals/new")
def new_meal(request: Request) -> Response:
    return _editor(
        request,
        title="New meal",
        action="/meals",
        values=_blank_meal(),
        lines=[blank_line(0)],
        errors={},
        next_index=1,
    )


@router.post("/meals")
def post_meal(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    instructions: str = Form(""),
    ingredient_id: list[str] = Form(default=[]),
    entered_quantity: list[str] = Form(default=[]),
    entered_unit_id: list[str] = Form(default=[]),
    line_notes: list[str] = Form(default=[]),
    session: Session = Depends(get_db),
) -> Response:
    return _save(
        request,
        session,
        meal=None,
        name=name,
        description=description,
        instructions=instructions,
        raw_lines=_raw_lines(
            ingredient_id, entered_quantity, entered_unit_id, line_notes
        ),
    )


@router.get("/meals/ingredient-search")
def ingredient_search(
    request: Request,
    index: int = 0,
    q: str = "",
    session: Session = Depends(get_db),
) -> Response:
    return templates.TemplateResponse(
        request,
        "partials/ingredient_search_results.html",
        {
            "index": index,
            "items": list_ingredients(session, query=q, status="active"),
        },
    )


@router.get("/meals/ingredients/{ingredient_id}/picker")
def ingredient_picker(
    request: Request,
    ingredient_id: int,
    index: int = 0,
    session: Session = Depends(get_db),
) -> Response:
    ingredient = session.scalar(
        select(Ingredient)
        .where(Ingredient.id == ingredient_id)
        .options(
            selectinload(Ingredient.canonical_unit),
            selectinload(Ingredient.conversions),
        )
    )
    if ingredient is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/recipe_line_picker.html",
        {"line": line_form_for_ingredient(ingredient, index, unit_catalog(session))},
    )


@router.get("/meals/lines/new")
def new_line(request: Request, index: int = 0) -> Response:
    return templates.TemplateResponse(
        request,
        "partials/recipe_line_append.html",
        {"line": blank_line(index), "next_index": index + 1},
    )


@router.get("/meals/blank")
def blank_fragment() -> Response:
    """Empty fragment used to remove a line or close the ingredient panel."""
    return Response(content="", media_type="text/html")


@router.get("/meals/{meal_id}")
def meal_detail(
    request: Request, meal_id: int, session: Session = Depends(get_db)
) -> Response:
    meal = _require_meal(session, meal_id)
    return templates.TemplateResponse(
        request,
        "meals/detail.html",
        {
            "active": "meals",
            "meal": meal,
            "cost": cost_meal(meal),
            "planner_entry_ids": historical_planner_entries(session, meal.id),
        },
    )


@router.get("/meals/{meal_id}/edit")
def edit_meal(
    request: Request, meal_id: int, session: Session = Depends(get_db)
) -> Response:
    meal = _require_meal(session, meal_id)
    catalog = unit_catalog(session)
    lines = [
        line_form_from_stored(line, index, catalog)
        for index, line in enumerate(meal.lines)
    ] or [blank_line(0)]
    return _editor(
        request,
        title=f"Edit {meal.name}",
        action=f"/meals/{meal.id}",
        values=_meal_values(meal),
        lines=lines,
        errors={},
        next_index=len(lines),
    )


@router.post("/meals/{meal_id}")
def post_edit_meal(
    request: Request,
    meal_id: int,
    name: str = Form(""),
    description: str = Form(""),
    instructions: str = Form(""),
    ingredient_id: list[str] = Form(default=[]),
    entered_quantity: list[str] = Form(default=[]),
    entered_unit_id: list[str] = Form(default=[]),
    line_notes: list[str] = Form(default=[]),
    session: Session = Depends(get_db),
) -> Response:
    meal = _require_meal(session, meal_id)
    return _save(
        request,
        session,
        meal=meal,
        name=name,
        description=description,
        instructions=instructions,
        raw_lines=_raw_lines(
            ingredient_id, entered_quantity, entered_unit_id, line_notes
        ),
    )


@router.post("/meals/{meal_id}/duplicate")
def post_duplicate(
    meal_id: int, session: Session = Depends(get_db)
) -> RedirectResponse:
    meal = _require_meal(session, meal_id)
    copy = duplicate_meal(session, meal)
    return RedirectResponse(f"/meals/{copy.id}", status_code=303)


@router.post("/meals/{meal_id}/archive")
def archive_meal(meal_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    meal = _require_meal(session, meal_id)
    set_meal_active(session, meal, active=False)
    return RedirectResponse(f"/meals/{meal.id}", status_code=303)


@router.post("/meals/{meal_id}/restore")
def restore_meal(meal_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    meal = _require_meal(session, meal_id)
    set_meal_active(session, meal, active=True)
    return RedirectResponse(f"/meals/{meal.id}", status_code=303)


def _save(
    request: Request,
    session: Session,
    *,
    meal: Meal | None,
    name: str,
    description: str,
    instructions: str,
    raw_lines: list[RawLine],
) -> Response:
    errors = meal_field_errors(
        name=name, description=description, instructions=instructions
    )
    prepared, line_errors = prepare_lines(session, raw_lines)
    if errors or line_errors:
        return _repaint(
            request,
            session,
            meal=meal,
            name=name,
            description=description,
            instructions=instructions,
            raw_lines=raw_lines,
            errors=errors,
            line_errors=line_errors,
        )
    try:
        saved = save_meal(
            session,
            meal,
            name=name,
            description=description,
            instructions=instructions,
            lines=prepared,
        )
    except FieldValidationError as exc:
        return _repaint(
            request,
            session,
            meal=meal,
            name=name,
            description=description,
            instructions=instructions,
            raw_lines=raw_lines,
            errors={exc.field: str(exc)},
            line_errors={},
        )
    return RedirectResponse(f"/meals/{saved.id}", status_code=303)


def _repaint(
    request: Request,
    session: Session,
    *,
    meal: Meal | None,
    name: str,
    description: str,
    instructions: str,
    raw_lines: list[RawLine],
    errors: dict[str, str],
    line_errors: dict[int, dict[str, str]],
) -> Response:
    catalog = unit_catalog(session)
    lines = [
        line_form_from_raw(session, raw, index, catalog, line_errors.get(index, {}))
        for index, raw in enumerate(raw_lines)
    ] or [blank_line(0)]
    title = "New meal" if meal is None else f"Edit {meal.name}"
    action = "/meals" if meal is None else f"/meals/{meal.id}"
    return _editor(
        request,
        title=title,
        action=action,
        values={"name": name, "description": description, "instructions": instructions},
        lines=lines,
        errors=errors,
        next_index=len(lines),
    )


def _editor(
    request: Request,
    *,
    title: str,
    action: str,
    values: dict[str, str],
    lines: list[LineForm],
    errors: dict[str, str],
    next_index: int,
) -> Response:
    return templates.TemplateResponse(
        request,
        "meals/form.html",
        {
            "active": "meals",
            "title": title,
            "action": action,
            "values": values,
            "lines": lines,
            "errors": errors,
            "next_index": next_index,
        },
    )


def _require_meal(session: Session, meal_id: int) -> Meal:
    meal = get_meal(session, meal_id)
    if meal is None:
        raise HTTPException(status_code=404)
    return meal


def _raw_lines(
    ingredient_ids: list[str],
    quantities: list[str],
    unit_ids: list[str],
    notes: list[str],
) -> list[RawLine]:
    length = max(len(ingredient_ids), len(quantities), len(unit_ids), len(notes), 0)

    def at(values: list[str], index: int) -> str:
        return values[index] if index < len(values) else ""

    return [
        RawLine(
            ingredient_id=at(ingredient_ids, index),
            entered_quantity=at(quantities, index),
            entered_unit_id=at(unit_ids, index),
            notes=at(notes, index),
        )
        for index in range(length)
    ]


def _blank_meal() -> dict[str, str]:
    return {"name": "", "description": "", "instructions": ""}


def _meal_values(meal: Meal) -> dict[str, str]:
    return {
        "name": meal.name,
        "description": meal.description or "",
        "instructions": meal.instructions or "",
    }


def _htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
