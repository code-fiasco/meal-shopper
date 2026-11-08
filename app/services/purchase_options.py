"""Purchase options and append-only price history."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, PurchaseOption, PurchasePriceHistory, Shop
from app.services.units import InvalidQuantityError


def create_purchase_option(
    session: Session,
    *,
    ingredient: Ingredient,
    shop: Shop,
    pack_quantity: Decimal,
    pack_label: str,
    price_pence: int,
) -> PurchaseOption:
    """Create a pack and record its opening price."""
    quantity = _require_pack_quantity(pack_quantity)
    price = _require_price(price_pence)
    label = _require_label(pack_label)
    option = PurchaseOption(
        ingredient=ingredient,
        shop=shop,
        pack_quantity=quantity,
        pack_label=label,
        price_pence=price,
        is_active=True,
    )
    session.add(option)
    session.flush()
    _record_history(session, option)
    return option


def change_purchase_option(
    session: Session,
    option: PurchaseOption,
    *,
    price_pence: int | None = None,
    pack_quantity: Decimal | None = None,
    pack_label: str | None = None,
    is_active: bool | None = None,
    shop: Shop | None = None,
) -> PurchaseOption:
    """Update a pack. Price and pack-size changes append a history row."""
    price_changed = False
    pack_changed = False
    if price_pence is not None:
        price = _require_price(price_pence)
        price_changed = price != option.price_pence
        option.price_pence = price
    if pack_quantity is not None:
        quantity = _require_pack_quantity(pack_quantity)
        pack_changed = quantity != option.pack_quantity
        option.pack_quantity = quantity
    if pack_label is not None:
        option.pack_label = _require_label(pack_label)
    if is_active is not None:
        option.is_active = is_active
    if shop is not None:
        option.shop = shop
    session.flush()
    if price_changed or pack_changed:
        _record_history(session, option)
    return option


def list_price_history(
    session: Session, option: PurchaseOption
) -> list[PurchasePriceHistory]:
    """Return snapshots newest first. Rows are never updated."""
    return list(
        session.scalars(
            select(PurchasePriceHistory)
            .where(PurchasePriceHistory.purchase_option_id == option.id)
            .order_by(
                PurchasePriceHistory.recorded_at.desc(),
                PurchasePriceHistory.id.desc(),
            )
        )
    )


def _record_history(session: Session, option: PurchaseOption) -> None:
    session.add(
        PurchasePriceHistory(
            purchase_option=option,
            price_pence=option.price_pence,
            pack_quantity=option.pack_quantity,
        )
    )
    session.flush()


def _require_pack_quantity(quantity: Decimal) -> Decimal:
    if isinstance(quantity, float) or not isinstance(quantity, Decimal):
        raise InvalidQuantityError("Pack quantity must be Decimal, not float.")
    if not quantity.is_finite() or quantity <= 0:
        raise InvalidQuantityError("Pack quantity must be greater than zero.")
    return quantity


def _require_price(price_pence: int) -> int:
    if isinstance(price_pence, bool) or not isinstance(price_pence, int):
        raise TypeError("Price must be integer pence.")
    if price_pence < 0:
        raise InvalidQuantityError("Price cannot be negative.")
    return price_pence


def _require_label(pack_label: str) -> str:
    label = pack_label.strip()
    if not label:
        raise ValueError("Pack label is required.")
    return label
