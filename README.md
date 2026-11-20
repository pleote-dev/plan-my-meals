<p align="center">
  <img src="icon.png" alt="Plan My Meals" width="128" />
</p>

# Plan My Meals for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Standalone **Home Assistant** integration for weekly meal planning, recipe library management, native Home Assistant AI support, external AI agent integration (e.g. Hermes / OpenJarvis / MCP), and **supermarket price tracking** (Continente, Auchan, Pingo Doce, Aldi, Lidl, Intermarché, Minipreço, El Corte Inglés, Mercadona).

---

## Features

- **100% Native Home Assistant Integration (no Pyscript required):** installs via HACS with full **Config Flow & Options Flow** UI setup.
- **Embedded Web App & Sidebar Panel:** automatically serves the interactive Plan My Meals UI inside Home Assistant's sidebar (zero manual `/config/www/` setup).
- **36 Copyright-Free Starter Recipes Included:** main meals, breakfasts, and desserts with structured ingredients, nutrition, and original MIT-licensed category artwork (see `ATTRIBUTIONS.md`).
- **Smart Weekly Generator:** 80% 4–5★ favorites, 20% new/unrated recipes, excludes 1–3★, avoids repeating categories on the same day, and preserves locked meals.
- **Supermarket Price Tracking & Menu Costing:**
  - Tracks major supermarkets in Portugal (Continente, Auchan, Pingo Doce / Mercadão, Aldi, Lidl, Intermarché, Minipreço, El Corte Inglés, Mercadona; extensible to other countries).
  - Computes **average meal cost**, **weekly average cost**, and **cost per person**.
  - Annotates shopping list items with quantity + lowest price and supermarket, e.g. **`Ovomaltine (2 un) (9€ Auchan)`**, and stores direct store links.
- **Native Home Assistant AI + External AI Agents:**
  - Works out of the box with any Home Assistant `ai_task.*` entity (Google Generative AI, OpenAI, Anthropic, Ollama, etc.).
  - Exposes full services (`plan_my_meals.*`) with `return_response` so external agents like **Hermes** can read/modify plans, add recipes, rate dishes, and sync shopping lists.
- **Exposed Entities for Custom Dashboards & Automations:**
  - `sensor.plan_my_meals_lunch_today` & `sensor.plan_my_meals_dinner_today` (with image, time, method, rating, avg cost, ingredients)
  - `sensor.plan_my_meals_week_cost` (weekly average cost, per-person cost, daily breakdown)
  - `sensor.plan_my_meals_missing_ingredients` (missing count + items with best price, store, and direct store URL)
  - `sensor.plan_my_meals_recipes`
  - `calendar.plan_my_meals` (weekly lunches & dinners in Home Assistant's Calendar)
  - `button.plan_my_meals_generate_week`, `button.plan_my_meals_sync_shopping_list`, `button.plan_my_meals_refresh_prices`
- **Automatic Legacy Migration:** if `/config/www/plan_my_meals_state.json` exists from a previous Pyscript installation, all existing recipes, custom variants, ratings, weekly plans, and local images are imported automatically on first startup.

---

## Installation via HACS

1. Open **HACS** → **Integrations** → menu (`⋮`) → **Custom repositories**.
2. Add `https://github.com/pleote-dev/plan-my-meals` with category **Integration**.
3. Search for **Plan My Meals** and click **Download**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration → Plan My Meals** and configure your shopping list (`todo.*`), servings, kitchen appliances, AI entity, and supermarkets.

---

## Services (Automations & External AI Agents)

| Service | Description |
|---|---|
| `plan_my_meals.get_plan` | Returns current plan, recipes, missing ingredients, and costs |
| `plan_my_meals.generate_week` | Generates a new weekly plan |
| `plan_my_meals.swap_meal` | Replaces lunch or dinner for a specific day (`0`..`6`) |
| `plan_my_meals.upsert_recipe` | Creates or updates a recipe or variant |
| `plan_my_meals.delete_recipe` | Deletes a recipe and its variants |
| `plan_my_meals.rate_recipe` | Sets 1–5★ rating (`0` clears) |
| `plan_my_meals.check_similarity` | Checks for duplicate or variant candidates |
| `plan_my_meals.upload_image` | Saves base64 or downloads image URL locally |
| `plan_my_meals.sync_shopping_list` | Pushes missing ingredients (`Ovomaltine (2 un) (9€ Auchan)`) to `todo.*` |
| `plan_my_meals.refresh_prices` | Refreshes supermarket prices for weekly ingredients (or all recipes) |
| `plan_my_meals.set_ingredient_price` | Manually sets or overrides a supermarket price & store URL |
