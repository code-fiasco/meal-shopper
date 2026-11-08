"""Shop list maintenance."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Shop
from app.services.ingredients import normalise_ingredient_name
from app.services.parsing import FieldValidationError


def shop_choices(session: Session, *, selected_id: int | None = None) -> list[Shop]:
    """Active shops, plus the current selection when it is archived."""
    shops = list_shops(session, include_archived=False)
    if selected_id is None or any(shop.id == selected_id for shop in shops):
        return shops
    selected = session.get(Shop, selected_id)
    if selected is None:
        return shops
    return sorted([*shops, selected], key=lambda shop: shop.name.lower())


def list_shops(session: Session, *, include_archived: bool = False) -> list[Shop]:
    """Return shops by name. Archived shops are hidden unless requested."""
    statement = select(Shop).order_by(Shop.name)
    if not include_archived:
        statement = statement.where(Shop.is_active.is_(True))
    return list(session.scalars(statement))


def create_shop(session: Session, *, name: str, notes: str | None = None) -> Shop:
    """Add a shop. A normalised name that already exists is rejected."""
    cleaned = _clean_name(name)
    existing = _find_by_name(session, cleaned)
    if existing is not None:
        raise FieldValidationError(
            "name",
            f"A shop named {existing.name} is already in the list. Choose it instead.",
        )
    shop = Shop(name=cleaned, notes=_clean_notes(notes), is_active=True)
    session.add(shop)
    session.flush()
    return shop


def rename_shop(
    session: Session, shop: Shop, *, name: str, notes: str | None = None
) -> Shop:
    """Rename a shop and replace its notes."""
    cleaned = _clean_name(name)
    existing = _find_by_name(session, cleaned, exclude_id=shop.id)
    if existing is not None:
        raise FieldValidationError(
            "name",
            f"A shop named {existing.name} is already in the list.",
        )
    shop.name = cleaned
    shop.notes = _clean_notes(notes)
    session.flush()
    return shop


def set_shop_active(session: Session, shop: Shop, *, active: bool) -> Shop:
    """Archive or restore a shop. Purchase options keep their shop."""
    shop.is_active = active
    session.flush()
    return shop


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise FieldValidationError("name", "Enter a shop name.")
    if len(cleaned) > 200:
        raise FieldValidationError(
            "name", "Use a shop name of 200 characters or fewer."
        )
    return cleaned


def _clean_notes(notes: str | None) -> str | None:
    if notes is None:
        return None
    cleaned = notes.strip()
    if len(cleaned) > 1000:
        raise FieldValidationError("notes", "Notes must be 1000 characters or fewer.")
    return cleaned or None


def _find_by_name(
    session: Session, name: str, *, exclude_id: int | None = None
) -> Shop | None:
    target = normalise_ingredient_name(name)
    for shop in session.scalars(select(Shop)):
        if exclude_id is not None and shop.id == exclude_id:
            continue
        if normalise_ingredient_name(shop.name) == target:
            return shop
    return None
