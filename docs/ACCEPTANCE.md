# Acceptance criteria

Checked against the tests in this repository on 8 Nov 2026. FR-20 was also checked by recreating the Docker container and confirming `data/app.db` was still present.

| ID | How it is covered | Status |
|---|---|---|
| FR-01 | `tests/test_ingredient_http.py::test_create_ingredient_with_canonical_unit` creates Ham in slices and finds it from the meal editor search. | Pass |
| FR-02 | `tests/test_meal_http.py::test_inline_ingredient_updates_the_line_without_the_meal_form` adds an ingredient inside the recipe editor and keeps the line. | Pass |
| FR-03 | `tests/test_ingredient_http.py::test_two_purchase_options_stay_unselected` saves two packs, each with a shop, quantity, label, and price. | Pass |
| FR-04 | `tests/test_ingredient_http.py::test_price_change_keeps_history_newest_first` and `tests/test_purchase_history.py::test_history_records_price_and_pack_changes`. | Pass |
| FR-05 | `tests/test_meals.py::test_complete_recipe_cost_uses_canonical_quantity` and `tests/test_meal_http.py::test_meal_page_shows_a_complete_two_person_cost`. | Pass |
| FR-06 | `tests/test_units.py::test_grams_rejected_for_sliced_ham` and `tests/test_meal_http.py::test_incompatible_unit_is_shown_beside_the_field`. | Pass |
| FR-07 | `tests/test_units.py::test_kilogram_converts_to_grams` and `tests/test_units.py::test_millilitres_and_grams_are_rejected`. | Pass |
| FR-08 | `tests/test_planner.py::test_same_meal_can_be_used_twice_and_keeps_its_snapshot` and `tests/test_planner_http.py::test_repeated_meal_and_takeaway_stay_on_the_page`. Blank slots are `tests/test_planner.py::test_replacing_a_slot_keeps_a_single_row`. | Pass |
| FR-09 | `tests/test_planner.py::test_takeaway_requires_a_non_negative_price_and_adds_no_ingredients` and `tests/test_planner.py::test_week_cost_keeps_takeaway_separate_from_meal_cost`. | Pass |
| FR-10 | `tests/test_planner_http.py::test_past_and_future_weeks_keep_their_meals`. | Pass |
| FR-11 | `tests/test_shopping.py::test_spec_example_keeps_outlay_separate_from_consumption` aggregates 200g and 500g of the same ingredient. | Pass |
| FR-12 | The same spec-example test deducts pantry stock once before pack rounding. `tests/test_shopping.py::test_covering_a_requirement_does_not_reduce_larger_stock` confirms stock itself is not decremented. | Pass |
| FR-13 | `tests/test_shopping.py::test_packs_round_up_to_whole_packs` and the spec example: 600g net against a 500g pack is 2 packs and £7.00 outlay. | Pass |
| FR-14 | `tests/test_shopping_http.py::test_changing_the_pack_uses_that_shop` and `tests/test_shopping.py::test_chosen_option_survives_regeneration`. | Pass |
| FR-15 | `tests/test_shopping.py::test_regeneration_keeps_manual_lines_removals_and_overrides` and `tests/test_shopping.py::test_restore_puts_a_removed_ingredient_back`. | Pass |
| FR-16 | `tests/test_shopping_http.py::test_checklist_tick_persists_and_print_is_plain` checks a line, reloads, and asserts the 48px phone targets in the stylesheet. | Pass |
| FR-17 | The same checklist test prints the shopping list with no navigation. `tests/test_planner_http.py::test_generate_pdf_is_one_a4_landscape_page` builds the meal-plan PDF. | Pass |
| FR-18 | `tests/test_spend.py::test_actual_spend_sums_shops_and_keeps_the_estimate_separate` and `tests/test_spend_http.py::test_recording_spend_keeps_the_estimate_out_of_the_total`. | Pass |
| FR-19 | `tests/test_spend_http.py::test_recording_spend_keeps_the_estimate_out_of_the_total` shows Grocery (actual) and Takeaway as separate labelled series, with the estimate hatched apart from them. | Pass |
| FR-20 | `tests/test_integrity.py::test_compose_publishes_localhost_and_keeps_the_database` checks the `./data` mount. Recreating the container with `docker compose up -d --build` left `data/app.db` in place. | Pass |
