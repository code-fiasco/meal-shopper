# Meal Planner & Shopping App

## Software Requirements Specification

**Version 1.0 | 8 November 2026**

A self-hosted web application for planning two-person meals, managing ingredient and shop-specific prices, generating shopping lists, tracking pantry stock, and understanding food spending over time.

*Prepared as an implementation-ready product specification*

---

## Document guide

- **Purpose:** define the product behaviour and business rules clearly enough to guide implementation.
- **Scope:** a single-household application, hosted on the user's Linux server in Docker and accessed through a browser, including a mobile-friendly shopping view.
- **Currency and locale:** GBP (£), UK-style dates and measurements by default.
- **Terminology:** an *ingredient* is a reusable database item; a *purchase option* is a shop-specific pack and price; a *meal* is a recipe; a *planner entry* is a meal or takeaway assigned to a lunch/dinner slot.

> **Important design principle:** the application must distinguish the cost of the ingredients consumed from the money actually required to buy whole packs. Weekly spending reports should prioritise actual recorded shopping expenditure, not merely the theoretical cost of recipe portions.

---

## 1. Product overview

The application combines a recipe library, weekly meal planner, ingredient and price database, pantry-stock tracker, shopping-list generator, and food-spend reporting. The user creates meals from centrally managed ingredients, schedules meals for lunch and dinner across multiple weeks, and generates a consolidated shopping list from the planned meals.

The app is intended for one user and one household of two people. Every planned recipe meal is for two portions. A meal can be scheduled repeatedly, left blank, or replaced with a takeaway entry whose price is entered for that occasion.

### 1.1 Goals

- Make it quick to create and maintain recipes and their ingredient quantities.
- Plan lunch and dinner for any week, including weeks in the future, while retaining historical plans.
- Generate one consolidated list of ingredients and non-food extras from the selected week's plan.
- Subtract ingredients already in household stock, while showing what the recipes require in total.
- Compare shop-specific purchasing options and estimate the cost of buying whole packs.
- Record actual shopping expenditure and chart food spending over time.
- Provide printable weekly plans and a simple, phone-friendly shopping checklist.

### 1.2 Out of scope for the initial release

- Multiple user accounts, household sharing, permissions, or public registration.
- Automatic supermarket price scraping, online ordering, loyalty-card integration, or live stock availability.
- Nutritional analysis, calorie tracking, dietary planning, barcode scanning, and recipe imports.
- Ingredient categories for shopping-list grouping (the user has explicitly said categories are unnecessary).
- Email delivery as a required feature; the selected delivery method is a mobile-friendly web page.

---

## 2. Deployment and technical requirements

### 2.1 Hosting

- The application shall run as a Dockerised web application on the user's existing Linux server.
- The user shall access it through a modern web browser on desktop and mobile devices.
- The application shall persist data outside the container filesystem using a Docker volume or bind mount.
- The application shall support restart and container recreation without losing application data.
- Configuration such as port, database path, timezone, and application settings should be supplied through environment variables or a documented configuration file.

### 2.2 Suggested architecture

A conventional single-server web architecture is recommended. The exact framework is an implementation choice, but the design should keep the user interface, business rules, and persistence layer clearly separated.

| Layer | Suggested approach / requirement |
|---|---|
| Frontend | Responsive web UI. A server-rendered application or a lightweight JavaScript frontend is suitable. |
| Backend | REST-style or server-rendered backend responsible for validation, calculations, and persistence. |
| Database | SQLite is sufficient for a single-user deployment; PostgreSQL is also acceptable if already standard in the user's Docker environment. |
| Container | Docker image with documented build/run instructions and persistent data mount. |
| Backups | Provide a straightforward database backup and restore procedure; ideally expose an export/backup action in the UI. |

The app should not depend on an external cloud service for normal operation. It should remain usable on the local network when internet access is unavailable, except for any future optional integrations.

---

## 3. Main application areas

| Area | Responsibilities |
|---|---|
| Dashboard / navigation | Navigate to planner, meals, ingredients, shopping lists, stock, and spending reports. |
| Meal library | Create, edit, duplicate, archive, and view recipes. |
| Ingredient database | Manage canonical ingredient records, units, purchase options, shops, and price history. |
| Weekly planner | Plan lunch and dinner for multiple weeks; retain completed and historical weeks. |
| Shopping list | Generate, edit, price, print, and use a live mobile checklist. |
| Pantry stock | Record remaining quantities and allocate stock against planned requirements. |
| Spending reports | Review estimated and actual weekly spending and historical trends. |

---

## 4. Ingredient database and unit model

### 4.1 Central ingredient records

Every ingredient used by a recipe or shopping list must refer to one central ingredient record. Users must be able to create a new ingredient from within the meal editor without leaving the recipe workflow. The newly created ingredient should immediately become selectable in that recipe.

An ingredient record should include:

- Name (required and unique enough to avoid accidental duplicates; warn on likely duplicate names).
- Canonical measurement unit and measurement type.
- Optional notes or description.
- Active/archived status, so obsolete ingredients can be hidden without breaking old recipes or historical shopping lists.
- One or more shop-specific purchase options.

### 4.2 Canonical units and strict validation

Each ingredient has exactly one canonical unit for quantities used in recipes, pantry stock, and shopping requirements. The unit is selected when the ingredient is created and is authoritative everywhere that ingredient is used.

Examples:

| Ingredient | Canonical unit | Purchase option example | Recipe quantity example |
|---|---|---|---|
| Honey roast ham | slice | 10 slices for £1.79 at Shop A | 6 slices |
| Sugar | g | 1,000g for £0.89 at Shop B | 200g |
| Milk | ml | 2,000ml for £1.55 at Shop A | 300ml |
| Eggs | egg | 6 eggs for £1.20 at Shop C | 2 eggs |
| Garlic | clove | 1 bulb / 10 cloves (if explicitly configured) | 2 cloves |

> **Mandatory rule:** a recipe ingredient quantity must use the ingredient's canonical unit or a supported conversion to it. If ham is configured in slices, a recipe must not enter ham in grams. The system must reject incompatible units rather than silently converting or guessing.

### 4.3 Unit families and conversions

- **Weight:** mg, g, kg. Convert using exact metric relationships (e.g. 1kg = 1,000g).
- **Volume:** ml, litres. Convert using exact metric relationships (e.g. 1 litre = 1,000ml).
- **Count:** individual count units such as egg, slice, clove, or item. These are not interchangeable by default.
- **Kitchen measures:** teaspoon, tablespoon, handful, pinch, cup, etc. These may be used as distinct units unless an explicit, ingredient-specific conversion is defined.
- Do not assume a weight-to-volume conversion (for example, grams to millilitres) because density varies by ingredient.
- Do not infer conversions between count units (for example, slices and grams, or cloves and bulbs) unless a user explicitly defines a valid conversion.

The interface should show the canonical unit when an ingredient is selected and constrain the quantity-entry control accordingly. If an incompatible unit is entered or imported, show a clear validation message naming the required unit.

### 4.4 Purchase options

An ingredient may have multiple purchase options. Each option represents a specific pack size, price, and shop, enabling the user to compare options but still choose a more convenient or preferred shop.

| Field | Description |
|---|---|
| Shop | Shop or retailer name (free text; reusable shop records are recommended). |
| Pack quantity | Quantity of the ingredient contained in one purchase unit, expressed in the ingredient's canonical unit after conversion. |
| Pack label | Human-readable pack description, e.g. '10 slices', '1kg bag', '6 pack'. |
| Price | Current price in GBP, stored to currency precision. |
| Price history | Previous prices with effective/recorded dates; updating a price must not erase earlier values. |
| Active status | Allow discontinued or unavailable purchase options to be archived. |

The same ingredient may have options at different shops and different pack sizes. For example, sugar may be available as 1kg at Shop A and 2kg at Shop B. The app should calculate comparable cost per canonical unit, but must not automatically force the cheapest shop choice.

### 4.5 Shops

A lightweight shop list should support reusable shop names. A purchase option must be associated with a shop, while manually added shopping-list items may optionally specify a shop or remain unassigned.

### 4.6 Price history

When a purchase option's price or pack quantity is updated, retain the old value and record the date of the change. Historical meal and shopping calculations should use a stored price snapshot or transaction record so later price edits do not rewrite the past.

---

## 5. Meal / recipe management

### 5.1 Creating and editing meals

A meal record should contain:

- Meal name (required).
- Optional description, preparation notes, or cooking instructions.
- A list of ingredient lines, each linked to a central ingredient.
- A quantity for each ingredient, expressed in its canonical unit (or a supported compatible unit converted to canonical storage).
- The recipe's default and fixed serving count: two portions.

For this household, recipes are defined for two portions. The app should not require a serving-count adjustment in the planner. If serving scaling is added later, it must be explicitly designed rather than changing the fixed two-person rule in the initial release.

### 5.2 Recipe calculations

The app should calculate the theoretical ingredient consumption cost for the two-person recipe using the selected or default active purchase option price per canonical unit. This is an estimated allocation cost, not necessarily the amount paid at the till.

If an ingredient has no active purchase option or price, the recipe remains usable but its cost should be marked incomplete. The UI should identify the missing price rather than treating it as zero.

### 5.3 Recipe maintenance

- Edit a meal and its ingredient lines.
- Duplicate a meal to create a variation.
- Delete or archive a meal, with a warning if it appears in historical planner entries.
- Preserve historical plan and spend records if a recipe is later edited or archived.
- Allow a meal to be selected multiple times in the same week or across different weeks.

---

## 6. Weekly meal planner

### 6.1 Planner layout

The planner shall display a seven-day week with two meal slots per day: Lunch and Dinner. The default week view should be clear and usable on desktop, with a practical responsive layout on smaller screens.

| Day | Lunch | Dinner |
|---|---|---|
| Monday | Selected meal / blank / takeaway | Selected meal / blank / takeaway |
| Tuesday | Selected meal / blank / takeaway | Selected meal / blank / takeaway |
| Wednesday | Selected meal / blank / takeaway | Selected meal / blank / takeaway |
| Thursday | Selected meal / blank / takeaway | Selected meal / blank / takeaway |
| Friday | Selected meal / blank / takeaway | Selected meal / blank / takeaway |
| Saturday | Selected meal / blank / takeaway | Selected meal / blank / takeaway |
| Sunday | Selected meal / blank / takeaway | Selected meal / blank / takeaway |

### 6.2 Planner behaviour

- Users can navigate to previous and future weeks and create plans for multiple weeks ahead.
- Each lunch and dinner slot can be left empty.
- Each slot can select any saved meal; the same meal can be selected repeatedly.
- Each planned recipe entry is for two portions.
- The application must save changes persistently and retain previous weeks as historical records.
- The planner should show a weekly estimated meal cost where prices are available.

### 6.3 Takeaway entries

A built-in 'Takeaway' option must be available in any lunch or dinner slot. Selecting it should prompt for a custom price for that specific occurrence. The user may optionally add a short description (e.g. 'Pizza' or 'Indian takeaway').

The takeaway price is a direct expense for that planner entry. It must be included in weekly spending totals and historical charts, but it does not create ingredient requirements or shopping-list lines.

### 6.4 Printable meal plan

Provide a print-friendly weekly meal plan designed for A4 landscape. It should show the week/date range, seven days, and lunch/dinner assignments. It should be uncluttered and readable, with optional meal-cost display. Browser print output should avoid navigation, buttons, and other application controls.

---

## 7. Pantry / in-stock ingredient tracking

### 7.1 Purpose

Users must be able to mark ingredients as already in stock so that the shopping list does not ask them to buy items they already own. This must support quantities, not just a binary 'have it' flag.

### 7.2 Stock records

For each ingredient, store an on-hand quantity in the canonical unit. The user should be able to enter or adjust the quantity at any time, for example 1,000g of flour, 6 eggs, or 4 slices of ham.

- Stock quantity must use the same canonical unit and unit validation rules as recipes.
- Allow a quick action from the shopping list to mark an ingredient as already in stock or adjust the quantity available.
- When generating a list, compare total planned requirement against available stock.
- If the planned requirement is 100g flour and 1,000g is in stock, the required purchase quantity is zero.
- If the planned requirement is 1,200g flour and 1,000g is in stock, the required purchase quantity is 200g before pack rounding.
- Show total recipe requirement, stock allocated, and remaining quantity to buy where useful.

For the initial release, stock should be manually maintained by the user. The app should not silently assume that a purchase automatically means the entire pack is still in stock or that recipe consumption has been physically verified. A later enhancement could offer prompts to update stock after shopping or after a planned week.

### 7.3 Avoiding double-counting

Stock must be applied once to the consolidated ingredient requirement for the selected week's plan, not separately to each recipe line. The system should aggregate all recipe uses of the same ingredient first, then subtract available stock.

---

## 8. Shopping list generation and editing

### 8.1 Generation

The shopping list is generated from all recipe meals in the selected week. Takeaways and blank slots do not generate ingredient requirements. Ingredient quantities are aggregated across all meals and both meal slots.

The generator must:

- Aggregate quantities by central ingredient ID, after converting compatible units to canonical units.
- Subtract available pantry stock from the aggregated weekly requirement.
- Calculate the remaining quantity to buy.
- Select or allow the user to select a purchase option for each ingredient.
- Round the purchase quantity up to whole packs where the purchase option is sold in packs.
- Show the recipe requirement, stock available/used, net quantity to buy, selected shop/pack, number of packs, and estimated cost.

### 8.2 Example

| Item | Value |
|---|---|
| Recipe requirement for week | 700g minced beef |
| Pantry stock available | 100g |
| Net amount to buy | 600g |
| Selected purchase option | 500g pack at £3.50 |
| Packs required | 2 packs (1,000g purchased) |
| Estimated shopping outlay | £7.00 |
| Theoretical consumption cost | £4.90 for 700g, before stock allocation |

The interface should make clear that buying two packs may leave unused stock. The shopping outlay and consumption cost must not be conflated.

### 8.3 Purchase option selection

For each ingredient, the user should be able to choose which shop and pack option to use for this particular shopping list. The default selection may be the lowest unit-cost active option, but the user must be able to override it to avoid visiting multiple shops or to choose a preferred retailer.

The shopping list should allow the user to see available alternatives and their prices. A future enhancement could support a preferred-shop setting or a 'minimise number of shops' optimisation, but neither is required for the first release.

### 8.4 Manual additions and removals

- Users can add arbitrary extra shopping items that are not linked to recipe ingredients, e.g. toilet roll, washing-up liquid, coffee, or snacks.
- Manual items may have a name, optional quantity/unit, optional price, and optional shop.
- Users can remove generated items they already have or do not wish to buy.
- Users can edit quantities, pack counts, selected purchase options, and prices for the current list.
- Manual additions and user removals must survive a re-generation after the meal plan changes, wherever possible.
- If a regenerated list changes an ingredient requirement, update the generated quantity while preserving the user's purchase-option choice and manual adjustments when still valid.
- Provide a clear way to restore a removed generated item if the user changes their mind.

### 8.5 Shopping list lifecycle

A shopping list should be associated with a specific planner week and have a persistent identity. It should be possible to revisit it later. Regeneration must update the existing list rather than create confusing duplicates.

The system should distinguish generated lines from manually added lines and record user overrides. If the user edits a generated quantity, the UI should indicate that the quantity has been manually adjusted so the next regeneration can handle it predictably.

---

## 9. Shopping list mobile view and printing

### 9.1 Mobile checklist

The shopping list should be accessible through a responsive web page that works well on a phone browser. Each line should have a large, easy-to-tap checkbox and display the item, quantity/pack details, shop (if selected), and price.

- Ticking an item marks it as collected/purchased for the current list.
- Checked state must persist if the page is refreshed or reopened on the same device.
- Show a total estimated shopping cost and, where useful, a remaining/uncollected total.
- Provide a simple 'show unchecked only' view or filter.
- The page should not require installing a native mobile app.

### 9.2 Printing

Provide a minimal print view intended for A4 paper. The user prefers a plain text-style list rather than a heavily designed document. Include item names, quantities, pack counts, prices, and optional checkboxes. Hide navigation and editing controls in print output.

The meal plan and shopping list have separate print layouts: A4 landscape for the weekly meal plan, and a compact, simple A4 list for shopping.

---

## 10. Costing and spending records

### 10.1 Required cost concepts

| Cost measure | Meaning | Use |
|---|---|---|
| Ingredient consumption cost | The value of the quantity used by recipes, calculated from the selected purchase option's unit price. | Recipe and meal costing. |
| Estimated shopping outlay | The cost of whole packs/items the generated list says to buy, after stock is deducted. | Planning a shopping trip. |
| Actual shopping spend | The amount the user records as actually paid for the shopping trip/list. | Primary weekly spending reports. |
| Takeaway spend | The custom price entered for each takeaway planner entry. | Included in weekly food spending. |

### 10.2 Meal cost

For a two-person meal, calculate each ingredient's allocated cost as: *recipe quantity in canonical units × purchase-option price per canonical unit*. Sum the ingredient costs to produce the meal's estimated ingredient cost. If no price is available for one or more ingredients, show a partial/incomplete total and identify missing prices.

The UI may also display an estimated cost per person (meal cost divided by two), but the primary recipe cost is for the full two-person meal.

### 10.3 Shopping cost

For each shopping-list line, estimated outlay is whole packs required multiplied by the selected pack price, plus any manually added item prices. If an item is removed or marked as already in stock, it must not be included in the estimated amount to pay.

### 10.4 Actual spend capture

Because the user's primary interest is what was actually spent each week, the app must support recording actual spend. On a shopping list, provide a way to confirm the list as shopped and enter or adjust the amount actually paid. The actual amount may differ from the estimate because of substitutions, promotions, unavailable items, or user choices.

- Store actual shopping spend against the relevant week and shopping-list record.
- Allow the user to enter one total paid amount and optionally adjust individual line prices/quantities.
- Do not assume the estimated shopping total is the actual amount paid.
- Support weeks with no shopping trip or no recorded actual spend; show them as unrecorded rather than £0 spent.
- If the user makes multiple shopping trips for one week, the data model should allow multiple spend transactions or shopping lists associated with that week.

### 10.5 Weekly food spend

Provide a weekly total that can include actual grocery spend plus takeaway spend. Display the components separately so grocery expenditure and takeaway expenditure remain understandable. If actual grocery spend has not been entered, label the figure as estimated or incomplete rather than presenting it as actual.

The specification assumes takeaway prices are recorded when the takeaway is planned and count toward that week's food spending. A later refinement may distinguish planned takeaway cost from confirmed amount paid.

---

## 11. Spending charts and history

The application should retain past planner weeks, shopping lists, price snapshots, and actual spend records. Provide a spending dashboard with at least:

- A chart of total food spending by week over time.
- A breakdown of grocery spend versus takeaway spend.
- A clear distinction between actual, estimated, and incomplete weeks.
- A selectable date range or number of weeks to display.
- Weekly totals and an overall total/average for the selected period.

The main chart should use actual recorded grocery spend plus recorded takeaway spend where available. Estimated shopping outlay may be shown separately or as a distinct visual series, but must not be mixed invisibly with actual spending.

Price history should be viewable for each purchase option so the user can see how a product's price has changed over time. Historical reports must use historical price/spend snapshots, not current prices applied retrospectively.

---

## 12. Data model (logical entities)

The following is a logical model, not a mandate for exact table names or database technology.

| Entity | Key fields / relationships |
|---|---|
| Ingredient | ID, name, canonical unit, unit type, notes, active flag. |
| Unit definition | ID, name, family/type, conversion factor where valid; supports custom count/kitchen units. |
| Shop | ID, name, optional notes. |
| Purchase option | ID, ingredient ID, shop ID, pack quantity in canonical units, pack label, current price, active flag. |
| Purchase price history | Purchase option ID, price, pack quantity, effective/recorded timestamp. |
| Meal / recipe | ID, name, description/instructions, active flag, created/updated timestamps. |
| Recipe ingredient | Meal ID, ingredient ID, quantity in canonical units, optional line notes. |
| Planner week | ID, week-start date, status/metadata. |
| Planner entry | Week ID, date, meal slot (lunch/dinner), entry type (meal/takeaway/blank), meal ID or takeaway description, takeaway price. |
| Pantry stock | Ingredient ID, on-hand quantity in canonical units, last-updated timestamp. |
| Shopping list | ID, planner week ID, created/updated timestamps, status. |
| Shopping list line | List ID, source type (generated/manual), ingredient ID if applicable, description, required quantity, stock allocation, net quantity, purchase option, pack count, estimated price, checked state, manual override metadata. |
| Shopping transaction | Shopping list/week ID, date, actual total paid, optional notes. |
| Shopping transaction line (optional) | Transaction ID, shopping-list line ID, actual quantity/price, substitution or adjustment notes. |

### 12.1 Historical integrity

Historical planner entries and shopping records must remain meaningful if a meal, ingredient, purchase option, or price is edited later. Use soft deletion/archive where appropriate and snapshot the relevant names, quantities, pack details, and prices on generated lists and completed transactions.

### 12.2 Data integrity

- Use stable IDs and foreign-key relationships.
- Prevent deletion of ingredients that are referenced by recipes or historical lists; archive instead.
- Validate all quantities as non-negative, and prices as non-negative GBP values.
- Store currency values using decimal-safe representation (e.g. integer pence or fixed-precision decimal), not binary floating-point.
- Store quantities with sufficient precision for recipe measurements and convert to canonical units before calculations.

---

## 13. User interface requirements

### 13.1 Desktop

- Provide clear navigation between Planner, Meals, Ingredients, Shopping, Stock, and Spending.
- Optimise common workflows: add a recipe ingredient, create a new ingredient inline, assign meals to the week, and generate a list.
- Show validation errors beside the relevant field with actionable messages.
- Use confirmation prompts for destructive actions and clear status indicators for archived, incomplete, estimated, and actual data.

### 13.2 Mobile

- The shopping list must be mobile-first or fully responsive, with large tap targets and minimal clutter.
- The weekly planner should remain usable on a phone, even if its layout changes from a seven-column grid to a day-by-day list.
- Do not require horizontal scrolling for the core shopping checklist.

### 13.3 Accessibility and usability

- Use readable contrast, labels, keyboard-accessible controls, and visible focus states.
- Do not communicate checked/unchecked or valid/invalid state using colour alone.
- Use clear units alongside every quantity; never show an unexplained bare number.

---

## 14. Functional requirements and acceptance criteria

The following criteria should be used to test the initial implementation.

| ID | Requirement / acceptance test |
|---|---|
| FR-01 | Create a central ingredient with a canonical unit; it is selectable from the meal editor. |
| FR-02 | Create a new ingredient from within the meal editor and add it to the current recipe without losing entered recipe data. |
| FR-03 | Add multiple purchase options for one ingredient, each with a shop, pack quantity, pack label, and price. |
| FR-04 | Update a purchase price and verify the old price remains available in price history. |
| FR-05 | Create a two-portion recipe with ingredient quantities and calculate its estimated ingredient cost. |
| FR-06 | Attempt to enter ham in grams when its canonical unit is slices; the app rejects the incompatible unit and explains the expected unit. |
| FR-07 | Convert compatible metric units correctly (e.g. 1kg sugar to 1,000g) without allowing invalid cross-family conversion. |
| FR-08 | Plan lunch and dinner for seven days, leave some slots blank, and select the same meal more than once. |
| FR-09 | Add a takeaway to a planner slot with a custom price; it affects weekly food spend but creates no ingredient requirement. |
| FR-10 | Navigate to a future week, save a plan, return later, and confirm the plan persists; previous weeks remain accessible. |
| FR-11 | Generate a shopping list and verify duplicate ingredient requirements across meals are aggregated. |
| FR-12 | Enter pantry stock; verify stock is deducted once from total weekly requirement before pack rounding. |
| FR-13 | For 600g net requirement and a 500g pack, verify two packs are shown and the outlay is two pack prices. |
| FR-14 | Choose a more expensive shop option instead of the cheapest option and verify the list uses the chosen option. |
| FR-15 | Add a manual non-recipe item, remove a generated item, change a meal, and regenerate; manual additions and valid removals/overrides are retained. |
| FR-16 | Open the shopping list on a phone-sized viewport; checkboxes are usable and checked state persists after refresh. |
| FR-17 | Print the shopping list as a compact plain list and print the weekly meal plan in A4 landscape. |
| FR-18 | Record actual shopping spend different from the estimate; reports show actual and estimated figures distinctly. |
| FR-19 | View a weekly spending chart over multiple weeks with grocery and takeaway components distinguishable. |
| FR-20 | Restart/recreate the Docker container and verify all user data remains intact. |

---

## 15. Non-functional requirements

- **Reliability:** normal operations should not lose saved recipes, planner entries, lists, or spending records.
- **Persistence:** database files and uploaded/generated data must live in a persistent Docker-mounted location.
- **Backup and restore:** document a reliable backup method and test restoration.
- **Performance:** ordinary operations and weekly list generation should feel immediate for a personal-sized dataset.
- **Security:** no public registration; recommend LAN-only access or authentication if exposed beyond a trusted home network. Do not expose an unauthenticated app directly to the public internet.
- **Privacy:** keep household and spending data local by default; no telemetry or third-party data sharing is required.
- **Maintainability:** provide documented configuration, database migrations, and a straightforward upgrade process.
- **Portability:** support current mainstream desktop and mobile browsers.

---

## 16. Suggested implementation phases

| Phase | Deliverables |
|---|---|
| 1. Foundation | Docker deployment, persistent database, navigation, ingredient/unit/shop data model. |
| 2. Recipes | Meal CRUD, inline ingredient creation, recipe quantities, unit validation, recipe costing. |
| 3. Planner | Seven-day lunch/dinner planner, multiple weeks, blank slots, takeaway entries, print layout. |
| 4. Stock and shopping | Pantry quantities, weekly aggregation, stock deduction, pack rounding, shop-option selection, editable persistent lists. |
| 5. Mobile and print | Responsive shopping checklist, persistent checked state, compact shopping print view. |
| 6. Spending | Actual spend entry, price history, weekly reports, historical charts. |
| 7. Hardening | Backup/restore, validation tests, Docker restart tests, usability and mobile testing. |

---

## 17. Decisions and assumptions to confirm during implementation

- **Week boundary:** use Monday to Sunday as the default UK-style planning week.
- **Timezone:** use the server's configured timezone or an application setting; display dates consistently.
- **Fixed portions:** all saved meals are costed and planned for two portions in the initial version.
- **Pantry accounting:** stock is manually maintained; the app subtracts stock for list generation but does not silently decrement stock when a plan is completed.
- **Actual spending:** the user explicitly records the amount paid; estimates are never automatically treated as actual spend.
- **Purchase-option default:** the cheapest active unit-cost option may be preselected, but user choice always takes precedence.
- **Manual list edits:** retain additions, removals, and valid overrides when a list is regenerated; provide a way to restore removed generated lines.
- **Categories:** omit ingredient and shopping categories in the initial version, as requested.

These are sensible defaults rather than blockers. They can be changed during implementation without altering the overall product concept.

---

## 18. Summary

The core of the application is a consistent ingredient model: every ingredient has a canonical unit, reusable shop-specific pack options, and a price history. Recipes refer to those ingredients and define quantities for two portions. The planner schedules recipes or individually priced takeaways across multiple weeks. The shopping generator aggregates recipe requirements, deducts pantry stock, rounds purchases to whole packs, and preserves user edits. Finally, the system distinguishes theoretical ingredient consumption cost, estimated whole-pack shopping outlay, and actual recorded expenditure so that weekly spending charts reflect what the household really spent.

This separation of recipe quantities, stock, purchasing choices, and actual spend is the most important architectural decision in the specification. It will prevent misleading totals and make the application useful beyond a simple recipe calendar.
