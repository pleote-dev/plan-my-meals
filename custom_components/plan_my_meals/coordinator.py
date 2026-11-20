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
            ingredients = self.db.aggregate_ingredients(
                todo_items,
                base_servings=int(cfg.get(CONF_BASE_SERVINGS) or DEFAULT_BASE_SERVINGS),
                currency=currency,
                include_qty=bool(cfg.get(CONF_INCLUDE_QTY, True)),
                include_price=bool(cfg.get(CONF_INCLUDE_PRICE, True)),
                ttl_days=ttl,
            )
            return {
                "state": state,
                "ingredients": ingredients,
                "missing": [i for i in ingredients if i["missing"]],
                "costs": state.get("costSummary") or {},
            }

        return await self.hass.async_add_executor_job(_read)

    async def async_refresh_prices(self, *, all_recipes: bool = False, max_items: int = 20) -> dict[str, Any]:
        """Fetch live supermarket prices for ingredients in the weekly plan (or all recipes)."""
        cfg = self.cfg
        if not cfg.get(CONF_PRICE_TRACKING, True):
            return {"ok": False, "error": "Price tracking is disabled in options."}

        state = await self.hass.async_add_executor_job(self.db.get_state)
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
        updated = 0
        priced = 0
        for term in terms[: max(1, max_items)]:
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

        await self.async_request_refresh()
        return {"ok": True, "searched": updated, "priced": priced}

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
