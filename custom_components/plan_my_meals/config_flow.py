"""Config flow and options flow for Plan My Meals."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    APPLIANCE_OPTIONS,
    CONF_AI_ENTITY,
    CONF_APPLIANCES,
    CONF_BASE_SERVINGS,
    CONF_BIMBY_FRIEND,
    CONF_BIMBY_MODE,
    CONF_COUNTRY,
    CONF_CURRENCY,
    CONF_INCLUDE_PRICE,
    CONF_INCLUDE_QTY,
    CONF_PRICE_TRACKING,
    CONF_PRICE_TTL_DAYS,
    CONF_SERVINGS,
    CONF_SHOW_SIDEBAR,
    CONF_SIDEBAR_ICON,
    CONF_SIDEBAR_TITLE,
    CONF_SUPERMARKETS,
    CONF_TODO_ENTITY,
    DEFAULT_APPLIANCES,
    DEFAULT_BASE_SERVINGS,
    DEFAULT_COUNTRY,
    DEFAULT_CURRENCY,
    DEFAULT_PRICE_TTL_DAYS,
    DEFAULT_SERVINGS,
    DEFAULT_SIDEBAR_ICON,
    DEFAULT_SIDEBAR_TITLE,
    DEFAULT_SUPERMARKETS_PT,
    DEFAULT_TODO_ENTITY,
    DOMAIN,
    SUPERMARKETS_BY_COUNTRY,
)


def _supermarket_options(country: str) -> list[selector.SelectOptionDict]:
    catalog = SUPERMARKETS_BY_COUNTRY.get(country, SUPERMARKETS_BY_COUNTRY["PT"])
    seen: set[str] = set()
    opts: list[selector.SelectOptionDict] = []
    for dom, name in catalog.items():
        if dom in seen:
            continue
        seen.add(dom)
        opts.append(selector.SelectOptionDict(value=dom, label=f"{name} ({dom})"))
    return opts


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    country = defaults.get(CONF_COUNTRY, DEFAULT_COUNTRY)
    appliance_opts = [
        selector.SelectOptionDict(value=k, label=v) for k, v in APPLIANCE_OPTIONS.items()
    ]
    return vol.Schema(
        {
            vol.Optional(
                CONF_TODO_ENTITY,
                default=defaults.get(CONF_TODO_ENTITY, DEFAULT_TODO_ENTITY),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="todo")),
            vol.Optional(
                CONF_SERVINGS,
                default=defaults.get(CONF_SERVINGS, DEFAULT_SERVINGS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=12, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_BASE_SERVINGS,
                default=defaults.get(CONF_BASE_SERVINGS, DEFAULT_BASE_SERVINGS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=8, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_APPLIANCES,
                default=defaults.get(CONF_APPLIANCES, DEFAULT_APPLIANCES),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=appliance_opts,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_BIMBY_MODE,
                default=defaults.get(CONF_BIMBY_MODE, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_BIMBY_FRIEND,
                default=defaults.get(CONF_BIMBY_FRIEND, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_AI_ENTITY,
                default=defaults.get(CONF_AI_ENTITY, ""),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain=["ai_task", "conversation"])),
            vol.Optional(
                CONF_PRICE_TRACKING,
                default=defaults.get(CONF_PRICE_TRACKING, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_COUNTRY,
                default=country,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="PT", label="Portugal (PT)"),
                        selector.SelectOptionDict(value="ES", label="España (ES)"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_SUPERMARKETS,
                default=defaults.get(CONF_SUPERMARKETS, DEFAULT_SUPERMARKETS_PT),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_supermarket_options(country),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_CURRENCY,
                default=defaults.get(CONF_CURRENCY, DEFAULT_CURRENCY),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_PRICE_TTL_DAYS,
                default=defaults.get(CONF_PRICE_TTL_DAYS, DEFAULT_PRICE_TTL_DAYS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_INCLUDE_QTY,
                default=defaults.get(CONF_INCLUDE_QTY, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_INCLUDE_PRICE,
                default=defaults.get(CONF_INCLUDE_PRICE, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SHOW_SIDEBAR,
                default=defaults.get(CONF_SHOW_SIDEBAR, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SIDEBAR_TITLE,
                default=defaults.get(CONF_SIDEBAR_TITLE, DEFAULT_SIDEBAR_TITLE),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_SIDEBAR_ICON,
                default=defaults.get(CONF_SIDEBAR_ICON, DEFAULT_SIDEBAR_ICON),
            ): selector.IconSelector(),
        }
    )


class PlanMyMealsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Plan My Meals."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get(CONF_SIDEBAR_TITLE) or DEFAULT_SIDEBAR_TITLE,
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=_build_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PlanMyMealsOptionsFlow(config_entry)


class PlanMyMealsOptionsFlow(OptionsFlow):
    """Handle options flow for Plan My Meals."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._entry.data, **self._entry.options}
        return self.async_show_form(step_id="init", data_schema=_build_schema(current))
