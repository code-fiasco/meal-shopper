"""Weekly planner pages. Saving a slot swaps that slot, not the whole page."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.services.parsing import FieldValidationError
from app.services.plan_pdf import render_meal_plan_pdf
from app.services.planner import (
    DINNER,
    LUNCH,
    WeekView,
    assign_blank,
    assign_meal,
    assign_takeaway,
    build_week,
    find_slot,
    local_today,
    open_editor,
    search_meals,
    shift_week,
    week_start_for,
)
from app.templating import templates

router = APIRouter()
_OPEN_MODES = {"pick-meal", "pick-takeaway"}


@router.get("/")
@router.get("/planner")
def planner_page(
    request: Request,
    date_value: Annotated[str, Query(alias="date")] = "",
    edit: str = "",
    slot: str = "",
    mode: str = "",
    session: Session = Depends(get_db),
) -> Response:
    today = _today()
    anchor, date_error = _anchor(date_value, today)
    week = build_week(session, anchor, today=today)
    _apply_query_editor(session, week, edit, slot, mode)
    return _page(request, week, date_error)


@router.get("/planner/pdf")
def planner_pdf(
    date_value: Annotated[str, Query(alias="date")] = "",
    session: Session = Depends(get_db),
) -> Response:
    today = _today()
    anchor, _error = _anchor(date_value, today)
    week = build_week(session, anchor, today=today)
    following = build_week(session, shift_week(week.start, 1), today=today)
    filename = f"meal-plan-{week.start.isoformat()}.pdf"
    return Response(
        content=render_meal_plan_pdf(week, following),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/planner/meal-search")
def meal_search(
    request: Request,
    q: str = "",
    date_value: Annotated[str, Query(alias="date")] = "",
    slot: str = "",
    session: Session = Depends(get_db),
) -> Response:
    plan_date = _parse_date(date_value)
    if plan_date is None or slot not in {LUNCH, DINNER}:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/planner_meal_results.html",
        {
            "meals": search_meals(session, q),
            "plan_date": plan_date,
            "slot_name": slot,
            "dom_id": f"slot-{plan_date.isoformat()}-{slot}",
            "query": q,
        },
    )


@router.post("/planner/slots")
def post_slot(
    request: Request,
    date_value: str = Form(..., alias="date"),
    slot: str = Form(...),
    intent: str = Form(...),
    meal_id: str = Form(""),
    takeaway_price: str = Form(""),
    takeaway_description: str = Form(""),
    session: Session = Depends(get_db),
) -> Response:
    plan_date = _parse_date(date_value)
    if plan_date is None or slot not in {LUNCH, DINNER}:
        raise HTTPException(status_code=400)
    known = {
        "show",
        "blank",
        "pick-meal",
        "pick-takeaway",
        "save-meal",
        "save-takeaway",
    }
    if intent not in known:
        raise HTTPException(status_code=400)
    return _dispatch(
        request,
        session,
        plan_date=plan_date,
        slot=slot,
        intent=intent,
        meal_id=meal_id,
        takeaway_price=takeaway_price,
        takeaway_description=takeaway_description,
    )


def _dispatch(
    request: Request,
    session: Session,
    *,
    plan_date: date,
    slot: str,
    intent: str,
    meal_id: str,
    takeaway_price: str,
    takeaway_description: str,
) -> Response:
    if intent == "show":
        return _saved(request, session, plan_date, slot)
    if intent == "pick-meal":
        return _opened(request, session, plan_date, slot, "pick-meal")
    if intent == "pick-takeaway":
        return _opened(
            request,
            session,
            plan_date,
            slot,
            "pick-takeaway",
            draft_price=takeaway_price,
            draft_description=takeaway_description,
        )
    try:
        _save(
            session,
            plan_date=plan_date,
            slot=slot,
            intent=intent,
            meal_id=meal_id,
            takeaway_price=takeaway_price,
            takeaway_description=takeaway_description,
        )
    except FieldValidationError as exc:
        mode = "pick-takeaway" if intent == "save-takeaway" else "pick-meal"
        return _opened(
            request,
            session,
            plan_date,
            slot,
            mode,
            errors={exc.field: str(exc)},
            draft_price=takeaway_price,
            draft_description=takeaway_description,
            keep_page=True,
        )
    return _saved(request, session, plan_date, slot)


def _save(
    session: Session,
    *,
    plan_date: date,
    slot: str,
    intent: str,
    meal_id: str,
    takeaway_price: str,
    takeaway_description: str,
) -> None:
    if intent == "blank":
        assign_blank(session, plan_date=plan_date, slot=slot)
        return
    if intent == "save-meal":
        assign_meal(
            session,
            plan_date=plan_date,
            slot=slot,
            meal_id=_require_meal_id(meal_id),
        )
        return
    if intent == "save-takeaway":
        assign_takeaway(
            session,
            plan_date=plan_date,
            slot=slot,
            price=takeaway_price,
            description=takeaway_description,
        )
        return
    raise FieldValidationError("intent", "Choose blank, a meal, or takeaway.")


def _saved(request: Request, session: Session, plan_date: date, slot: str) -> Response:
    week = build_week(session, plan_date, today=_today())
    if _htmx(request):
        return _slot_fragment(request, week, plan_date, slot)
    monday = week_start_for(plan_date)
    return RedirectResponse(f"/planner?date={monday.isoformat()}", status_code=303)


def _opened(
    request: Request,
    session: Session,
    plan_date: date,
    slot: str,
    mode: str,
    *,
    errors: dict[str, str] | None = None,
    draft_price: str = "",
    draft_description: str = "",
    keep_page: bool = False,
) -> Response:
    week = build_week(session, plan_date, today=_today())
    meals = search_meals(session, "") if mode == "pick-meal" else []
    open_editor(
        week,
        plan_date=plan_date,
        slot=slot,
        mode=mode,
        errors=errors,
        draft_price=draft_price,
        draft_description=draft_description,
        meals=meals,
    )
    if _htmx(request):
        return _slot_fragment(request, week, plan_date, slot)
    if keep_page:
        return _page(request, week, None)
    monday = week.start.isoformat()
    target = plan_date.isoformat()
    location = f"/planner?date={monday}&edit={target}&slot={slot}&mode={mode}"
    return RedirectResponse(location, status_code=303)


def _slot_fragment(
    request: Request, week: WeekView, plan_date: date, slot: str
) -> Response:
    found = find_slot(week, plan_date, slot)
    if found is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/planner_slot_update.html",
        {"slot": found, "costs": week.costs},
    )


def _page(request: Request, week: WeekView, date_error: str | None) -> Response:
    return templates.TemplateResponse(
        request,
        "planner/week.html",
        {"active": "planner", "week": week, "date_error": date_error},
    )


def _apply_query_editor(
    session: Session, week: WeekView, edit: str, slot: str, mode: str
) -> None:
    if mode not in _OPEN_MODES or slot not in {LUNCH, DINNER}:
        return
    plan_date = _parse_date(edit)
    if plan_date is None:
        return
    meals = search_meals(session, "") if mode == "pick-meal" else []
    open_editor(week, plan_date=plan_date, slot=slot, mode=mode, meals=meals)


def _anchor(raw: str, today: date) -> tuple[date, str | None]:
    if not raw:
        return today, None
    parsed = _parse_date(raw)
    if parsed is None:
        return today, "Choose a valid date."
    return parsed, None


def _parse_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _require_meal_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise FieldValidationError("meal_id", "Choose a meal.") from None


def _today() -> date:
    return local_today(get_settings().app_timezone)


def _htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
