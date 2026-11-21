"""Constants for the Plan My Meals integration."""

from __future__ import annotations

DOMAIN = "plan_my_meals"
VERSION = "0.1.2"

PLATFORMS = ["sensor", "calendar", "button"]

STATIC_URL_PATH = "/plan_my_meals_static"
IMG_DIR_NAME = "plan_my_meals_img"
LEGACY_STATE_PATH = "www/plan_my_meals_state.json"

# Config / Options keys
CONF_TODO_ENTITY = "todo_entity"
CONF_SERVINGS = "servings"
CONF_BASE_SERVINGS = "base_servings"
CONF_APPLIANCES = "appliances"
CONF_BIMBY_MODE = "bimby_mode"  # Legacy key (migrated into appliances)
CONF_BIMBY_FRIEND = "bimby_friend"  # Legacy key (migrated into accessories.bimby)
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
DEFAULT_APPLIANCES = ["airfryer", "forno", "microondas", "fogao", "grelhador"]
DEFAULT_COUNTRY = "PT"
DEFAULT_CURRENCY = "€"
DEFAULT_PRICE_TTL_DAYS = 7
DEFAULT_SIDEBAR_TITLE = "Plan My Meals"
DEFAULT_SIDEBAR_ICON = "mdi:food-fork-drink"

DAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
DAYS_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

APPLIANCE_OPTIONS = {
    "bimby": "Bimby / Thermomix",
    "airfryer": "Airfryer",
    "forno": "Forno / Oven",
    "fogao": "Fogão / Stovetop",
    "grelhador": "Grelhador / Grill",
    "microondas": "Micro-ondas / Microwave",
    "panela_pressao": "Panela de Pressão / Pressure Cooker",
    "slow_cooker": "Slow Cooker",
    "varinha_magica": "Varinha Mágica / Blender",
    "batedeira": "Batedeira / Stand Mixer",
}

APPLIANCE_ACCESSORIES: dict[str, dict[str, str]] = {
    "bimby": {
        "bimby_friend": "Bimby Friend",
        "varoma": "Varoma",
        "cesto": "Cesto",
        "borboleta": "Borboleta",
        "protetor_lamina": "Protetor de Lâmina / Descascador",
        "cortador": "Cortador / Fatiador",
        "espiralizador": "Espiralizador",
        "sensor": "Thermomix Sensor",
        "tampa_antisalpicos": "Tampa Anti-Salpicos",
        "copo_extra": "Segundo Copo",
    },
    "airfryer": {
        "cesto_duplo": "Cesto Duplo / Divisória",
        "grelha_airfryer": "Grelha de 2 Níveis",
        "forma_silicone": "Forma de Silicone",
        "forma_bolo": "Forma de Bolo / Tarte",
        "espetos": "Suporte de Espetadas",
        "tab_pizza": "Tabuleiro de Pizza",
    },
    "forno": {
        "tabuleiro_forno": "Tabuleiro / Assadeira",
        "pyrex": "Travessa Pyrex / Cerâmica",
        "forma_tarte": "Forma de Tarte / Quiche",
        "forma_bolo_forno": "Forma de Bolo",
        "pedra_pizza": "Pedra de Pizza",
        "sonda_forno": "Sonda de Temperatura",
    },
    "fogao": {
        "frigideira": "Frigideira Antiaderente",
        "wok": "Wok",
        "tacho_fundo_grosso": "Tacho / Caçarola",
        "chapa_ferro": "Frigideira / Chapa de Ferro Fundido",
        "cesto_vapor_tacho": "Cesto de Vapor",
        "banho_maria": "Taça de Banho-Maria",
    },
    "grelhador": {
        "placas_lisas": "Placas Lisas / Plancha",
        "placas_waffles": "Placas de Waffles / Sandes",
        "espetos_grelha": "Espetos Metálicos",
        "cesto_legumes": "Cesto para Legumes",
    },
    "microondas": {
        "prato_crisp": "Prato Crisp / Dourador",
        "vapor_microondas": "Recipiente de Vapor",
        "tampa_microondas": "Tampa Protetora",
        "grelha_grill": "Grelha Grill",
    },
    "panela_pressao": {
        "cesto_vapor_pressao": "Cesto de Vapor",
        "suporte_tripe": "Tripé / Suporte Interno",
        "tampa_vidro": "Tampa de Vidro",
    },
    "slow_cooker": {
        "tacho_ceramica": "Cuba Cerâmica",
        "grelha_assados": "Grelha para Assados",
    },
    "varinha_magica": {
        "copo_medidor": "Copo Medidor",
        "picadora": "Acessório Picadora",
        "batedor_varas": "Vara de Arames",
    },
    "batedeira": {
        "batedor_pinha": "Batedor de Arames",
        "gancho_massa": "Gancho de Amassar",
        "pa_mistura": "Pá de Mistura",
    },
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
