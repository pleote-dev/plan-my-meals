"""SQLite database and domain logic for Plan My Meals."""

from __future__ import annotations

import difflib
import json
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .const import (
    DAYS,
    DAYS_SHORT,
    DEFAULT_APPLIANCES,
    DEFAULT_BASE_SERVINGS,
    DEFAULT_CURRENCY,
    DEFAULT_PRICE_TTL_DAYS,
    DEFAULT_SERVINGS,
)
from .prices import format_shopping_item, normalize_text, summarize_offers

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS state_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supermarket_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_norm TEXT NOT NULL,
    term TEXT NOT NULL,
    supermarket TEXT NOT NULL,
    store_domain TEXT NOT NULL,
    title TEXT NOT NULL,
    price REAL NOT NULL,
    unit TEXT DEFAULT '',
    unit_price TEXT DEFAULT '',
    url TEXT DEFAULT '',
    fetched_at TEXT NOT NULL,
    UNIQUE (term_norm, store_domain)
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _format_qty(qty: float | None, unit: str) -> str:
    if qty is None:
        return ""
    if unit == "g":
        if qty >= 1000:
            kg = round(qty / 1000.0, 2)
            return f"{int(kg) if kg.is_integer() else kg} kg"
        return f"{round(qty)} g"
    if unit == "ml":
        if qty >= 1000:
            lit = round(qty / 1000.0, 2)
            return f"{int(lit) if lit.is_integer() else lit} L"
        return f"{round(qty)} ml"
    rounded = round(qty * 2) / 2
    num = str(int(rounded)) if rounded.is_integer() else str(rounded).replace(".", ",")
    plurals = {"lata": "latas", "dente": "dentes", "maço": "maços", "ramo": "ramos"}
    if unit in plurals:
        return f"{num} {unit if rounded == 1 else plurals[unit]}"
    return f"{num} {unit}".strip()


def normalize_kitchen(
    kitchen: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize kitchen equipment and migrate legacy bimbyMode/bimbyFriend flags."""
    raw = dict(kitchen or {})
    cfg = config or {}
    appliances_src = raw.get("appliances")
    if not isinstance(appliances_src, list):
        appliances_src = list(cfg.get("appliances", DEFAULT_APPLIANCES))
    appliances: list[str] = []
    for item in appliances_src:
        s = str(item or "").strip()
        if s and s not in appliances:
            appliances.append(s)

    accessories_raw = raw.get("accessories")
    if not isinstance(accessories_raw, dict):
        accessories_raw = dict(cfg.get("accessories") or {})
    accessories: dict[str, list[str]] = {}
    for app_id, acc_list in accessories_raw.items():
        aid = str(app_id or "").strip()
        if not aid or not isinstance(acc_list, list):
            continue
        cleaned = []
        for acc in acc_list:
            s = str(acc or "").strip()
            if s and s not in cleaned:
                cleaned.append(s)
        if cleaned:
            accessories[aid] = cleaned

    # Migrate legacy bimbyMode / bimbyFriend flags seamlessly
    if (raw.get("bimbyMode") or cfg.get("bimby_mode")) and "bimby" not in appliances:
        appliances.append("bimby")
    if (raw.get("bimbyFriend") or cfg.get("bimby_friend")) and "bimby" in appliances:
        bimby_acc = list(accessories.get("bimby") or [])
        if "bimby_friend" not in bimby_acc:
            bimby_acc.append("bimby_friend")
        accessories["bimby"] = bimby_acc

    custom_appliances = raw.get("customAppliances") if isinstance(raw.get("customAppliances"), list) else []
    custom_accessories = raw.get("customAccessories") if isinstance(raw.get("customAccessories"), dict) else {}

    return {
        "appliances": appliances,
        "accessories": accessories,
        "customAppliances": custom_appliances,
        "customAccessories": custom_accessories,
    }


def _default_state(starter_recipes: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    main_meals = [r for r in starter_recipes if (r.get("meal_type") or "refeicao") == "refeicao"]
    plan = []
    idx = 0
    for day in DAYS:
        lunch = dict(main_meals[idx % len(main_meals)]) if main_meals else {"id": "", "name": "—", "items": []}
        idx += 1
        dinner = dict(main_meals[idx % len(main_meals)]) if main_meals else {"id": "", "name": "—", "items": []}
        idx += 1
        lunch["locked"] = False
        dinner["locked"] = False
        plan.append({"day": day, "lunch": lunch, "dinner": dinner})
    return {
        "version": 5,
        "updated_at": utc_now_iso(),
        "updated_by": "Plan My Meals",
        "servings": int(cfg.get("servings", DEFAULT_SERVINGS)),
        "includeQtyInHA": bool(cfg.get("include_qty_in_todo", True)),
        "includePriceInHA": bool(cfg.get("include_price_in_todo", True)),
        "priceSearchMode": "ai",
        "priceRefreshMeta": {},
        "mealConfig": {
            "breakfast": True,
            "lunch": True,
            "lunchDessert": True,
            "dinner": True,
            "dinnerDessert": True,
        },
        "weeklyPlan": plan,
        "weeks": {},
        "pantry": [],
        "kitchen": normalize_kitchen(None, config=cfg),
        "recipes": starter_recipes,
        "customRecipes": [],
        "recipeRatings": {},
        "mealHistoryStats": {},
        "recipeGuides": {},
        "ingredientPrices": {},
    }


class PlanMyMealsDB:
    """Thread-safe SQLite store for Plan My Meals."""

    def __init__(
        self,
        db_path: Path,
        starter_recipes_path: Path | None = None,
        legacy_state_path: Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.starter_recipes_path = starter_recipes_path or (
            Path(__file__).resolve().parent / "data" / "starter_recipes.json"
        )
        self.legacy_state_path = legacy_state_path
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(supermarket_prices)").fetchall()
            }
            if "unit" not in cols:
                self._conn.execute("ALTER TABLE supermarket_prices ADD COLUMN unit TEXT DEFAULT ''")
            if "unit_price" not in cols:
                self._conn.execute("ALTER TABLE supermarket_prices ADD COLUMN unit_price TEXT DEFAULT ''")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _load_starter_recipes(self) -> list[dict[str, Any]]:
        if self.starter_recipes_path and self.starter_recipes_path.exists():
            try:
                data = json.loads(self.starter_recipes_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except ValueError:
                pass
        return []

    def _backfill_starter_recipes(self, state: dict[str, Any]) -> bool:
        """Ensure starter recipes from starter_recipes.json exist unless explicitly deleted by the user."""
        starter = self._load_starter_recipes()
        if not starter:
            return False
        existing = list(state.get("recipes") or [])
        existing_ids = {str(r.get("id") or "") for r in existing if isinstance(r, dict)}
        deleted_ids = {str(x) for x in (state.get("deletedStarterIds") or [])}
        added = 0
        for rec in starter:
            rid = str(rec.get("id") or "")
            if rid and rid not in existing_ids and rid not in deleted_ids:
                existing.append(dict(rec))
                existing_ids.add(rid)
                added += 1
        if added:
            state["recipes"] = existing
            return True
        return False

    def initialize(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ensure state exists: migrate legacy JSON if present, otherwise seed starter recipes."""
        with self._lock:
            row = self._conn.execute("SELECT value FROM state_kv WHERE key = 'main'").fetchone()
            if row:
                state = json.loads(row["value"])
                state["kitchen"] = normalize_kitchen(state.get("kitchen"), config=config)
                if self._backfill_starter_recipes(state):
                    state["updated_at"] = utc_now_iso()
                    self._save_raw(state)
                return state

            # One-time automatic migration from legacy Pyscript /local/plan_my_meals_state.json
            if self.legacy_state_path and self.legacy_state_path.exists():
                try:
                    legacy = json.loads(self.legacy_state_path.read_text(encoding="utf-8"))
                    if isinstance(legacy, dict) and legacy.get("recipes"):
                        legacy.setdefault("ingredientPrices", {})
                        legacy["kitchen"] = normalize_kitchen(legacy.get("kitchen"), config=config)
                        legacy["migrated_from_legacy"] = True
                        self._backfill_starter_recipes(legacy)
                        self._save_raw(legacy)
                        return legacy
                except (OSError, ValueError):
                    pass

            starter = self._load_starter_recipes()
            state = _default_state(starter, config=config)
            self._save_raw(state)
            return state

    def _save_raw(self, state: dict[str, Any]) -> None:
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO state_kv (key, value, updated_at) VALUES ('main', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (json.dumps(state, ensure_ascii=False), now),
        )
        self._conn.commit()

    def get_price_stats(self, ttl_days: int = DEFAULT_PRICE_TTL_DAYS) -> dict[str, Any]:
        sql = "SELECT COUNT(DISTINCT term_norm) AS items, COUNT(*) AS offers, MAX(fetched_at) AS last_fetched FROM supermarket_prices"
        params: list[Any] = []
        if ttl_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).replace(microsecond=0).isoformat()
            sql += " WHERE fetched_at >= ?"
            params.append(cutoff)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            if not row:
                return {"total_priced_items": 0, "total_offers": 0, "last_fetched_at": None}
            return {
                "total_priced_items": int(row["items"] or 0),
                "total_offers": int(row["offers"] or 0),
                "last_fetched_at": row["last_fetched"],
            }

    def record_price_refresh(
        self,
        searched: int,
        priced: int,
        mode: str = "supermarkets",
        updated_by: str = "Automation",
    ) -> dict[str, Any]:
        with self._lock:
            state = self.get_state()
            stats = self.get_price_stats()
            meta = {
                "last_run_at": utc_now_iso(),
                "searched": int(searched),
                "priced": int(priced),
                "mode": str(mode or "supermarkets"),
                "updated_by": str(updated_by or "Automation"),
                "total_priced_items": stats["total_priced_items"],
                "total_offers": stats["total_offers"],
            }
            state["priceRefreshMeta"] = meta
            self.save_state(state, updated_by=updated_by)
            return meta

    def get_state(
        self,
        ttl_days: int = DEFAULT_PRICE_TTL_DAYS,
        currency: str = DEFAULT_CURRENCY,
    ) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state_kv WHERE key = 'main'").fetchone()
            state = json.loads(row["value"]) if row else self.initialize()
            state["kitchen"] = normalize_kitchen(state.get("kitchen"))
            # Merge live supermarket price summaries into state
            prices = self.get_all_price_summaries(ttl_days=ttl_days, currency=currency)
            merged_prices = dict(state.get("ingredientPrices") or {})
            merged_prices.update(prices)
            state["ingredientPrices"] = merged_prices
            costs = self.compute_meal_costs(state, merged_prices)
            state["costSummary"] = costs
            stats = self.get_price_stats(ttl_days=ttl_days)
            meta = dict(state.get("priceRefreshMeta") or {})
            meta["total_priced_items"] = stats["total_priced_items"]
            meta["total_offers"] = stats["total_offers"]
            if not meta.get("last_run_at") and stats.get("last_fetched_at"):
                meta["last_run_at"] = stats["last_fetched_at"]
            state["priceRefreshMeta"] = meta
            return state

    def save_state(self, state: dict[str, Any], updated_by: str = "Home Assistant") -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state_kv WHERE key = 'main'").fetchone()
            prev = json.loads(row["value"]) if row else {}
            merged = {**prev, **state}
            # Never wipe existing recipes if an incoming payload omits them
            if not merged.get("recipes") and prev.get("recipes"):
                merged["recipes"] = list(prev["recipes"])
            # Ensure any customRecipes sent by the client are also present in recipes
            if isinstance(merged.get("customRecipes"), list) and merged["customRecipes"]:
                by_id = {r.get("id"): r for r in (merged.get("recipes") or []) if isinstance(r, dict) and r.get("id")}
                for cr in merged["customRecipes"]:
                    if isinstance(cr, dict) and cr.get("id"):
                        by_id[cr["id"]] = cr
                merged["recipes"] = list(by_id.values())
            merged["kitchen"] = normalize_kitchen(merged.get("kitchen"))
            merged["updated_at"] = utc_now_iso()
            merged["updated_by"] = updated_by or merged.get("updated_by") or "Home Assistant"
            self._save_raw(merged)
            return merged

    # ------------------------------------------------------------------ Recipes

    def check_similarity(
        self,
        title: str,
        items: list[dict[str, Any]] | None = None,
        meal_type: str = "",
    ) -> dict[str, Any]:
        state = self.get_state()
        recipes = list(state.get("recipes") or [])
        q_title = normalize_text(title)
        q_ings = {normalize_text(i.get("name", "") if isinstance(i, dict) else str(i)) for i in (items or [])}
        q_ings.discard("")

        best_match: dict[str, Any] | None = None
        best_score = 0.0
        for rec in recipes:
            if meal_type and rec.get("meal_type") and rec.get("meal_type") != meal_type:
                continue
            r_title = normalize_text(rec.get("name", ""))
            title_sim = difflib.SequenceMatcher(None, q_title, r_title).ratio() if q_title and r_title else 0.0
            r_ings = {
                normalize_text(i.get("name", "") if isinstance(i, dict) else str(i))
                for i in (rec.get("items") or [])
            }
            r_ings.discard("")
            ing_sim = (len(q_ings & r_ings) / len(q_ings | r_ings)) if (q_ings and r_ings) else 0.0
            score = 0.65 * title_sim + 0.35 * ing_sim
            if score > best_score:
                best_score = score
                best_match = rec

        if best_match and best_score >= 0.85:
            status = "duplicate"
        elif best_match and best_score >= 0.55:
            status = "variant_candidate"
        else:
            status = "new"
        match_obj = {"id": best_match["id"], "name": best_match["name"]} if best_match and status != "new" else None
        parent_id = (best_match.get("parent_recipe_id") or best_match["id"]) if best_match and status != "new" else None
        parent_name = best_match["name"] if best_match and status != "new" else None
        return {
            "status": status,
            "score": round(best_score, 3),
            "match": match_obj,
            "parent_id": parent_id,
            "parent_name": parent_name,
            "suggested_variant_name": f"Alternativa ({title.strip()})" if title.strip() and status != "new" else "Variante Personalizada",
        }

    def upsert_recipe(self, recipe_data: dict[str, Any], updated_by: str = "Home Assistant") -> dict[str, Any]:
        with self._lock:
            state = self.get_state()
            recipes = list(state.get("recipes") or [])
            rid = str(recipe_data.get("id") or "").strip() or f"c-{int(time.time() * 1000)}"
            now = utc_now_iso()
            existing_idx = next((i for i, r in enumerate(recipes) if r.get("id") == rid), None)
            existing = recipes[existing_idx] if existing_idx is not None else {}

            raw_appliances = recipe_data.get("appliances") if recipe_data.get("appliances") is not None else existing.get("appliances", [])
            appliances = [str(a).strip() for a in (raw_appliances or []) if str(a).strip()]
            raw_accessories = recipe_data.get("accessories") if recipe_data.get("accessories") is not None else existing.get("accessories", {})
            accessories: dict[str, list[str]] = {}
            if isinstance(raw_accessories, dict):
                for app_id, acc_list in raw_accessories.items():
                    aid = str(app_id or "").strip()
                    if aid and isinstance(acc_list, list):
                        cleaned = [str(x).strip() for x in acc_list if str(x).strip()]
                        if cleaned:
                            accessories[aid] = cleaned

            merged = {
                "id": rid,
                "name": str(recipe_data.get("name") or existing.get("name") or "Sem nome").strip(),
                "meal_type": recipe_data.get("meal_type") or existing.get("meal_type") or "refeicao",
                "category": recipe_data.get("category") or existing.get("category") or "Rápido",
                "cuisine": recipe_data.get("cuisine") or existing.get("cuisine") or "Portuguesa",
                "time": recipe_data.get("time") or existing.get("time") or "25 min",
                "prepTime": recipe_data.get("prepTime") or recipe_data.get("prep_time") or existing.get("prepTime") or "",
                "cookTime": recipe_data.get("cookTime") or recipe_data.get("cook_time") or existing.get("cookTime") or "",
                "method": recipe_data.get("method") if recipe_data.get("method") is not None else existing.get("method", ""),
                "appliances": appliances,
                "accessories": accessories,
                "steps": recipe_data.get("steps") if recipe_data.get("steps") is not None else existing.get("steps", ""),
                "items": recipe_data.get("items") if recipe_data.get("items") is not None else existing.get("items", []),
                "nutrition": recipe_data.get("nutrition") if recipe_data.get("nutrition") is not None else existing.get("nutrition", {}),
                "parent_recipe_id": recipe_data.get("parent_recipe_id", existing.get("parent_recipe_id")),
                "variant_name": recipe_data.get("variant_name", existing.get("variant_name")),
                "rating": recipe_data.get("rating", existing.get("rating")),
                "image_url": recipe_data.get("image_url") if recipe_data.get("image_url") is not None else existing.get("image_url", ""),
                "source": recipe_data.get("source") or existing.get("source") or "app",
                "created_by": recipe_data.get("created_by") or existing.get("created_by") or updated_by,
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
            }
            if existing_idx is not None:
                recipes[existing_idx] = merged
            else:
                recipes.append(merged)
            state["recipes"] = recipes
            state["customRecipes"] = [r for r in recipes if r.get("source") not in ("default", "starter")]
            if merged.get("rating") is not None:
                ratings = dict(state.get("recipeRatings") or {})
                ratings[rid] = merged["rating"]
                state["recipeRatings"] = ratings
            self.save_state(state, updated_by=updated_by)
            return {"ok": True, "recipe": merged}

    def delete_recipe(self, recipe_id: str, updated_by: str = "Home Assistant") -> dict[str, Any]:
        with self._lock:
            state = self.get_state()
            before = len(state.get("recipes") or [])
            recipes = [
                r for r in (state.get("recipes") or [])
                if r.get("id") != recipe_id and r.get("parent_recipe_id") != recipe_id
            ]
            state["recipes"] = recipes
            state["customRecipes"] = [r for r in recipes if r.get("source") not in ("default", "starter")]
            starter_ids = {str(r.get("id") or "") for r in self._load_starter_recipes()}
            if recipe_id in starter_ids:
                deleted = list(state.get("deletedStarterIds") or [])
                if recipe_id not in deleted:
                    deleted.append(recipe_id)
                state["deletedStarterIds"] = deleted
            self.save_state(state, updated_by=updated_by)
            return {"ok": True, "deleted": before - len(recipes)}

    def rate_recipe(self, recipe_id: str, rating: int, updated_by: str = "Home Assistant") -> dict[str, Any]:
        with self._lock:
            state = self.get_state()
            val = int(rating) if rating and int(rating) > 0 else None
            ratings = dict(state.get("recipeRatings") or {})
            if val is None:
                ratings.pop(recipe_id, None)
            else:
                ratings[recipe_id] = max(1, min(5, val))
            state["recipeRatings"] = ratings
            for r in state.get("recipes") or []:
                if r.get("id") == recipe_id:
                    r["rating"] = ratings.get(recipe_id)
            for d in state.get("weeklyPlan") or []:
                for k in ("lunch", "dinner"):
                    if (d.get(k) or {}).get("id") == recipe_id:
                        d[k]["rating"] = ratings.get(recipe_id)
            self.save_state(state, updated_by=updated_by)
            return {"ok": True, "recipe_id": recipe_id, "rating": ratings.get(recipe_id)}

    def update_recipe_image(self, recipe_id: str, image_url: str, updated_by: str = "Home Assistant") -> dict[str, Any]:
        with self._lock:
            state = self.get_state()
            if recipe_id:
                for r in state.get("recipes") or []:
                    if r.get("id") == recipe_id:
                        r["image_url"] = image_url
                for d in state.get("weeklyPlan") or []:
                    for k in ("lunch", "dinner"):
                        if (d.get(k) or {}).get("id") == recipe_id:
                            d[k]["image_url"] = image_url
                self.save_state(state, updated_by=updated_by)
            return {"ok": True, "recipe_id": recipe_id, "image_url": image_url}

    # ------------------------------------------------------------------ Weekly Plan

    def generate_week(self, updated_by: str = "Home Assistant") -> dict[str, Any]:
        with self._lock:
            state = self.get_state()
            recipes = [r for r in (state.get("recipes") or []) if (r.get("meal_type") or "refeicao") == "refeicao"]
            if not recipes:
                recipes = list(state.get("recipes") or [])
            if not recipes:
                return {"ok": False, "error": "No recipes available"}

            plan = list(state.get("weeklyPlan") or [])
            used = {
                d[k]["id"]
                for d in plan
                for k in ("lunch", "dinner")
                if (d.get(k) or {}).get("locked") and (d.get(k) or {}).get("id")
            }

            def _pick(avoid_cat: str | None) -> dict[str, Any]:
                eligible = [r for r in recipes if r.get("rating") is None or int(r.get("rating")) >= 4]
                source = eligible or recipes

                def _filt(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
                    p = [r for r in pool if r["id"] not in used and r.get("category") != avoid_cat]
                    if not p:
                        p = [r for r in pool if r["id"] not in used]
                    if not p:
                        p = [r for r in pool if r.get("category") != avoid_cat]
                    return p or pool

                favs = _filt([r for r in source if (r.get("rating") or 0) >= 4])
                unrated = _filt([r for r in source if r.get("rating") is None])
                if favs and unrated:
                    chosen = random.choice(favs) if random.random() < 0.8 else random.choice(unrated)
                elif favs:
                    chosen = random.choice(favs)
                elif unrated:
                    chosen = random.choice(unrated)
                else:
                    chosen = random.choice(_filt(source))
                out = dict(chosen)
                out["locked"] = False
                return out

            new_plan = []
            for idx, day in enumerate(DAYS):
                cur = plan[idx] if idx < len(plan) else {}
                lunch = dict(cur["lunch"]) if (cur.get("lunch") or {}).get("locked") else _pick(None)
                used.add(lunch.get("id", ""))
                dinner = dict(cur["dinner"]) if (cur.get("dinner") or {}).get("locked") else _pick(lunch.get("category"))
                used.add(dinner.get("id", ""))
                new_plan.append({"day": day, "lunch": lunch, "dinner": dinner})

            state["weeklyPlan"] = new_plan
            self.save_state(state, updated_by=updated_by)
            return {"ok": True, "weeklyPlan": new_plan}

    def swap_meal(self, day_index: int, meal_key: str, dish: str, updated_by: str = "Home Assistant") -> dict[str, Any]:
        with self._lock:
            state = self.get_state()
            plan = list(state.get("weeklyPlan") or [])
            if not (0 <= day_index < len(plan)):
                return {"ok": False, "error": f"Invalid day_index {day_index}"}
            q = normalize_text(dish)
            recipes = list(state.get("recipes") or [])
            matched = next((r for r in recipes if r.get("id") == dish or q in normalize_text(r.get("name", ""))), None)
            if not matched and recipes:
                names = [normalize_text(r.get("name", "")) for r in recipes]
                close = difflib.get_close_matches(q, names, n=1, cutoff=0.55)
                if close:
                    matched = recipes[names.index(close[0])]
            if matched:
                new_meal = dict(matched)
                new_meal["locked"] = True
            else:
                new_meal = {
                    "id": f"free-{int(time.time())}",
                    "name": dish.strip()[:1].upper() + dish.strip()[1:],
                    "time": "—",
                    "category": "Livre",
                    "items": [],
                    "locked": True,
                }
            plan[day_index][meal_key] = new_meal
            state["weeklyPlan"] = plan
            self.save_state(state, updated_by=updated_by)
            return {"ok": True, "day": DAYS[day_index], "meal": meal_key, "dish": new_meal["name"]}

    # ------------------------------------------------------------------ Supermarket Prices

    def upsert_supermarket_price(
        self,
        term: str,
        supermarket: str,
        store_domain: str,
        price: float,
        title: str = "",
        url: str = "",
        unit: str = "",
        unit_price: str = "",
    ) -> dict[str, Any]:
        t_clean = str(term or "").strip()
        t_norm = normalize_text(t_clean)
        dom = store_domain.lower().strip()
        if dom.startswith("www."):
            dom = dom[4:]
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO supermarket_prices (term_norm, term, supermarket, store_domain, title, price, unit, unit_price, url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(term_norm, store_domain) DO UPDATE SET
                    term = excluded.term,
                    supermarket = excluded.supermarket,
                    title = excluded.title,
                    price = excluded.price,
                    unit = CASE WHEN excluded.unit != '' THEN excluded.unit ELSE supermarket_prices.unit END,
                    unit_price = CASE WHEN excluded.unit_price != '' THEN excluded.unit_price ELSE supermarket_prices.unit_price END,
                    url = CASE WHEN excluded.url != '' THEN excluded.url ELSE supermarket_prices.url END,
                    fetched_at = excluded.fetched_at
                """,
                (
                    t_norm,
                    t_clean,
                    supermarket.strip() or dom,
                    dom,
                    (title or t_clean)[:200],
                    round(float(price), 2),
                    str(unit or "").strip()[:40],
                    str(unit_price or "").strip()[:40],
                    url.strip(),
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM supermarket_prices WHERE term_norm = ? AND store_domain = ?",
                (t_norm, dom),
            ).fetchone()
            return dict(row) if row else {}

    def get_supermarket_prices(self, term: str, ttl_days: int = DEFAULT_PRICE_TTL_DAYS) -> list[dict[str, Any]]:
        t_norm = normalize_text(term)
        if not t_norm:
            return []
        sql = "SELECT * FROM supermarket_prices WHERE term_norm = ?"
        params: list[Any] = [t_norm]
        if ttl_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).replace(microsecond=0).isoformat()
            sql += " AND fetched_at >= ?"
            params.append(cutoff)
        sql += " ORDER BY price ASC, supermarket ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_all_price_summaries(
        self,
        ttl_days: int = DEFAULT_PRICE_TTL_DAYS,
        currency: str = DEFAULT_CURRENCY,
    ) -> dict[str, dict[str, Any]]:
        sql = "SELECT * FROM supermarket_prices"
        params: list[Any] = []
        if ttl_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).replace(microsecond=0).isoformat()
            sql += " WHERE fetched_at >= ?"
            params.append(cutoff)
        sql += " ORDER BY term_norm ASC, price ASC"
        with self._lock:
            rows = [dict(r) for r in self._conn.execute(sql, params).fetchall()]
        grouped: dict[str, list[dict[str, Any]]] = {}
        terms: dict[str, str] = {}
        for r in rows:
            grouped.setdefault(r["term_norm"], []).append(r)
            terms.setdefault(r["term_norm"], r["term"])
        return {
            tn: summarize_offers(terms[tn], offers, currency=currency)
            for tn, offers in grouped.items()
        }

    # ------------------------------------------------------------------ Aggregation & Costs

    def compute_meal_costs(
        self,
        state: dict[str, Any],
        price_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        servings = max(1, int(state.get("servings") or DEFAULT_SERVINGS))
        week_avg = 0.0
        week_min = 0.0
        any_priced = False
        daily: list[dict[str, Any]] = []

        for day_obj in state.get("weeklyPlan") or []:
            day_entry: dict[str, Any] = {"day": day_obj.get("day", "")}
            for key in ("lunch", "dinner"):
                meal = day_obj.get(key) or {}
                seen: set[str] = set()
                m_avg = 0.0
                m_min = 0.0
                priced = 0
                for raw in meal.get("items") or []:
                    name = raw.strip() if isinstance(raw, str) else str((raw or {}).get("name") or "").strip()
                    nk = normalize_text(name)
                    if not nk or nk in seen:
                        continue
                    seen.add(nk)
                    p = price_map.get(nk)
                    if p and p.get("avg_price") is not None:
                        m_avg += float(p["avg_price"])
                        m_min += float(p.get("min_price") or p["avg_price"])
                        priced += 1
                day_entry[f"{key}_avg_eur"] = round(m_avg, 2) if priced else None
                day_entry[f"{key}_min_eur"] = round(m_min, 2) if priced else None
                day_entry[f"{key}_priced"] = priced
                day_entry[f"{key}_total"] = len(seen)
                if priced:
                    week_avg += m_avg
                    week_min += m_min
                    any_priced = True
            daily.append(day_entry)

        return {
            "week_avg_eur": round(week_avg, 2) if any_priced else None,
            "week_min_eur": round(week_min, 2) if any_priced else None,
            "per_person_avg_eur": round(week_avg / servings, 2) if any_priced else None,
            "daily": daily,
        }

    def aggregate_ingredients(
        self,
        ha_todo_summaries: list[str] | None = None,
        *,
        base_servings: int = DEFAULT_BASE_SERVINGS,
        currency: str = DEFAULT_CURRENCY,
        include_qty: bool = True,
        include_price: bool = True,
        ttl_days: int = DEFAULT_PRICE_TTL_DAYS,
    ) -> list[dict[str, Any]]:
        state = self.get_state(ttl_days=ttl_days, currency=currency)
        servings = int(state.get("servings") or DEFAULT_SERVINGS)
        pantry = {normalize_text(x) for x in (state.get("pantry") or [])}
        ha_norms = [normalize_text(x) for x in (ha_todo_summaries or [])]
        price_map = state.get("ingredientPrices") or {}

        agg: dict[str, dict[str, Any]] = {}
        for idx, day_obj in enumerate(state.get("weeklyPlan") or []):
            for key in ("lunch", "dinner"):
                meal = day_obj.get(key) or {}
                for raw in meal.get("items") or []:
                    if isinstance(raw, str):
                        name, qty, unit = raw.strip(), None, ""
                    elif isinstance(raw, dict):
                        name = str(raw.get("name") or "").strip()
                        qty = raw.get("qty")
                        unit = str(raw.get("unit") or "").strip()
                    else:
                        continue
                    if not name:
                        continue
                    nk = normalize_text(name)
                    if nk not in agg:
                        agg[nk] = {"key": nk, "name": name, "units": {}, "days": []}
                    entry = agg[nk]
                    if idx < len(DAYS_SHORT) and DAYS_SHORT[idx] not in entry["days"]:
                        entry["days"].append(DAYS_SHORT[idx])
                    if isinstance(qty, (int, float)):
                        scaled = (float(qty) * servings) / max(1, base_servings)
                        u = unit or "un"
                        entry["units"][u] = entry["units"].get(u, 0.0) + scaled

        out: list[dict[str, Any]] = []
        for entry in sorted(agg.values(), key=lambda x: x["key"]):
            qparts = [_format_qty(tot, u) for u, tot in entry["units"].items()]
            qlabel = " + ".join(p for p in qparts if p)
            in_ha = any(h == entry["key"] or entry["key"] in h or h in entry["key"] for h in ha_norms if h)
            in_pantry = entry["key"] in pantry
            pinfo = price_map.get(entry["key"]) or {}
            min_price = pinfo.get("min_price")
            min_store = str(pinfo.get("min_store") or "")
            min_url = str(pinfo.get("min_url") or "")
            avg_price = pinfo.get("avg_price")
            ha_text = format_shopping_item(
                entry["name"],
                qty=qlabel,
                price=min_price,
                supermarket=min_store,
                currency=currency,
                include_qty=include_qty,
                include_price=include_price,
            )
            out.append({
                "name": entry["name"],
                "key": entry["key"],
                "qty": qlabel,
                "ha_text": ha_text,
                "min_price": min_price,
                "min_store": min_store,
                "min_url": min_url,
                "min_unit": str(pinfo.get("min_unit") or ""),
                "min_unit_price": str(pinfo.get("min_unit_price") or ""),
                "avg_price": avg_price,
                "tag": str(pinfo.get("tag") or ""),
                "offers": pinfo.get("offers") or [],
                "days": entry["days"],
                "in_ha": in_ha,
                "in_pantry": in_pantry,
                "missing": not in_ha and not in_pantry,
            })
        return out
