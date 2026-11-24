<p align="center">
  <img src="icon.png" alt="Plan My Meals" width="128" />
</p>

<p align="center">
  🌐 <strong>English</strong> | <a href="README.pt.md">Português</a>
</p>

# Plan My Meals for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate with HACS](https://github.com/pleote-dev/plan-my-meals/actions/workflows/hacs.yml/badge.svg)](https://github.com/pleote-dev/plan-my-meals/actions/workflows/hacs.yml)
[![Validate with hassfest](https://github.com/pleote-dev/plan-my-meals/actions/workflows/hassfest.yml/badge.svg)](https://github.com/pleote-dev/plan-my-meals/actions/workflows/hassfest.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Standalone **Home Assistant** integration for weekly meal planning, recipe library management, native Home Assistant AI support, external AI agent integration (e.g. Hermes / OpenJarvis / MCP), and **supermarket price & unit tracking** (Continente, Auchan, Pingo Doce, Aldi, Lidl, Intermarché, Minipreço, El Corte Inglés, Mercadona).

---

## Features

- **100% Native Home Assistant Integration:** installs via HACS with full **Config Flow & Options Flow** UI setup.
- **Embedded Web App & Sidebar Panel:** automatically serves the interactive Plan My Meals UI inside Home Assistant's sidebar (zero manual `/config/www/` setup).
- **Automatic Home Assistant Language Sync (English & Portuguese included):** seamlessly follows your Home Assistant user language preference (Portuguese when HA is set to Portuguese, English when HA is set to English or any unsupported language) and uses simple JSON locale files so additional languages can be contributed easily.
- **60 Copyright-Free Starter Recipes Included:** 36 main meals, 12 breakfasts, and 12 desserts with structured ingredients, nutrition, step-by-step instructions, and original MIT-licensed category artwork (see `ATTRIBUTIONS.md`), with automatic backfill on upgrades so starter recipes are never lost.
- **Smart Weekly Generator:** 80% 4–5★ favorites, 20% new/unrated recipes, excludes 1–3★, avoids repeating categories on the same day, and preserves locked meals.
- **Live Supermarket Price & Unit Tracking + Interactive Popover:**
  - Scrapes live prices, pack units (e.g. `1 kg`, `500 g`, `1 L`, `6 un`), and unit prices (e.g. `1,89 €/kg`) across major supermarkets in Portugal (Continente, Auchan, Pingo Doce / Mercadão, Aldi, Lidl, Intermarché, Minipreço, El Corte Inglés, Mercadona; extensible to other countries), with automatic AI fallback via `ai_task.*` or `conversation.*`.
  - **Interactive Ingredient Price Popover:** hover or click any ingredient in the **Shopping List** or **Recipe Details** to open a compact floating card showing the best price, pack unit, price per unit, average price, and a full supermarket comparison with direct store links.
  - Computes **average meal cost**, **weekly average cost**, and **cost per person**.
  - Annotates shopping list items with quantity + lowest price and supermarket, e.g. **`Ovomaltine (2 un) (9€ Auchan)`**, and stores direct store links.
- **Resilient Native Home Assistant AI + External AI Agents:**
  - Works out of the box with any Home Assistant `ai_task.*` or `conversation.*` entity (Google Generative AI, OpenAI, Anthropic, Ollama, etc.).
  - Two-stage structured + JSON fallback, generous timeouts (60s cloud / 90s local LLMs), primary + fallback AI redundancy, and full diagnostic logging in Home Assistant logs.
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

### One-Click (My Home Assistant)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pleote-dev&repository=plan-my-meals&category=integration)

### Manual HACS Setup

1. Open **HACS** → **Integrations** → menu (`⋮`) → **Custom repositories**.
2. Add `https://github.com/pleote-dev/plan-my-meals` with category **Integration**.
3. Search for **Plan My Meals** and click **Download**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration → Plan My Meals** and configure your shopping list (`todo.*`), servings, kitchen appliances, AI entity, and supermarkets.

---

## User Guide

1. **Weekly Planner (`Weekly Plan` tab):**
   - Click **Generate Week** to fill unlocked slots using your ratings (80% 4–5★ favorites, 20% new/unrated).
   - Use the **lock** button on any meal to keep it fixed across regenerations, or click a meal to swap it, pick another dish, or view its full cooking guide.
   - Adjust the **servings counter** in the top bar to scale all ingredient quantities automatically.
2. **Recipe Library, Editing & Safe Deletion (`Recipes` tab):**
   - Browse **Main Meals**, **Breakfasts**, and **Desserts** (60 copyright-free starter recipes included), rate dishes (1–5★), and create linked **variants** via the corner fold button.
   - Click **Edit** on any recipe card to update ingredients, equipment, steps, nutrition, or cover photo — or use **✨ Suggest with AI** to auto-complete fields.
   - **Deleting a recipe:** to prevent accidental deletions, the **Delete** button is intentionally kept **inside the Edit Recipe dialog** (bottom-left) and always prompts for confirmation before removing the recipe and its linked variants.
3. **Shopping List & Live Ingredient Prices (`Shopping & HA` tab):**
   - Ingredients from the weekly plan are grouped by supermarket aisle and synced directly to your configured Home Assistant `todo.*` list.
   - **Hover or click any ingredient** (in the Shopping List or inside Recipe Details) to open the floating price card showing the **best price**, **pack unit** (e.g. `1 kg`, `500 g`, `1 L`), **price per unit** (`€/kg`, `€/L`, `€/un`), average price, and a full supermarket comparison with direct store links.
   - Open **Shopping → Options** to toggle quantities/prices in `todo.*`, switch AI fallback mode, or run **Run search now**.
4. **Language:**
   - Plan My Meals automatically follows your **Home Assistant user language** (Portuguese when HA is set to Portuguese; English when HA is set to English or any unsupported language).

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
| `plan_my_meals.generate_recipe_ai` | Generates or completes a recipe via HA AI with structured/JSON fallback & logging |
| `plan_my_meals.upload_image` | Saves base64 or downloads image URL locally |
| `plan_my_meals.sync_shopping_list` | Pushes missing ingredients (`Ovomaltine (2 un) (9€ Auchan)`) to `todo.*` |
| `plan_my_meals.refresh_prices` | Refreshes supermarket prices for weekly ingredients (or all recipes) |
| `plan_my_meals.set_ingredient_price` | Manually sets or overrides a supermarket price & store URL |

---

## Daily Supermarket Price Refresh Automation

You can schedule Home Assistant to refresh supermarket prices once a day automatically. The timestamp of the last run and the number of prices fetched are displayed inside the **Shopping → Options** menu in the Plan My Meals UI (along with a **Run Now** button and AI search mode toggle).

Add the following automation to your Home Assistant `automations.yaml` (or create it via **Settings → Automations & Scenes**):

```yaml
alias: "Plan My Meals - Daily Supermarket Price Refresh"
description: "Refresh local supermarket prices for weekly meal plan ingredients once a day"
mode: single
triggers:
  - trigger: time
    at: "07:00:00"
conditions: []
actions:
  - action: plan_my_meals.refresh_prices
    data:
      all_recipes: false
      max_items: 25
```

- Set `all_recipes: true` if you want to refresh prices across your entire recipe library instead of just the current weekly plan.
- You can optionally pass `use_ai: true` (or `false`) to override the AI-assisted price lookup mode configured in **Shopping → Options**.

---

## Translations & Adding a New Language

Plan My Meals is designed to be easily translated into any language:

1. **Web App UI:**
   - Copy `custom_components/plan_my_meals/frontend/locales/en.json` to `<lang>.json` (e.g. `es.json`, `fr.json`, `de.json`) and translate the string values (keep `{placeholders}` intact).
   - Register the new language in `custom_components/plan_my_meals/frontend/locales/index.json`.
   - Any missing key automatically falls back to English.
2. **Home Assistant Config Flow & Entities:**
   - Copy `custom_components/plan_my_meals/translations/en.json` to `custom_components/plan_my_meals/translations/<lang>.json` and translate the labels.
3. Open a Pull Request — contributions are very welcome!
