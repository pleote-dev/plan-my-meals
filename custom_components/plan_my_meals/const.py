"""Constants for the Plan My Meals integration."""

from __future__ import annotations

DOMAIN = "plan_my_meals"
VERSION = "0.1.0"

PLATFORMS = ["sensor", "calendar", "button"]

STATIC_URL_PATH = "/plan_my_meals_static"
IMG_DIR_NAME = "plan_my_meals_img"
LEGACY_STATE_PATH = "www/plan_my_meals_state.json"

# Config / Options keys
CONF_TODO_ENTITY = "todo_entity"
CONF_SERVINGS = "servings"
CONF_BASE_SERVINGS = "base_servings"
CONF_APPLIANCES = "appliances"
CONF_BIMBY_MODE = "bimby_mode"
CONF_BIMBY_FRIEND = "bimby_friend"
CONF_AI_ENTITY = "ai_entity"
CONF_PRICE_TRACKING = "price_tracking"
CONF_COUNTRY = "country"
CONF_SUPERMARKETS = "supermarkets"
CONF_CURRENCY = "currency"
CONF_PRICE_TTL_DAYS = "price_ttl_days"
CONF_INCLUDE_QTY = "include_qty_in_todo"
CONF_INCLUDE_PRICE = "include_price_in_todo"
CONF_SHOW_SIDEBAR = "show_in_sidebar"
CONF_SIDEBAR_TITLE = "sidebar_title"
CONF_SIDEBAR_ICON = "sidebar_icon"

# Defaults
DEFAULT_TODO_ENTITY = "todo.shopping_list"
DEFAULT_SERVINGS = 4
DEFAULT_BASE_SERVINGS = 2
DEFAULT_APPLIANCES = ["airfryer", "forno", "microondas"]
DEFAULT_COUNTRY = "PT"
DEFAULT_CURRENCY = "€"
DEFAULT_PRICE_TTL_DAYS = 7
DEFAULT_SIDEBAR_TITLE = "Plan My Meals"
DEFAULT_SIDEBAR_ICON = "mdi:food-fork-drink"

DAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
DAYS_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

APPLIANCE_OPTIONS = {
    "airfryer": "Airfryer",
    "forno": "Forno / Oven",
    "microondas": "Micro-ondas / Microwave",
    "fogao": "Fogão / Stovetop",
    "slow_cooker": "Slow Cooker",
    "grelhador": "Grelhador / Grill",
}

SUPERMARKETS_BY_COUNTRY: dict[str, dict[str, str]] = {
    "PT": {
        "continente.pt": "Continente",
        "auchan.pt": "Auchan",
        "pingodoce.pt": "Pingo Doce",
        "mercadao.pt": "Pingo Doce",
        "aldi.pt": "Aldi",
        "lidl.pt": "Lidl",
        "intermarche.pt": "Intermarché",
        "minipreco.pt": "Minipreço",
        "elcorteingles.pt": "El Corte Inglés",
        "mercadona.pt": "Mercadona",
    },
    "ES": {
        "mercadona.es": "Mercadona",
        "carrefour.es": "Carrefour",
        "dia.es": "Dia",
        "alcampo.es": "Alcampo",
        "lidl.es": "Lidl",
        "aldi.es": "Aldi",
        "elcorteingles.es": "El Corte Inglés",
    },
}

DEFAULT_SUPERMARKETS_PT = [
    "continente.pt",
    "auchan.pt",
    "pingodoce.pt",
    "aldi.pt",
    "lidl.pt",
]
