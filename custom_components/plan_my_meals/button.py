"""Button entities for triggering Plan My Meals actions from any dashboard."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import PlanMyMealsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(
        [
            _ActionButton(coord, entry, "generate_week", "Generate Weekly Plan", "mdi:dice-multiple"),
            _ActionButton(coord, entry, "sync_shopping", "Sync Shopping List", "mdi:cart-arrow-down"),
            _ActionButton(coord, entry, "refresh_prices", "Refresh Supermarket Prices", "mdi:tag-search-outline"),
        ]
    )


class _ActionButton(CoordinatorEntity[PlanMyMealsCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PlanMyMealsCoordinator,
        entry: ConfigEntry,
        action: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._action = action
        self._attr_translation_key = action
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_btn_{action}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Plan My Meals",
            manufacturer="Plan My Meals",
            model="Weekly Meal Planner",
            sw_version=VERSION,
        )

    async def async_press(self) -> None:
        if self._action == "generate_week":
            await self.hass.async_add_executor_job(self.coordinator.db.generate_week, "Home Assistant")
            await self.coordinator.async_request_refresh()
        elif self._action == "sync_shopping":
            await self.coordinator.async_sync_shopping_list(refresh_prices=False)
        elif self._action == "refresh_prices":
            await self.coordinator.async_refresh_prices(all_recipes=False, max_items=20)
