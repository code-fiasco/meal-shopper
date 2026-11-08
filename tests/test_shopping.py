"""Shopping-list generation, stock deduction, and regeneration."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PurchaseOption, Shop, ShoppingList, ShoppingListLine, Unit
from app.services.ingredients import create_ingredient
from app.services.meals import RawLine, prepare_lines, save_meal
from app.services.parsing import FieldValidationError
from app.services.planner import assign_blank, assign_meal, assign_takeaway, get_week
from app.services.purchase_options import change_purchase_option, create_purchase_option
from app.services.shopping import (
    add_manual_line,
    checklist_for,
    checklist_lines,
    choose_purchase_option,
    cover_requirement_with_stock,
    generate_shopping_list,
    kept_without_requirement,
    packs_to_buy,
    refresh_shopping_list,
    remove_generated_line,
    restore_removed_line,
    set_line_checked,
    set_line_price,
    set_pack_count_override,
    set_quantity_override,
    shopping_totals,
)
from app.services.stock import SET, adjust_stock, get_stock_map

MONDAY = date(2026, 11, 2)


def _unit(session: Session, symbol: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.symbol == symbol))
    assert unit is not None
    return unit


def _shop(session: Session, name: str) -> Shop:
    shop = Shop(name=name, is_active=True)
    session.add(shop)
    session.flush()
    return shop


def _meal(session: Session, name: str, lines: list[RawLine]):
    prepared, errors = prepare_lines(session, lines)
    assert errors == {}
    return save_meal(
        session,
        None,
        name=name,
        description=None,
        instructions=None,
        lines=prepared,
    )


def _plan(session: Session, slots: list[tuple[date, str, int]]):
    for plan_date, slot, meal_id in slots:
        assign_meal(session, plan_date=plan_date, slot=slot, meal_id=meal_id)
    week = get_week(session, MONDAY)
    assert week is not None
    return week


def _line(shopping_list: ShoppingList, name: str) -> ShoppingListLine:
    found = [line for line in shopping_list.lines if line.description == name]
    assert len(found) == 1
    return found[0]


def test_packs_round_up_to_whole_packs() -> None:
    assert packs_to_buy(Decimal("0"), Decimal("500")) == 0
    assert packs_to_buy(Decimal("500"), Decimal("500")) == 1
    assert packs_to_buy(Decimal("501"), Decimal("500")) == 2
    assert packs_to_buy(Decimal("600"), Decimal("500")) == 2


def test_spec_example_keeps_outlay_separate_from_consumption(
    session: Session,
) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    shop = _shop(session, "Butcher")
    create_purchase_option(
        session,
        ingredient=beef,
        shop=shop,
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    lunch = _meal(
        session,
        "Ragu",
        [RawLine(str(beef.id), "200", str(grams.id), "")],
    )
    dinner = _meal(
        session,
        "Chilli",
        [RawLine(str(beef.id), "500", str(grams.id), "")],
    )
    tuesday = MONDAY + timedelta(days=1)
    week = _plan(
        session,
        [(MONDAY, "lunch", lunch.id), (MONDAY, "dinner", dinner.id)],
    )
    assign_takeaway(
        session,
        plan_date=tuesday,
        slot="lunch",
        price="12.50",
        description="Pizza",
    )
    assign_blank(session, plan_date=tuesday, slot="dinner")
    adjust_stock(
        session,
        ingredient_id=beef.id,
        action=SET,
        quantity="100",
        unit_id=str(grams.id),
    )

    shopping_list = generate_shopping_list(session, week.id)
    generated = [line for line in shopping_list.lines if line.source == "generated"]
    assert len(generated) == 1
    line = generated[0]
    assert line.description == "Minced beef"
    assert line.unit_snapshot == "g"
    assert line.required_quantity == Decimal("700")
    assert line.stock_allocated == Decimal("100")
    assert line.net_quantity == Decimal("600")
    assert line.shop_name == "Butcher"
    assert line.pack_label == "500g pack"
    assert line.pack_quantity == Decimal("500")
    assert line.pack_price_pence == 350
    assert line.pack_count == 2
    assert line.estimated_price_pence == 700
    totals = shopping_totals(shopping_list)
    assert totals.outlay_pence == 700
    assert totals.consumption_pence == 490
    assert totals.outlay_pence != totals.consumption_pence
    assert totals.is_complete is True
    assert totals.missing_ingredients == ()
    assert get_stock_map(session)[beef.id] == Decimal("100")


def test_totals_keep_the_snapshotted_price_until_regeneration(
    session: Session,
) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    option = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "700", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    change_purchase_option(session, option, price_pence=999)
    assert shopping_totals(shopping_list).outlay_pence == 700
    refreshed = generate_shopping_list(session, week.id)
    assert refreshed.id == shopping_list.id
    assert shopping_totals(refreshed).outlay_pence == 1998
    assert _line(refreshed, "Minced beef").pack_price_pence == 999


def test_cheapest_active_pack_is_the_default(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    market = _shop(session, "Market")
    butcher = _shop(session, "Butcher")
    cheap = create_purchase_option(
        session,
        ingredient=beef,
        shop=market,
        pack_quantity=Decimal("1000"),
        pack_label="1kg tray",
        price_pence=400,
    )
    create_purchase_option(
        session,
        ingredient=beef,
        shop=butcher,
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "600", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    line = _line(shopping_list, "Minced beef")
    assert line.selected_purchase_option_id == cheap.id
    assert line.shop_name == "Market"
    assert line.pack_count == 1
    assert line.option_overridden is False
    assert shopping_totals(shopping_list).outlay_pence == 400


def test_equal_unit_price_uses_the_lowest_option_id(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    first = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Market"),
        pack_quantity=Decimal("500"),
        pack_label="500g",
        price_pence=350,
    )
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("1000"),
        pack_label="1kg",
        price_pence=700,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "100", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "dinner", meal.id)])
    line = _line(generate_shopping_list(session, week.id), "Minced beef")
    assert line.selected_purchase_option_id == first.id


def test_inactive_pack_is_not_chosen(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    retired = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Old shop"),
        pack_quantity=Decimal("500"),
        pack_label="old",
        price_pence=100,
    )
    change_purchase_option(session, retired, is_active=False)
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "600", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    line = _line(generate_shopping_list(session, week.id), "Minced beef")
    assert line.selected_purchase_option_id is None
    assert line.estimated_price_pence is None
    assert line.pack_count == 0


def test_chosen_option_survives_regeneration(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Market"),
        pack_quantity=Decimal("1000"),
        pack_label="1kg tray",
        price_pence=400,
    )
    dear = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "600", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    line = _line(shopping_list, "Minced beef")
    choose_purchase_option(session, line, dear.id)
    assert line.option_overridden is True
    assert line.shop_name == "Butcher"
    assert line.pack_count == 2
    assert line.estimated_price_pence == 700
    refreshed = generate_shopping_list(session, week.id)
    kept = _line(refreshed, "Minced beef")
    assert kept.selected_purchase_option_id == dear.id
    assert kept.option_overridden is True
    assert kept.shop_name == "Butcher"
    assert shopping_totals(refreshed).outlay_pence == 700


def test_inactive_chosen_option_falls_back_to_the_cheapest(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    cheap = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Market"),
        pack_quantity=Decimal("1000"),
        pack_label="1kg tray",
        price_pence=400,
    )
    dear = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "600", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    choose_purchase_option(session, _line(shopping_list, "Minced beef"), dear.id)
    change_purchase_option(session, dear, is_active=False)
    refreshed = generate_shopping_list(session, week.id)
    line = _line(refreshed, "Minced beef")
    assert line.selected_purchase_option_id == cheap.id
    assert line.option_overridden is False
    assert line.shop_name == "Market"


def test_missing_price_is_named_and_left_out_of_both_totals(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    salt = create_ingredient(session, name="Salt", canonical_unit=grams).ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(
        session,
        "Ragu",
        [
            RawLine(str(beef.id), "700", str(grams.id), ""),
            RawLine(str(salt.id), "5", str(grams.id), ""),
        ],
    )
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    salt_line = _line(shopping_list, "Salt")
    assert salt_line.estimated_price_pence is None
    assert salt_line.pack_price_pence is None
    totals = shopping_totals(shopping_list)
    assert totals.outlay_pence == 700
    assert totals.consumption_pence == 490
    assert totals.is_complete is False
    assert totals.missing_ingredients == ("Salt",)


def test_full_stock_has_no_outlay_but_keeps_consumption_cost(
    session: Session,
) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "100", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    adjust_stock(
        session,
        ingredient_id=beef.id,
        action=SET,
        quantity="500",
        unit_id=str(grams.id),
    )
    shopping_list = generate_shopping_list(session, week.id)
    line = _line(shopping_list, "Minced beef")
    assert line.stock_allocated == Decimal("100")
    assert line.net_quantity == Decimal("0")
    assert line.pack_count == 0
    assert line.estimated_price_pence == 0
    totals = shopping_totals(shopping_list)
    assert totals.outlay_pence == 0
    assert totals.consumption_pence == 70
    assert get_stock_map(session)[beef.id] == Decimal("500")


def test_regeneration_keeps_manual_lines_removals_and_overrides(
    session: Session,
) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    rice = create_ingredient(session, name="Rice", canonical_unit=grams).ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Market"),
        pack_quantity=Decimal("1000"),
        pack_label="1kg tray",
        price_pence=400,
    )
    dear = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    create_purchase_option(
        session,
        ingredient=rice,
        shop=_shop(session, "Grocer"),
        pack_quantity=Decimal("1000"),
        pack_label="1kg bag",
        price_pence=200,
    )
    meal = _meal(
        session,
        "Ragu",
        [
            RawLine(str(beef.id), "700", str(grams.id), ""),
            RawLine(str(rice.id), "200", str(grams.id), ""),
        ],
    )
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    manual = add_manual_line(
        session,
        shopping_list,
        description="Toilet roll",
        quantity=Decimal("1"),
        unit="pack",
        price_pence=150,
        shop_name="Chemist",
    )
    remove_generated_line(_line(shopping_list, "Rice"))
    beef_line = _line(shopping_list, "Minced beef")
    beef_line.checked = True
    choose_purchase_option(session, beef_line, dear.id)
    set_quantity_override(beef_line, Decimal("100"))
    revised, errors = prepare_lines(
        session,
        [
            RawLine(str(beef.id), "900", str(grams.id), ""),
            RawLine(str(rice.id), "300", str(grams.id), ""),
        ],
    )
    assert errors == {}
    save_meal(
        session,
        meal,
        name="Ragu",
        description=None,
        instructions=None,
        lines=revised,
    )
    refreshed = generate_shopping_list(session, week.id)
    assert refreshed.id == shopping_list.id
    assert session.scalar(select(func.count()).select_from(ShoppingList)) == 1
    kept_manual = _line(refreshed, "Toilet roll")
    assert kept_manual.id == manual.id
    assert kept_manual.manual_price_pence == 150
    assert kept_manual.shop_name == "Chemist"
    assert kept_manual.source == "manual"
    rice_line = _line(refreshed, "Rice")
    assert rice_line.removed is True
    assert rice_line.required_quantity == Decimal("300")
    kept_beef = _line(refreshed, "Minced beef")
    assert kept_beef.checked is True
    assert kept_beef.required_quantity == Decimal("900")
    assert kept_beef.quantity_overridden is True
    assert kept_beef.quantity_override == Decimal("100")
    assert kept_beef.selected_purchase_option_id == dear.id
    assert kept_beef.pack_count == 1
    assert kept_beef.estimated_price_pence == 350
    totals = shopping_totals(refreshed)
    assert totals.outlay_pence == 500
    onion = create_ingredient(session, name="Onion", canonical_unit=grams).ingredient
    create_purchase_option(
        session,
        ingredient=onion,
        shop=_shop(session, "Greengrocer"),
        pack_quantity=Decimal("1"),
        pack_label="each",
        price_pence=40,
    )
    with_onion, errors = prepare_lines(
        session,
        [
            RawLine(str(beef.id), "900", str(grams.id), ""),
            RawLine(str(rice.id), "300", str(grams.id), ""),
            RawLine(str(onion.id), "2", str(grams.id), ""),
        ],
    )
    assert errors == {}
    save_meal(
        session,
        meal,
        name="Ragu",
        description=None,
        instructions=None,
        lines=with_onion,
    )
    expanded = generate_shopping_list(session, week.id)
    assert _line(expanded, "Onion").net_quantity == Decimal("2")
    assert _line(expanded, "Toilet roll").id == manual.id
    without_rice, errors = prepare_lines(
        session,
        [
            RawLine(str(beef.id), "900", str(grams.id), ""),
            RawLine(str(onion.id), "2", str(grams.id), ""),
        ],
    )
    assert errors == {}
    save_meal(
        session,
        meal,
        name="Ragu",
        description=None,
        instructions=None,
        lines=without_rice,
    )
    dropped = generate_shopping_list(session, week.id)
    rice_left = [line for line in dropped.lines if line.description == "Rice"]
    assert rice_left == []
    assert _line(dropped, "Minced beef").quantity_overridden is True
    assert _line(dropped, "Toilet roll").manual_price_pence == 150


def test_restore_puts_a_removed_ingredient_back(session: Session) -> None:
    grams = _unit(session, "g")
    rice = create_ingredient(session, name="Rice", canonical_unit=grams).ingredient
    create_purchase_option(
        session,
        ingredient=rice,
        shop=_shop(session, "Grocer"),
        pack_quantity=Decimal("1000"),
        pack_label="1kg bag",
        price_pence=200,
    )
    meal = _meal(session, "Rice", [RawLine(str(rice.id), "200", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "dinner", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    line = _line(shopping_list, "Rice")
    remove_generated_line(line)
    assert shopping_totals(shopping_list).outlay_pence == 0
    restore_removed_line(line)
    assert line.removed is False
    assert shopping_totals(shopping_list).outlay_pence == 200


def test_checked_line_stays_when_the_plan_drops_the_ingredient(
    session: Session,
) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    rice = create_ingredient(session, name="Rice", canonical_unit=grams).ingredient
    for ingredient, shop_name in ((beef, "Butcher"), (rice, "Grocer")):
        create_purchase_option(
            session,
            ingredient=ingredient,
            shop=_shop(session, shop_name),
            pack_quantity=Decimal("500"),
            pack_label="pack",
            price_pence=200,
        )
    meal = _meal(
        session,
        "Ragu",
        [
            RawLine(str(beef.id), "200", str(grams.id), ""),
            RawLine(str(rice.id), "200", str(grams.id), ""),
        ],
    )
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    _line(shopping_list, "Minced beef").checked = True
    revised, errors = prepare_lines(
        session, [RawLine(str(rice.id), "200", str(grams.id), "")]
    )
    assert errors == {}
    save_meal(
        session, meal, name="Ragu", description=None, instructions=None, lines=revised
    )
    refreshed = generate_shopping_list(session, week.id)
    parked = _line(refreshed, "Minced beef")
    assert kept_without_requirement(parked) is True
    assert parked.required_quantity == Decimal("0")
    assert parked.pack_count == 0
    assert _line(refreshed, "Rice").required_quantity == Decimal("200")


def test_unchecked_line_is_removed_when_the_plan_drops_it(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "200", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    generate_shopping_list(session, week.id)
    rice = create_ingredient(session, name="Rice", canonical_unit=grams).ingredient
    revised, errors = prepare_lines(
        session, [RawLine(str(rice.id), "200", str(grams.id), "")]
    )
    assert errors == {}
    save_meal(
        session, meal, name="Ragu", description=None, instructions=None, lines=revised
    )
    refreshed = generate_shopping_list(session, week.id)
    assert [line.description for line in refreshed.lines] == ["Rice"]


def test_negative_override_is_rejected(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "200", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    line = _line(shopping_list, "Minced beef")
    with pytest.raises(FieldValidationError, match="cannot be negative"):
        set_quantity_override(line, Decimal("-1"))
    assert line.quantity_overridden is False


def test_refresh_reports_new_updated_and_removed_lines(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "200", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    _shopping_list, first = refresh_shopping_list(session, week.id)
    assert first.label() == "1 new"
    _unchanged, second = refresh_shopping_list(session, week.id)
    assert second.label() == "No changes"
    revised, errors = prepare_lines(
        session, [RawLine(str(beef.id), "500", str(grams.id), "")]
    )
    assert errors == {}
    save_meal(
        session, meal, name="Ragu", description=None, instructions=None, lines=revised
    )
    _updated, third = refresh_shopping_list(session, week.id)
    assert third.label() == "1 updated"
    rice = create_ingredient(session, name="Rice", canonical_unit=grams).ingredient
    with_rice, errors = prepare_lines(
        session,
        [
            RawLine(str(beef.id), "500", str(grams.id), ""),
            RawLine(str(rice.id), "200", str(grams.id), ""),
        ],
    )
    assert errors == {}
    save_meal(
        session,
        meal,
        name="Ragu",
        description=None,
        instructions=None,
        lines=with_rice,
    )
    _added, fourth = refresh_shopping_list(session, week.id)
    assert fourth.label() == "1 new"
    beef_only, errors = prepare_lines(
        session, [RawLine(str(beef.id), "500", str(grams.id), "")]
    )
    assert errors == {}
    save_meal(
        session,
        meal,
        name="Ragu",
        description=None,
        instructions=None,
        lines=beef_only,
    )
    _dropped, fifth = refresh_shopping_list(session, week.id)
    assert fifth.label() == "1 removed"


def test_pack_count_override_yields_to_a_quantity_edit(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "200", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    line = _line(shopping_list, "Minced beef")
    set_pack_count_override(line, 3)
    assert line.pack_count == 3
    assert line.estimated_price_pence == 1050
    refreshed = generate_shopping_list(session, week.id)
    kept = _line(refreshed, "Minced beef")
    assert kept.pack_count == 3
    set_quantity_override(kept, Decimal("100"))
    assert kept.pack_count_override is None
    assert kept.pack_count == 1
    with pytest.raises(FieldValidationError, match="cannot be negative"):
        set_pack_count_override(kept, -1)


def test_line_price_is_a_list_snapshot(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    option = create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "600", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    line = _line(shopping_list, "Minced beef")
    set_line_price(line, 200)
    assert line.estimated_price_pence == 400
    assert option.price_pence == 350
    manual = add_manual_line(session, shopping_list, description="Washing up liquid")
    set_line_price(manual, 150)
    assert manual.manual_price_pence == 150
    with pytest.raises(FieldValidationError, match="price"):
        set_line_price(line, None)  # type: ignore[arg-type]


def test_covering_a_requirement_does_not_reduce_larger_stock(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    meal = _meal(session, "Ragu", [RawLine(str(beef.id), "200", str(grams.id), "")])
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    summary = cover_requirement_with_stock(session, _line(shopping_list, "Minced beef"))
    assert summary.label() == "1 updated"
    covered = _line(shopping_list, "Minced beef")
    assert covered.net_quantity == Decimal("0")
    assert covered.pack_count == 0
    assert get_stock_map(session)[beef.id] == Decimal("200")
    again = cover_requirement_with_stock(session, covered)
    assert again.label() == "No changes"
    assert get_stock_map(session)[beef.id] == Decimal("200")
    adjust_stock(
        session,
        ingredient_id=beef.id,
        action=SET,
        quantity="500",
        unit_id=str(grams.id),
    )
    cover_requirement_with_stock(session, covered)
    assert get_stock_map(session)[beef.id] == Decimal("500")


def test_checklist_orders_shops_and_keeps_a_tick(session: Session) -> None:
    grams = _unit(session, "g")
    beef = create_ingredient(session, name="Minced beef", canonical_unit=grams)
    beef = beef.ingredient
    onion = create_ingredient(session, name="Onion", canonical_unit=grams).ingredient
    create_purchase_option(
        session,
        ingredient=beef,
        shop=_shop(session, "Butcher"),
        pack_quantity=Decimal("500"),
        pack_label="500g pack",
        price_pence=350,
    )
    create_purchase_option(
        session,
        ingredient=onion,
        shop=_shop(session, "Market"),
        pack_quantity=Decimal("1"),
        pack_label="each",
        price_pence=40,
    )
    meal = _meal(
        session,
        "Ragu",
        [
            RawLine(str(beef.id), "200", str(grams.id), ""),
            RawLine(str(onion.id), "1", str(grams.id), ""),
        ],
    )
    week = _plan(session, [(MONDAY, "lunch", meal.id)])
    shopping_list = generate_shopping_list(session, week.id)
    add_manual_line(session, shopping_list, description="Apples")
    by_shop = checklist_lines(list(shopping_list.lines), order="shop")
    assert [item.line.description for item in by_shop] == [
        "Minced beef",
        "Onion",
        "Apples",
    ]
    by_name = checklist_lines(list(shopping_list.lines), order="name")
    assert [item.line.description for item in by_name] == [
        "Apples",
        "Minced beef",
        "Onion",
    ]
    beef_line = _line(shopping_list, "Minced beef")
    totals = checklist_for(shopping_list).totals
    assert totals.estimated_pence == totals.remaining_pence
    set_line_checked(beef_line, True)
    ticked = checklist_for(shopping_list).totals
    assert ticked.estimated_pence == totals.estimated_pence
    beef_price = beef_line.estimated_price_pence or 0
    assert ticked.remaining_pence == totals.remaining_pence - beef_price
    assert beef_line.checked is True
    set_line_checked(beef_line, False)
    assert beef_line.checked is False
    with pytest.raises(FieldValidationError, match="collected"):
        set_line_checked(beef_line, 1)  # type: ignore[arg-type]
    remove_generated_line(beef_line)
    with pytest.raises(FieldValidationError, match="removed"):
        set_line_checked(beef_line, True)
    visible = checklist_lines(shopping_list.lines, order="shop")
    assert [item.line.description for item in visible] == ["Onion", "Apples"]
    with pytest.raises(FieldValidationError, match="A-Z"):
        checklist_lines(shopping_list.lines, order="aisle")


def test_generate_rejects_an_unknown_week(session: Session) -> None:
    with pytest.raises(FieldValidationError, match="planned"):
        generate_shopping_list(session, 999)
    assert session.scalar(select(func.count()).select_from(ShoppingList)) == 0
    assert session.scalar(select(func.count()).select_from(PurchaseOption)) == 0
