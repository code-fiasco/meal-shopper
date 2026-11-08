"""Display formatting. Storage stays in pence and Decimal quantities."""

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

_POUND_DISPLAY = Decimal("0.000001")


def format_gbp_input(pence: int) -> str:
    """Pound amount for an input, without the currency symbol."""
    sign = "-" if pence < 0 else ""
    absolute = abs(pence)
    return f"{sign}{absolute // 100}.{absolute % 100:02d}"


def format_gbp(pence: int) -> str:
    """Format integer pence as pounds, for example 179 -> £1.79."""
    return format_gbp_exact(Decimal(pence))


def format_gbp_exact(pence: Decimal) -> str:
    """Format a precise pence amount. Trailing zeros stop at two decimal places."""
    if isinstance(pence, float) or not isinstance(pence, Decimal):
        raise TypeError("Money must be Decimal or int pence, not float.")
    negative = pence < 0
    pounds = (abs(pence) / Decimal(100)).quantize(
        _POUND_DISPLAY, rounding=ROUND_HALF_UP
    )
    text = format(pounds, "f")
    if "." not in text:
        text = f"{text}.00"
    else:
        whole, fraction = text.split(".", 1)
        if len(fraction) < 2:
            fraction = fraction.ljust(2, "0")
        else:
            while len(fraction) > 2 and fraction.endswith("0"):
                fraction = fraction[:-1]
        text = f"{whole}.{fraction}"
    sign = "-" if negative else ""
    return f"{sign}£{text}"


def format_quantity(quantity: Decimal, symbol: str) -> str:
    """Show a quantity with its unit, for example 200g or 2 eggs."""
    amount = format_quantity_input(quantity)
    if symbol.isalpha() and len(symbol) <= 2:
        return f"{amount}{symbol}"
    return f"{amount} {symbol}"


def format_quantity_input(quantity: Decimal) -> str:
    """Plain number for an input value, without trailing zeros."""
    if isinstance(quantity, float) or not isinstance(quantity, Decimal):
        raise TypeError("Quantity must be Decimal, not float.")
    return format(quantity.normalize(), "f")


_SHEET_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_sheet_date(day: date) -> str:
    """Compact print date, for example 09-Nov."""
    return f"{day.day:02d}-{_SHEET_MONTHS[day.month - 1]}"


def format_week_commencing(day: date) -> str:
    """UK week-commencing label, for example w/c 09/11/26."""
    return f"w/c {day.day:02d}/{day.month:02d}/{day.year % 100:02d}"


def format_local(value: datetime, timezone_name: str) -> str:
    """UK-style local time from a stored timestamp."""
    moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    local = moment.astimezone(ZoneInfo(timezone_name))
    return local.strftime("%d %b %Y, %H:%M")
