"""The Plan My Meals integration for Home Assistant."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_AI_ENTITY,
    CONF_AI_FALLBACK_ENTITY,
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
    IMG_DIR_NAME,
    LEGACY_STATE_PATH,
    PLATFORMS,
    STATIC_URL_PATH,
    VERSION,
)
from .coordinator import PlanMyMealsCoordinator
from .database import PlanMyMealsDB
from .prices import canonical_supermarket, search_recipe_images

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "plan-my-meals-app"


class _PlanMyMealsAppView(HomeAssistantView):
    """Serve app.html with strict no-cache headers so upgrades show immediately."""

    url = f"/api/{DOMAIN}/app"
    name = f"api:{DOMAIN}:app"
    requires_auth = False

    def __init__(self, html_path: Path) -> None:
        self._html_path = html_path

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        html = await hass.async_add_executor_job(self._html_path.read_text, "utf-8")
        return web.Response(
            text=html,
            content_type="text/html",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


def _public_config(entry: ConfigEntry) -> dict[str, Any]:
    cfg = {**entry.data, **entry.options}
    appliances = list(cfg.get(CONF_APPLIANCES) or [])
    accessories: dict[str, list[str]] = {}
    if cfg.get(CONF_BIMBY_MODE) and "bimby" not in appliances:
        appliances.append("bimby")
    if cfg.get(CONF_BIMBY_FRIEND) and "bimby" in appliances:
        accessories["bimby"] = ["bimby_friend"]
    return {
        "todo_entity": cfg.get(CONF_TODO_ENTITY, DEFAULT_TODO_ENTITY),
        "servings": int(cfg.get(CONF_SERVINGS, DEFAULT_SERVINGS)),
        "base_servings": int(cfg.get(CONF_BASE_SERVINGS, DEFAULT_BASE_SERVINGS)),
        "appliances": appliances,
        "accessories": accessories,
        "ai_entity": cfg.get(CONF_AI_ENTITY, ""),
        "ai_fallback_entity": cfg.get(CONF_AI_FALLBACK_ENTITY, ""),
        "price_tracking": bool(cfg.get(CONF_PRICE_TRACKING, True)),
        "country": cfg.get(CONF_COUNTRY, DEFAULT_COUNTRY),
        "supermarkets": list(cfg.get(CONF_SUPERMARKETS) or DEFAULT_SUPERMARKETS_PT),
        "currency": cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY),
        "price_ttl_days": int(cfg.get(CONF_PRICE_TTL_DAYS, DEFAULT_PRICE_TTL_DAYS)),
        "include_qty_in_todo": bool(cfg.get(CONF_INCLUDE_QTY, True)),
        "include_price_in_todo": bool(cfg.get(CONF_INCLUDE_PRICE, True)),
        "version": VERSION,
    }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Plan My Meals from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    db_path = Path(hass.config.path(".storage", DOMAIN, "plan_my_meals.db"))
    legacy_path = Path(hass.config.path(LEGACY_STATE_PATH))
    db = PlanMyMealsDB(db_path=db_path, legacy_state_path=legacy_path)
    cfg = _public_config(entry)
    await hass.async_add_executor_job(db.initialize, cfg)

    coordinator = PlanMyMealsCoordinator(hass, entry, db)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN]["entry"] = entry
    hass.data[DOMAIN]["db"] = db
    hass.data[DOMAIN]["coordinator"] = coordinator

    # Register static frontend assets + no-cache app HTML view
    if not hass.data[DOMAIN].get("static_registered"):
        frontend_dir = Path(__file__).resolve().parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL_PATH, str(frontend_dir), cache_headers=False)]
        )
        hass.http.register_view(_PlanMyMealsAppView(frontend_dir / "app.html"))
        hass.data[DOMAIN]["static_registered"] = True

    # Register sidebar panel if enabled
    merged = {**entry.data, **entry.options}
    if merged.get(CONF_SHOW_SIDEBAR, True):
        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title=merged.get(CONF_SIDEBAR_TITLE, DEFAULT_SIDEBAR_TITLE),
            sidebar_icon=merged.get(CONF_SIDEBAR_ICON, DEFAULT_SIDEBAR_ICON),
            frontend_url_path=PANEL_URL_PATH,
            config={"url": f"/api/{DOMAIN}/app?v={VERSION}"},
            require_admin=False,
            update=True,
        )

    # Register WebSocket API once
    if not hass.data[DOMAIN].get("ws_registered"):
        @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_state"})
        @websocket_api.async_response
        async def ws_get_state(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
            ent: ConfigEntry = hass.data[DOMAIN]["entry"]
            data = coord.data or await coord.async_refresh() or {}
            state = (coord.data or {}).get("state") or await hass.async_add_executor_job(coord.db.get_state)
            connection.send_result(
                msg["id"],
                {
                    "state": state,
                    "ingredients": (coord.data or {}).get("ingredients") or [],
                    "config": _public_config(ent),
                },
            )

        websocket_api.async_register_command(hass, ws_get_state)
        hass.data[DOMAIN]["ws_registered"] = True

    # Register native services
    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        db: PlanMyMealsDB | None = hass.data.get(DOMAIN, {}).pop("db", None)
        if db is not None:
            await hass.async_add_executor_job(db.close)
        hass.data.get(DOMAIN, {}).pop("coordinator", None)
        hass.data.get(DOMAIN, {}).pop("entry", None)
    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    if hass.data[DOMAIN].get("services_registered"):
        return

    async def handle_save_state(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        raw = call.data.get("state_json")
        state = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        updated_by = str(call.data.get("updated_by") or "Home Assistant")
        await hass.async_add_executor_job(coord.db.save_state, state, updated_by)
        await coord.async_request_refresh()
        return {"ok": True}

    async def handle_get_plan(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        ent: ConfigEntry = hass.data[DOMAIN]["entry"]
        data = coord.data or {}
        state = data.get("state") or await hass.async_add_executor_job(coord.db.get_state)
        return {
            "ok": True,
            "state": state,
            "ingredients": data.get("ingredients") or [],
            "missing": data.get("missing") or [],
            "costs": data.get("costs") or {},
            "config": _public_config(ent),
        }

    async def handle_generate_week(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        res = await hass.async_add_executor_job(
            coord.db.generate_week, str(call.data.get("updated_by") or "Home Assistant")
        )
        await coord.async_request_refresh()
        return res

    async def handle_swap_meal(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        res = await hass.async_add_executor_job(
            coord.db.swap_meal,
            int(call.data["day_index"]),
            str(call.data["meal"]),
            str(call.data["dish"]),
            str(call.data.get("updated_by") or "Home Assistant"),
        )
        await coord.async_request_refresh()
        return res

    async def handle_upsert_recipe(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        raw = call.data.get("recipe_json")
        rec = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        updated_by = str(rec.get("updated_by") or call.data.get("updated_by") or "Home Assistant")
        res = await hass.async_add_executor_job(coord.db.upsert_recipe, rec, updated_by)
        await coord.async_request_refresh()
        return res

    async def handle_delete_recipe(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        res = await hass.async_add_executor_job(
            coord.db.delete_recipe,
            str(call.data["recipe_id"]),
            str(call.data.get("updated_by") or "Home Assistant"),
        )
        await coord.async_request_refresh()
        return res

    async def handle_rate_recipe(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        res = await hass.async_add_executor_job(
            coord.db.rate_recipe,
            str(call.data["recipe_id"]),
            int(call.data["rating"]),
            str(call.data.get("updated_by") or "Home Assistant"),
        )
        await coord.async_request_refresh()
        return res

    async def handle_check_similarity(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        return await hass.async_add_executor_job(
            coord.db.check_similarity,
            str(call.data.get("title") or ""),
            list(call.data.get("items") or []),
            str(call.data.get("meal_type") or ""),
        )

    async def handle_upload_image(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        recipe_id = str(call.data.get("recipe_id") or "").strip()
        updated_by = str(call.data.get("updated_by") or "Home Assistant")
        img_dir = Path(hass.config.path("www", IMG_DIR_NAME))
        img_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", recipe_id) or "img"
        fname = f"{safe_id}_{int(time.time())}.jpg"
        dest = img_dir / fname

        img_b64 = str(call.data.get("image_base64") or "").strip()
        img_url_src = str(call.data.get("image_url_source") or "").strip()

        if img_b64:
            if "," in img_b64:
                header, img_b64 = img_b64.split(",", 1)
                if "png" in header.lower():
                    fname = f"{safe_id}_{int(time.time())}.png"
                    dest = img_dir / fname
                elif "webp" in header.lower():
                    fname = f"{safe_id}_{int(time.time())}.webp"
                    dest = img_dir / fname
            raw_bytes = base64.b64decode(img_b64)
            await hass.async_add_executor_job(dest.write_bytes, raw_bytes)
        elif img_url_src.startswith(("http://", "https://")):
            session = async_get_clientsession(hass)
            async with session.get(img_url_src, timeout=15) as resp:
                resp.raise_for_status()
                raw_bytes = await resp.read()
            await hass.async_add_executor_job(dest.write_bytes, raw_bytes)
        else:
            return {"ok": False, "error": "Provide image_base64 or image_url_source."}

        public_url = f"/local/{IMG_DIR_NAME}/{fname}"
        if recipe_id:
            await hass.async_add_executor_job(coord.db.update_recipe_image, recipe_id, public_url, updated_by)
            await coord.async_request_refresh()
        return {"ok": True, "image_url": public_url}

    async def handle_sync_shopping_list(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        return await coord.async_sync_shopping_list(
            refresh_prices=bool(call.data.get("refresh_prices", False))
        )

    async def handle_refresh_prices(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        use_ai_raw = call.data.get("use_ai")
        use_ai = None if use_ai_raw is None else bool(use_ai_raw)
        return await coord.async_refresh_prices(
            all_recipes=bool(call.data.get("all_recipes", False)),
            max_items=int(call.data.get("max_items", 20)),
            use_ai=use_ai,
            updated_by=str(call.data.get("updated_by") or "Automation"),
        )

    async def handle_set_ingredient_price(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        term = str(call.data["ingredient"]).strip()
        store = str(call.data["store"]).strip()
        price = float(call.data["price"])
        url = str(call.data.get("url") or "").strip()
        unit = str(call.data.get("unit") or "").strip()
        unit_price = str(call.data.get("unit_price") or "").strip()
        canon = canonical_supermarket(store, country=coord.cfg.get(CONF_COUNTRY, DEFAULT_COUNTRY))
        dom, name = canon if canon else (store.lower(), store)
        reg = await hass.async_add_executor_job(
            coord.db.upsert_supermarket_price, term, name, dom, price, term, url, unit, unit_price
        )
        await coord.async_request_refresh()
        return {"ok": True, "price": reg}

    async def handle_generate_recipe_ai(call: ServiceCall) -> ServiceResponse:
        coord: PlanMyMealsCoordinator = hass.data[DOMAIN]["coordinator"]
        raw_apps = call.data.get("appliances_desc")
        appliances_desc = list(raw_apps) if isinstance(raw_apps, list) else []
        return await coord.async_generate_recipe_ai(
            dish_name=str(call.data.get("dish_name") or "").strip(),
            hint_text=str(call.data.get("hint_text") or "").strip(),
            existing_ingredients=str(call.data.get("existing_ingredients") or "").strip(),
            meal_type=str(call.data.get("meal_type") or "refeicao").strip(),
            appliances_desc=appliances_desc,
            has_explicit_equipment=bool(call.data.get("has_explicit_equipment", False)),
            uses_bimby=bool(call.data.get("uses_bimby", False)),
            has_bimby_friend=bool(call.data.get("has_bimby_friend", False)),
            language=str(call.data.get("language") or getattr(hass.config, "language", "pt") or "pt").strip(),
        )

    async def handle_search_recipe_images(call: ServiceCall) -> ServiceResponse:
        query = str(call.data.get("query") or "").strip()
        cuisine = str(call.data.get("cuisine") or "").strip()
        category = str(call.data.get("category") or "").strip()
        limit = max(1, min(20, int(call.data.get("limit") or 10)))
        session = async_get_clientsession(hass)
        images = await search_recipe_images(
            query,
            cuisine=cuisine,
            category=category,
            limit=limit,
            session=session,
        )
        return {"ok": True, "query": query, "images": images}

    services = {
        "save_state": handle_save_state,
        "get_plan": handle_get_plan,
        "generate_week": handle_generate_week,
        "swap_meal": handle_swap_meal,
        "upsert_recipe": handle_upsert_recipe,
        "delete_recipe": handle_delete_recipe,
        "rate_recipe": handle_rate_recipe,
        "check_similarity": handle_check_similarity,
        "upload_image": handle_upload_image,
        "search_recipe_images": handle_search_recipe_images,
        "sync_shopping_list": handle_sync_shopping_list,
        "refresh_prices": handle_refresh_prices,
        "set_ingredient_price": handle_set_ingredient_price,
        "generate_recipe_ai": handle_generate_recipe_ai,
    }
    for name, handler in services.items():
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            supports_response=SupportsResponse.OPTIONAL,
        )
    hass.data[DOMAIN]["services_registered"] = True
