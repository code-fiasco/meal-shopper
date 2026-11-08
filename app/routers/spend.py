"""Spending page. Totals come from the spend service."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.services.planner import local_today
from app.services.spend import spend_report
from app.templating import templates

router = APIRouter()

WEEK_CHOICES = (4, 8, 12, 26)


@router.get("/spending")
def spending_page(
    request: Request,
    weeks: int = 8,
    date_value: Annotated[str, Query(alias="date")] = "",
    session: Session = Depends(get_db),
) -> Response:
    today = local_today(get_settings().app_timezone)
    end, date_error = _anchor(date_value, today)
    selected = weeks if weeks in WEEK_CHOICES else 8
    report = spend_report(session, end=end, week_count=selected)
    return templates.TemplateResponse(
        request,
        "spending.html",
        {
            "active": "spending",
            "report": report,
            "chart": report.chart_payload(),
            "week_choices": WEEK_CHOICES,
            "selected_weeks": selected,
            "selected_date": end,
            "date_error": date_error,
        },
    )


def _anchor(raw: str, today: date) -> tuple[date, str | None]:
    if not raw:
        return today, None
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return today, "Choose a valid date."
