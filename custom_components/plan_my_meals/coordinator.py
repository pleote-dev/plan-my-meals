"""DataUpdateCoordinator for Plan My Meals."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BASE_SERVINGS,
    CONF_COUNTRY,
    CONF_CURRENCY,
    CONF_INCLUDE_PRICE,
    CONF_INCLUDE_QTY,
    CONF_PRICE_TRACKING,
    CONF_PRICE_TTL_DAYS,
    CONF_SUPERMARKETS,
    CONF_TODO_ENTITY,
    DEFAULT_BASE_SERVINGS,
    DEFAULT_COUNTRY,
    DEFAULT_CURRENCY,
    DEFAULT_PRICE_TTL_DAYS,
    DEFAULT_SUPERMARKETS_PT,
    DEFAULT_TODO_ENTITY,
    DOMAIN,
)
from .database import PlanMyMealsDB
from .prices import normalize_text, search_supermarkets

_LOGGER = logging.getLogger(__name__)


class PlanMyMealsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinates state, missing ingredients, and supermarket price updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, db: PlanMyMealsDB) -> None:
        self.entry = entry
        self.db = db
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=15),
        )

    @property
    def cfg(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    async def _async_get_todo_summaries(self) -> list[str]:
        todo_entity = self.cfg.get(CONF_TODO_ENTITY) or DEFAULT_TODO_ENTITY
        if not todo_entity or not self.hass.states.get(todo_entity):
            return []
        try:
            resp = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": todo_entity, "status": ["needs_action"]},
                blocking=True,
                return_response=True,
            )
            items = ((resp or {}).get(todo_entity) or {}).get("items") or []
            return [str(i.get("summary") or "") for i in items if i.get("summary")]
        except Exception as exc:
            _LOGGER.debug("Could not read %s: %s", todo_entity, exc)
            return []

    async def _async_update_data(self) -> dict[str, Any]:
        cfg = self.cfg
        ttl = int(cfg.get(CONF_PRICE_TTL_DAYS) or DEFAULT_PRICE_TTL_DAYS)
        currency = str(cfg.get(CONF_CURRENCY) or DEFAULT_CURRENCY)
        todo_items = await self._async_get_todo_summaries()

        def _read() -> dict[str, Any]:
            state = self.db.get_state(ttl_days=ttl, currency=currency)
            inc_qty = state.get("includeQtyInHA")
            if inc_qty is None:
                inc_qty = bool(cfg.get(CONF_INCLUDE_QTY, True))
            inc_price = state.get("includePriceInHA")
            if inc_price is None:
                inc_price = bool(cfg.get(CONF_INCLUDE_PRICE, True))
            ingredients = self.db.aggregate_ingredients(
                todo_items,
                base_servings=int(cfg.get(CONF_BASE_SERVINGS) or DEFAULT_BASE_SERVINGS),
                currency=currency,
                include_qty=bool(inc_qty),
                include_price=bool(inc_price),
                ttl_days=ttl,
            )
            return {
                "state": state,
                "ingredients": ingredients,
                "missing": [i for i in ingredients if i["missing"]],
                "costs": state.get("costSummary") or {},
            }

        return await self.hass.async_add_executor_job(_read)

    async def _async_ai_estimate_prices(
        self,
        terms: list[str],
        country: str,
        enabled_supermarkets: list[str],
    ) -> int:
        """Use a configured/available HA ai_task entity to estimate local supermarket prices."""
        if not terms:
            return 0
        from .const import CONF_AI_ENTITY, SUPERMARKETS_BY_COUNTRY

        cfg_ai = str(self.cfg.get(CONF_AI_ENTITY) or "").strip()
        candidates: list[str] = []
        if cfg_ai and self.hass.states.get(cfg_ai):
            candidates.append(cfg_ai)
        for st in self.hass.states.async_all("ai_task"):
            if st.entity_id not in candidates:
                candidates.append(st.entity_id)
        if not candidates:
            return 0

        catalog = SUPERMARKETS_BY_COUNTRY.get(country, SUPERMARKETS_BY_COUNTRY["PT"])
        stores_desc = ", ".join(f"{catalog.get(d, d)} ({d})" for d in enabled_supermarkets)
        instructions = (
            f"Estimate current typical lowest retail supermarket prices in {country} (EUR) for these grocery items: "
            f"{', '.join(terms)}. Choose the most competitive store from: {stores_desc}. "
            "Return JSON in the 'prices_json' field as a list of objects: "
            '[{"ingredient": "...", "store_domain": "continente.pt", "supermarket": "Continente", "price": 2.49}].'
        )
        structure = {
            "prices_json": {
                "description": "JSON array of objects with ingredient, store_domain, supermarket, and numeric price in EUR",
                "required": True,
                "selector": {"text": {}},
            }
        }
        import json as _json

        for entity_id in candidates:
            try:
                resp = await self.hass.services.async_call(
                    "ai_task",
                    "generate_data",
                    {
                        "entity_id": entity_id,
                        "task_name": "Plan My Meals Supermarket Prices",
                        "instructions": instructions,
                        "structure": structure,
                    },
                    blocking=True,
                    return_response=True,
                )
                data = (resp or {}).get("data") or resp or {}
                raw_json = str(data.get("prices_json") or "").strip()
                if not raw_json:
                    continue
                start = raw_json.find("[")
                end = raw_json.rfind("]")
                if start >= 0 and end > start:
                    raw_json = raw_json[start : end + 1]
                parsed = _json.loads(raw_json)
                if not isinstance(parsed, list):
                    continue
                saved = 0
                for row in parsed:
                    if not isinstance(row, dict):
                        continue
                    ing = str(row.get("ingredient") or "").strip()
                    dom = str(row.get("store_domain") or "").strip().lower()
                    store = str(row.get("supermarket") or catalog.get(dom, dom)).strip()
                    try:
                        price = float(row.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if not ing or price <= 0 or price > 500:
                        continue
                    if not dom:
                        dom = enabled_supermarkets[0] if enabled_supermarkets else "continente.pt"
                    await self.hass.async_add_executor_job(
                        self.db.upsert_supermarket_price,
                        ing,
                        store or dom,
                        dom,
                        price,
                        f"{ing} (IA)",
                        "",
                    )
                    saved += 1
                if saved:
                    return saved
            except Exception as exc:
                _LOGGER.debug("AI price estimation failed on %s: %s", entity_id, exc)
        return 0

    async def async_refresh_prices(
        self,
        *,
        all_recipes: bool = False,
        max_items: int = 20,
        use_ai: bool | None = None,
        updated_by: str = "Home Assistant",
    ) -> dict[str, Any]:
        """Fetch live supermarket prices for ingredients in the weekly plan (or all recipes)."""
        cfg = self.cfg
        if not cfg.get(CONF_PRICE_TRACKING, True):
            return {"ok": False, "error": "Price tracking is disabled in options."}

        state = await self.hass.async_add_executor_job(self.db.get_state)
        ai_enabled = (state.get("priceSearchMode", "ai") == "ai") if use_ai is None else bool(use_ai)
        terms: list[str] = []
        seen: set[str] = set()
        sources = (
            list(state.get("recipes") or [])
            if all_recipes
            else [
                (d.get(k) or {})
                for d in (state.get("weeklyPlan") or [])
                for k in ("lunch", "dinner")
            ]
        )
        for meal in sources:
            for raw in (meal.get("items") or []):
                name = raw.strip() if isinstance(raw, str) else str((raw or {}).get("name") or "").strip()
                nk = normalize_text(name)
                if nk and nk not in seen:
                    seen.add(nk)
                    terms.append(name)

        session = async_get_clientsession(self.hass)
        country = str(cfg.get(CONF_COUNTRY) or DEFAULT_COUNTRY)
        enabled = list(cfg.get(CONF_SUPERMARKETS) or DEFAULT_SUPERMARKETS_PT)
        target_terms = terms[: max(1, max_items)]
        updated = 0
        priced = 0
        missing_for_ai: list[str] = []
        for term in target_terms:
            offers = await search_supermarkets(
                term,
                session=session,
                country=country,
                enabled_supermarkets=enabled,
            )
            updated += 1
            if offers:
                priced += 1
                for of in offers:
                    await self.hass.async_add_executor_job(
                        self.db.upsert_supermarket_price,
                        term,
                        of["supermarket"],
                        of["store_domain"],
                        of["price"],
                        of["title"],
                        of.get("url", ""),
                    )
            else:
                missing_for_ai.append(term)

        if ai_enabled and missing_for_ai:
            ai_saved = await self._async_ai_estimate_prices(missing_for_ai, country, enabled)
            priced += ai_saved

        mode = "ai" if ai_enabled else "supermarkets"
        meta = await self.hass.async_add_executor_job(
            self.db.record_price_refresh,
            updated,
            priced,
            mode,
            updated_by,
        )
        await self.async_request_refresh()
        return {"ok": True, "searched": updated, "priced": priced, "mode": mode, "meta": meta}

    async def async_sync_shopping_list(self, *, refresh_prices: bool = False) -> dict[str, Any]:
        """Push missing ingredients to the configured HA todo entity with qty + best price/store."""
        if refresh_prices:
            await self.async_refresh_prices(all_recipes=False, max_items=15)
        await self.async_request_refresh()
        data = self.data or await self._async_update_data()
        todo_entity = self.cfg.get(CONF_TODO_ENTITY) or DEFAULT_TODO_ENTITY
        added: list[str] = []
        for item in data.get("missing") or []:
            await self.hass.services.async_call(
                "todo",
                "add_item",
                {"entity_id": todo_entity, "item": item["ha_text"]},
                blocking=True,
            )
            added.append(item["ha_text"])
        await self.async_request_refresh()
        return {"ok": True, "todo_entity": todo_entity, "added": added, "total": len(added)}
