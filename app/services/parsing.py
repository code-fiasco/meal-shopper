"""Parse form text into decimals and integer pence."""

from decimal import Decimal, InvalidOperation

from app.services.units import InvalidQuantityError


class InvalidPriceError(ValueError):
    """Raised when a pound amount cannot be stored as integer pence."""


class FieldValidationError(ValueError):
    """A single field failed validation."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def parse_gbp_to_pence(raw: str) -> int:
    """Convert a pound amount such as '1.79' or '£1.79' into integer pence."""
    text = raw.strip().replace(" ", "")
    if text.startswith("£"):
        text = text[1:]
    if not text:
        raise InvalidPriceError("Enter a price in pounds, such as 1.79.")
    if "," in text:
        raise InvalidPriceError("Use a decimal point, such as 1.79.")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise InvalidPriceError("Enter a price in pounds, such as 1.79.") from None
    if not amount.is_finite():
        raise InvalidPriceError("Enter a price in pounds, such as 1.79.")
    if amount < 0:
        raise InvalidPriceError(
            "Price cannot be negative. Enter 0 or a positive amount such as 1.79."
        )
    if amount != amount.quantize(Decimal("0.01")):
        raise InvalidPriceError("Use at most two decimal places, such as 1.79.")
    return int(amount * Decimal(100))


def parse_recipe_quantity(raw: str, *, unit_symbol: str) -> Decimal:
    """Parse a recipe amount. Zero is allowed. Negative amounts are rejected."""
    text = raw.strip().replace(" ", "")
    if not text:
        raise InvalidQuantityError(f"Enter a quantity in {unit_symbol}.")
    if "," in text:
        raise InvalidQuantityError(
            f"Enter the quantity in {unit_symbol}, such as 2 or 0.5."
        )
    try:
        quantity = Decimal(text)
    except InvalidOperation:
        raise InvalidQuantityError(
            f"Enter the quantity in {unit_symbol}, such as 2 or 0.5."
        ) from None
    if not quantity.is_finite() or quantity < 0:
        raise InvalidQuantityError(f"Quantity in {unit_symbol} cannot be negative.")
    return quantity


def parse_pack_quantity(raw: str, *, unit_symbol: str) -> Decimal:
    """Parse a pack size. Zero and negative amounts are rejected."""
    text = raw.strip().replace(" ", "")
    if not text:
        raise InvalidQuantityError(f"Enter the pack quantity in {unit_symbol}.")
    if "," in text:
        raise InvalidQuantityError(
            f"Enter the pack quantity in {unit_symbol}, such as 500 or 1.5."
        )
    try:
        quantity = Decimal(text)
    except InvalidOperation:
        raise InvalidQuantityError(
            f"Enter the pack quantity in {unit_symbol}, such as 500 or 1.5."
        ) from None
    if not quantity.is_finite() or quantity < 0:
        raise InvalidQuantityError(
            f"Pack quantity in {unit_symbol} cannot be negative."
        )
    if quantity == 0:
        raise InvalidQuantityError(
            f"Enter how much is in the pack, in {unit_symbol}. Zero is not a pack."
        )
    return quantity
