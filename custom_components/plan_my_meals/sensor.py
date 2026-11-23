"""Sensors exposed by Plan My Meals for use in any Home Assistant dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CURRENCY, DEFAULT_CURRENCY, DOMAIN, VERSION
from .coordinator import PlanMyMealsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(
        [
            MealTodaySensor(coord, entry, "lunch", "Lunch Today", "mdi:white-balance-sunny"),
            MealTodaySensor(coord, entry, "dinner", "Dinner Today", "mdi:weather-night"),
            WeekCostSensor(coord, entry),
            MissingIngredientsSensor(coord, entry),
            RecipesCountSensor(coord, entry),
        ]
    )


class _BaseMealEntity(CoordinatorEntity[PlanMyMealsCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PlanMyMealsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Plan My Meals",
            manufacturer="Plan My Meals",
            model="Weekly Meal Planner",
            sw_version=VERSION,
        )


class MealTodaySensor(_BaseMealEntity):
    """Exposes today's lunch or dinner dish with full recipe & cost attributes."""

    def __init__(
        self,
        coordinator: PlanMyMealsCoordinator,
        entry: ConfigEntry,
        meal_key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._meal_key = meal_key
        self._attr_translation_key = f"{meal_key}_today"
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{meal_key}_today"

    def _today_meal(self) -> tuple[dict[str, Any], dict[str, Any]]:
        state = (self.coordinator.data or {}).get("state") or {}
        plan = state.get("weeklyPlan") or []
        costs = ((self.coordinator.data or {}).get("costs") or {}).get("daily") or []
        idx = datetime.now().weekday()
        meal = (plan[idx].get(self._meal_key) or {}) if idx < len(plan) else {}
        cost = costs[idx] if idx < len(costs) else {}
        return meal, cost

    @property
    def native_value(self) -> str:
        meal, _ = self._today_meal()
        return str(meal.get("name") or "—")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        meal, cost = self._today_meal()
        return {
            "recipe_id": meal.get("id"),
            "category": meal.get("category"),
            "cuisine": meal.get("cuisine"),
            "time": meal.get("time"),
            "method": meal.get("method"),
            "rating": meal.get("rating"),
            "image_url": meal.get("image_url"),
            "avg_cost_eur": cost.get(f"{self._meal_key}_avg_eur"),
            "min_cost_eur": cost.get(f"{self._meal_key}_min_eur"),
            "ingredients": meal.get("items") or [],
        }


class WeekCostSensor(_BaseMealEntity):
    """Exposes the estimated weekly average cost based on supermarket prices."""

    _attr_translation_key = "week_cost"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator: PlanMyMealsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_week_cost"

    @property
    def native_unit_of_measurement(self) -> str:
        return str(self.coordinator.cfg.get(CONF_CURRENCY) or DEFAULT_CURRENCY)

    @property
    def native_value(self) -> float | None:
        costs = (self.coordinator.data or {}).get("costs") or {}
        return costs.get("week_avg_eur")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        costs = (self.coordinator.data or {}).get("costs") or {}
        return {
            "week_min_eur": costs.get("week_min_eur"),
            "per_person_avg_eur": costs.get("per_person_avg_eur"),
            "daily": costs.get("daily") or [],
        }


class MissingIngredientsSensor(_BaseMealEntity):
    """Exposes the number of missing ingredients and their best supermarket price/link."""

    _attr_translation_key = "missing_ingredients"
    _attr_icon = "mdi:cart-outline"

    def __init__(self, coordinator: PlanMyMealsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_missing_ingredients"

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("missing") or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        missing = (self.coordinator.data or {}).get("missing") or []
        return {
            "items": [
                {
                    "name": m["name"],
                    "qty": m["qty"],
                    "ha_text": m["ha_text"],
                    "min_price": m["min_price"],
                    "min_store": m["min_store"],
                    "min_url": m["min_url"],
                    "avg_price": m["avg_price"],
                }
                for m in missing[:40]
            ]
        }


class RecipesCountSensor(_BaseMealEntity):
    """Exposes total recipes and sync metadata."""

    _attr_translation_key = "recipes_count"
    _attr_icon = "mdi:book-open-variant"

    def __init__(self, coordinator: PlanMyMealsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_recipes_count"

    @property
    def native_value(self) -> int:
        state = (self.coordinator.data or {}).get("state") or {}
        return len(state.get("recipes") or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = (self.coordinator.data or {}).get("state") or {}
        return {
            "servings": state.get("servings"),
            "updated_at": state.get("updated_at"),
            "updated_by": state.get("updated_by"),
            "migrated_from_legacy": bool(state.get("migrated_from_legacy")),
        }
