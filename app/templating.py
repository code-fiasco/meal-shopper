"""Jinja2 environment for server-rendered pages."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.formatting import (
    format_gbp,
    format_gbp_exact,
    format_gbp_input,
    format_local,
    format_quantity,
    format_quantity_input,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["gbp"] = format_gbp
templates.env.filters["gbp_exact"] = format_gbp_exact
templates.env.filters["gbp_input"] = format_gbp_input
templates.env.filters["qty"] = format_quantity
templates.env.filters["qty_input"] = format_quantity_input
templates.env.filters["local_dt"] = format_local
