"""Calendar platform for Plan My Meals (weekly lunches and dinners)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, VERSION
from .coordinator import PlanMyMealsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([PlanMyMealsCalendar(coord, entry)])


class PlanMyMealsCalendar(CoordinatorEntity[PlanMyMealsCoordinator], CalendarEntity):
    """Calendar showing the weekly lunch and dinner schedule."""

    _attr_has_entity_name = True
    _attr_name = "Meal Schedule"
    _attr_icon = "mdi:calendar-text"

    def __init__(self, coordinator: PlanMyMealsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Plan My Meals",
            manufacturer="Plan My Meals",
            model="Weekly Meal Planner",
            sw_version=VERSION,
        )

    def _build_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        state = (self.coordinator.data or {}).get("state") or {}
        plan = state.get("weeklyPlan") or []
        if not plan:
            return []
        tz = dt_util.get_default_time_zone()
        events: list[CalendarEvent] = []
        cur = start.date()
        end_date = end.date()
        while cur <= end_date:
            idx = cur.weekday()
            if idx < len(plan):
                day_obj = plan[idx]
                for key, label, h_start, h_end in (
                    ("lunch", "Almoço", time(13, 0), time(14, 0)),
                    ("dinner", "Jantar", time(20, 0), time(21, 0)),
                ):
                    meal = day_obj.get(key) or {}
                    name = str(meal.get("name") or "").strip()
                    if not name or name == "—":
                        continue
                    ev_start = datetime.combine(cur, h_start, tzinfo=tz)
                    ev_end = datetime.combine(cur, h_end, tzinfo=tz)
                    if ev_end >= start and ev_start <= end:
                        events.append(
                            CalendarEvent(
                                summary=f"{label}: {name}",
                                start=ev_start,
                                end=ev_end,
                                description=f"{meal.get('category') or ''} · {meal.get('time') or ''}".strip(" ·"),
                            )
                        )
            cur += timedelta(days=1)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = self._build_events(now, now + timedelta(days=2))
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        return self._build_events(start_date, end_date)
