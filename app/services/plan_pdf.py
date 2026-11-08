"""A4 landscape PDF of the selected week and the week after it."""

from pathlib import Path

from fpdf import FPDF

from app.formatting import format_sheet_date, format_week_commencing
from app.services.planner import BLANK, MEAL, TAKEAWAY, SlotView, WeekView

_PAGE_W = 297.0
_PAGE_H = 210.0
_MARGIN = 14.0
_BANNER_H = 12.0
_BANNER_GAP = 4.0
_FRAME_PAD_X = 5.0
_FRAME_PAD_TOP = 5.0
_FRAME_PAD_BOTTOM = 6.0
_WEEK_GAP = 12.0
_DATE_H = 5.5
_WEEKDAY_H = 8.0
_LABEL_W = 26.0
_INK = (17, 17, 17)
_BLUE = (214, 228, 245)
_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def render_meal_plan_pdf(week: WeekView, following: WeekView) -> bytes:
    """Draw both weeks onto one landscape A4 page."""
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False, margin=0)
    pdf.set_margins(0, 0, 0)
    pdf.add_font("DejaVu", "", str(_font("DejaVuSans.ttf")))
    pdf.add_font("DejaVu", "B", str(_font("DejaVuSans-Bold.ttf")))
    pdf.add_page()
    pdf.set_title("Meal Planner")

    _draw_banner(pdf, format_week_commencing(week.start))
    frame = _draw_frame(pdf)
    meal_h = _meal_row_height(frame[3])
    inner_x = frame[0] + _FRAME_PAD_X
    inner_w = frame[2] - (2 * _FRAME_PAD_X)
    first_y = frame[1] + _FRAME_PAD_TOP
    _draw_week(pdf, week, inner_x, first_y, inner_w, meal_h)
    second_y = first_y + _DATE_H + _WEEKDAY_H + (2 * meal_h) + _WEEK_GAP
    _draw_week(pdf, following, inner_x, second_y, inner_w, meal_h)
    return bytes(pdf.output())


def _font(filename: str) -> Path:
    path = _FONT_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"DejaVu font is not installed at {path}.")
    return path


def _draw_banner(pdf: FPDF, commencing: str) -> None:
    x, y = _MARGIN, _MARGIN
    width = _PAGE_W - (2 * _MARGIN)
    pdf.set_draw_color(*_INK)
    pdf.set_line_width(0.6)
    pdf.rect(x, y, width, _BANNER_H)
    pdf.set_text_color(*_INK)
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_xy(x, y)
    pdf.cell(width, _BANNER_H, "Meal Planner", align="C")
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_xy(x, y)
    pdf.cell(width - 4, _BANNER_H, commencing, align="R")


def _draw_frame(pdf: FPDF) -> tuple[float, float, float, float]:
    x = _MARGIN
    y = _MARGIN + _BANNER_H + _BANNER_GAP
    width = _PAGE_W - (2 * _MARGIN)
    height = _PAGE_H - _MARGIN - y
    pdf.set_draw_color(*_INK)
    pdf.set_line_width(0.6)
    pdf.rect(x, y, width, height)
    return x, y, width, height


def _meal_row_height(frame_height: float) -> float:
    inner = frame_height - _FRAME_PAD_TOP - _FRAME_PAD_BOTTOM
    grid = (inner - _WEEK_GAP) / 2
    return (grid - _DATE_H - _WEEKDAY_H) / 2


def _draw_week(
    pdf: FPDF,
    week: WeekView,
    x: float,
    y: float,
    width: float,
    meal_h: float,
) -> None:
    day_w = (width - _LABEL_W) / 7
    for index, day in enumerate(week.days):
        _draw_cell(
            pdf,
            x + _LABEL_W + (index * day_w),
            y,
            day_w,
            _DATE_H,
            format_sheet_date(day.plan_date),
            fill=None,
            bold=True,
            size=8,
        )
    weekday_y = y + _DATE_H
    _draw_cell(
        pdf, x, weekday_y, _LABEL_W, _WEEKDAY_H, "", fill=_BLUE, bold=True, size=9
    )
    for index, day in enumerate(week.days):
        _draw_cell(
            pdf,
            x + _LABEL_W + (index * day_w),
            weekday_y,
            day_w,
            _WEEKDAY_H,
            day.weekday,
            fill=_BLUE,
            bold=True,
            size=9,
        )
    for offset, label, slot_name in ((0, "Lunch", "lunch"), (1, "Dinner", "dinner")):
        row_y = weekday_y + _WEEKDAY_H + (offset * meal_h)
        _draw_cell(
            pdf, x, row_y, _LABEL_W, meal_h, label, fill=_BLUE, bold=True, size=10
        )
        for index, day in enumerate(week.days):
            slot = day.lunch if slot_name == "lunch" else day.dinner
            _draw_cell(
                pdf,
                x + _LABEL_W + (index * day_w),
                row_y,
                day_w,
                meal_h,
                _slot_text(slot),
                fill=None,
                bold=False,
                size=9,
            )


def _draw_cell(
    pdf: FPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    fill: tuple[int, int, int] | None,
    bold: bool,
    size: float,
) -> None:
    pdf.set_draw_color(*_INK)
    pdf.set_line_width(0.3)
    if fill is None:
        pdf.rect(x, y, w, h, style="D")
    else:
        pdf.set_fill_color(*fill)
        pdf.rect(x, y, w, h, style="DF")
    if not text:
        return
    pdf.set_text_color(*_INK)
    pdf.set_font("DejaVu", "B" if bold else "", size)
    pad = 1.0
    inner_w = w - (2 * pad)
    line_h = pdf.font_size * 1.15
    lines = pdf.multi_cell(
        inner_w,
        line_h,
        text,
        dry_run=True,
        output="LINES",
        align="CENTER",
    )
    if not isinstance(lines, list):
        lines = [text]
    fitted = lines[: max(1, int((h - 1) / line_h))]
    block_h = len(fitted) * line_h
    text_y = y + max(0.3, (h - block_h) / 2)
    for index, line in enumerate(fitted):
        pdf.set_xy(x + pad, text_y + (index * line_h))
        pdf.cell(inner_w, line_h, line, align="C")


def _slot_text(slot: SlotView) -> str:
    entry = slot.entry
    if entry is None or entry.entry_type == BLANK:
        return ""
    if entry.entry_type == TAKEAWAY:
        description = (entry.takeaway_description or "").strip()
        if description:
            return f"Takeaway: {description}"
        return "Takeaway"
    if entry.entry_type == MEAL:
        return entry.snapshot_meal_name or ""
    return ""
