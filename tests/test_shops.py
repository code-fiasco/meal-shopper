"""Shop create, rename, and archive."""

import pytest
from sqlalchemy.orm import Session

from app.services.parsing import FieldValidationError
from app.services.shops import create_shop, list_shops, rename_shop, set_shop_active


def test_create_rename_and_reject_duplicate(session: Session) -> None:
    shop = create_shop(session, name="  Tesco  ")
    assert shop.name == "Tesco"
    renamed = rename_shop(session, shop, name="Tesco Extra", notes="big")
    assert renamed.name == "Tesco Extra"
    assert renamed.notes == "big"
    create_shop(session, name="Aldi")
    with pytest.raises(FieldValidationError, match="already in the list"):
        create_shop(session, name="aldi")


def test_archive_removes_shop_from_the_active_list(session: Session) -> None:
    shop = create_shop(session, name="Local")
    set_shop_active(session, shop, active=False)
    assert list_shops(session) == []
    archived = list_shops(session, include_archived=True)
    assert archived[0].is_active is False
