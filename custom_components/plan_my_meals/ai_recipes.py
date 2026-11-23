"""Resilient AI recipe generation helpers for Plan My Meals.

Provides:
- Language-aware prompt and relaxed `ai_task.generate_data` structure builders
- Tolerant JSON extraction (markdown fences, trailing commas, unescaped newlines)
- Normalization of AI recipe payloads (handling list/string ingredients & steps,
  noisy numeric strings like "450 kcal", and category mapping)
- Two-stage per-entity execution (structured -> unstructured JSON fallback) with
  generous timeouts and full Home Assistant diagnostic logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Generous timeouts: local LLMs (Ollama/llama) often need 40-75s for full recipes
DEFAULT_AI_TIMEOUT_SECONDS = 60
LOCAL_AI_TIMEOUT_SECONDS = 90

VALID_CATEGORIES = [
    "Peixe",
    "Aves",
    "Carne",
    "Vegetariano",
    "Ovos",
    "Rápido",
    "Pequeno-Almoço",
    "Sobremesa",
]

CATEGORY_ALIASES = {
    # English -> canonical category keys used in DB
    "fish": "Peixe",
    "seafood": "Peixe",
    "poultry": "Aves",
    "chicken": "Aves",
    "turkey": "Aves",
    "meat": "Carne",
    "beef": "Carne",
    "pork": "Carne",
    "vegetarian": "Vegetariano",
    "vegan": "Vegetariano",
    "veggie": "Vegetariano",
    "eggs": "Ovos",
    "egg": "Ovos",
    "quick": "Rápido",
    "fast": "Rápido",
    "easy": "Rápido",
    "breakfast": "Pequeno-Almoço",
    "dessert": "Sobremesa",
    "sweet": "Sobremesa",
    # Spanish / French common aliases
    "pescado": "Peixe",
    "poisson": "Peixe",
    "pollo": "Aves",
    "volaille": "Aves",
    "viande": "Carne",
    "vegetariano": "Vegetariano",
    "huevos": "Ovos",
    "oeufs": "Ovos",
    "rapido": "Rápido",
    "rapide": "Rápido",
    "desayuno": "Pequeno-Almoço",
    "postre": "Sobremesa",
}

LANGUAGE_NAMES = {
    "pt": "Portuguese (Portugal)",
    "pt-pt": "Portuguese (Portugal)",
    "pt-br": "Portuguese (Brazil)",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
}


def _norm(text: str) -> str:
    import unicodedata

    raw = unicodedata.normalize("NFD", str(text or ""))
    return "".join(ch for ch in raw if unicodedata.category(ch) != "Mn").lower().strip()


def timeout_for_entity(entity_id: str) -> int:
    """Return a suitable timeout in seconds for the given AI entity."""
    low = entity_id.lower()
    if any(tok in low for tok in ("ollama", "local", "llama", "mistral", "qwen", "gemma", "whisper")):
        return LOCAL_AI_TIMEOUT_SECONDS
    return DEFAULT_AI_TIMEOUT_SECONDS


def build_recipe_prompt(
    *,
    dish_name: str = "",
    hint_text: str = "",
    existing_ingredients: str = "",
    meal_type: str = "refeicao",
    appliances_desc: list[str] | None = None,
    has_explicit_equipment: bool = False,
    uses_bimby: bool = False,
    has_bimby_friend: bool = False,
    language: str = "pt",
    base_servings: int = 2,
) -> str:
    """Build a clear, language-aware prompt for recipe generation."""
    lang_code = (language or "pt").lower().split("_")[0]
    lang_short = lang_code.split("-")[0]
    appliances_desc = [str(a).strip() for a in (appliances_desc or []) if str(a).strip()]

    if lang_short == "pt":
        type_label = (
            "pequeno-almoço"
            if meal_type == "pequeno_almoco"
            else ("sobremesa" if meal_type == "sobremesa" else "refeição principal (almoço/jantar)")
        )
        bimby_text = ""
        if uses_bimby:
            bimby_text = (
                "A cozinha dispõe de Bimby e Bimby Friend: se for a opção mais eficiente para este prato, "
                "trabalha em paralelo com [Bimby] e [Bimby Friend] usando a notação real "
                "(Tempo / Temperatura / Velocidade, respeitando os limites da Bimby Friend: até 100°C/Varoma e Colher a Vel. 2 inversa)."
                if has_bimby_friend
                else "A cozinha dispõe de Bimby: se for a opção mais eficiente para este prato, "
                "usa a notação real da Bimby em cada passo (Tempo / Temperatura / Velocidade e acessórios disponíveis)."
            )
        equip_text = ""
        if appliances_desc:
            equip_text = (
                f"Eletrodomésticos e acessórios selecionados para esta receita: {'; '.join(appliances_desc)}. "
                "Utiliza estes equipamentos e acessórios na confeção."
                if has_explicit_equipment
                else f"Eletrodomésticos e acessórios disponíveis na cozinha: {'; '.join(appliances_desc)}. "
                "Escolhe automaticamente a combinação mais eficiente destes equipamentos disponíveis e indica no campo 'method' quais os equipamentos utilizados."
            )
        parts = [
            "Responde em português de Portugal.",
            (
                f'Cria ou completa a receita de {type_label} para {base_servings} pessoas de: "{dish_name}".'
                if dish_name
                else f"Sugere uma receita prática e equilibrada de {type_label} caseira portuguesa para {base_servings} pessoas."
            ),
            equip_text,
            bimby_text,
            f"Preferências / notas: {hint_text}."
            if hint_text and _norm(hint_text) != _norm(dish_name)
            else "",
            f"Ingredientes já indicados: {existing_ingredients}." if existing_ingredients else "",
            f"Indica categoria, origem/cozinha, forma de cozinhar com equipamento e temperatura, tempo de preparação, tempo de cozedura, tempo total, "
            f"ingredientes para {base_servings} pessoas separados por vírgula com quantidades, "
            "valores nutricionais estimados por 1 pessoa (kcal, protein_g, carbs_g, fat_g, fiber_g em números inteiros), "
            "e passos curtos numerados com dica de ponto de cozedura.",
        ]
        return " ".join(p for p in parts if p)

    lang_name = LANGUAGE_NAMES.get(lang_code) or LANGUAGE_NAMES.get(lang_short) or "English"
    type_label = (
        "breakfast"
        if meal_type == "pequeno_almoco"
        else ("dessert" if meal_type == "sobremesa" else "main meal (lunch/dinner)")
    )
    bimby_text = ""
    if uses_bimby:
        bimby_text = (
            "The kitchen has a Thermomix/Bimby and Friend: if efficient for this dish, use parallel [Thermomix] and [Friend] steps with real notation (Time / Temperature / Speed)."
            if has_bimby_friend
            else "The kitchen has a Thermomix/Bimby: if efficient for this dish, use real Thermomix notation in each step (Time / Temperature / Speed)."
        )
    equip_text = ""
    if appliances_desc:
        equip_text = (
            f"Selected appliances and accessories for this recipe: {'; '.join(appliances_desc)}. Use them in the cooking method and steps."
            if has_explicit_equipment
            else f"Available kitchen appliances and accessories: {'; '.join(appliances_desc)}. Choose the most efficient combination and state it in 'method'."
        )
    parts = [
        f"Respond in {lang_name}.",
        (
            f'Create or complete a {type_label} recipe for {base_servings} people for: "{dish_name}".'
            if dish_name
            else f"Suggest a practical, balanced homemade {type_label} recipe for {base_servings} people."
        ),
        equip_text,
        bimby_text,
        f"Preferences / notes: {hint_text}."
        if hint_text and _norm(hint_text) != _norm(dish_name)
        else "",
        f"Existing ingredients: {existing_ingredients}." if existing_ingredients else "",
        f"Provide category, cuisine, cooking method with equipment and temperature, prep_time, cook_time, total_time, "
        f"ingredients_csv for {base_servings} people comma-separated with quantities, "
        "estimated nutrition per 1 person as integers (kcal, protein_g, carbs_g, fat_g, fiber_g), "
        "and short numbered cooking steps with a doneness tip.",
    ]
    return " ".join(p for p in parts if p)


def build_relaxed_structure(language: str = "pt") -> dict[str, Any]:
    """Build a permissive ai_task.generate_data structure.

    Uses text selectors for all fields and marks only core fields required so
    diverse LLM providers (Gemini, OpenAI, Anthropic, Ollama) do not fail
    Home Assistant's strict schema validation.
    """
    is_pt = (language or "pt").lower().startswith("pt")
    return {
        "name": {
            "description": "Nome do prato" if is_pt else "Dish name",
            "required": True,
            "selector": {"text": {}},
        },
        "category": {
            "description": "Peixe, Aves, Carne, Vegetariano, Ovos, Rápido, Pequeno-Almoço ou Sobremesa",
            "required": False,
            "selector": {"text": {}},
        },
        "cuisine": {
            "description": "Tipo de cozinha (ex: Portuguesa, Italiana)" if is_pt else "Cuisine type (e.g. Mediterranean, Italian)",
            "required": False,
            "selector": {"text": {}},
        },
        "method": {
            "description": "Equipamento e temperatura (ex: Airfryer 180°C, Forno 190°C)" if is_pt else "Cooking method & temperature (e.g. Airfryer 180°C, Oven 190°C)",
            "required": False,
            "selector": {"text": {}},
        },
        "prep_time": {
            "description": "Tempo de preparação (ex: 15 min)" if is_pt else "Prep time (e.g. 15 min)",
            "required": False,
            "selector": {"text": {}},
        },
        "cook_time": {
            "description": "Tempo de cozedura (ex: 25 min)" if is_pt else "Cook time (e.g. 25 min)",
            "required": False,
            "selector": {"text": {}},
        },
        "total_time": {
            "description": "Tempo total (ex: 40 min)" if is_pt else "Total time (e.g. 40 min)",
            "required": False,
            "selector": {"text": {}},
        },
        "kcal": {
            "description": "Calorias por 1 pessoa (número inteiro)" if is_pt else "Calories per 1 person (integer)",
            "required": False,
            "selector": {"text": {}},
        },
        "protein_g": {
            "description": "Proteína em gramas por 1 pessoa (número inteiro)" if is_pt else "Protein in grams per 1 person (integer)",
            "required": False,
            "selector": {"text": {}},
        },
        "carbs_g": {
            "description": "Hidratos em gramas por 1 pessoa (número inteiro)" if is_pt else "Carbs in grams per 1 person (integer)",
            "required": False,
            "selector": {"text": {}},
        },
        "fat_g": {
            "description": "Gordura em gramas por 1 pessoa (número inteiro)" if is_pt else "Fat in grams per 1 person (integer)",
            "required": False,
            "selector": {"text": {}},
        },
        "fiber_g": {
            "description": "Fibra em gramas por 1 pessoa (número inteiro)" if is_pt else "Fiber in grams per 1 person (integer)",
            "required": False,
            "selector": {"text": {}},
        },
        "ingredients_csv": {
            "description": "Ingredientes separados por vírgula com quantidades (ex: 300g Bacalhau, 400g Batatas)"
            if is_pt
            else "Comma-separated ingredients with quantities (e.g. 300g Cod, 400g Potatoes)",
            "required": True,
            "selector": {"text": {}},
        },
        "steps": {
            "description": "Passos numerados claros de confeção" if is_pt else "Clear numbered cooking steps",
            "required": True,
            "selector": {"text": {}},
        },
    }


def _escape_newlines_in_json_strings(raw: str) -> str:
    """Replace literal newlines/tabs inside JSON string literals with escaped forms."""
    out: list[str] = []
    in_str = False
    escaped = False
    for ch in raw:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_str:
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str and ch == "\n":
            out.append("\\n")
            continue
        if in_str and ch == "\r":
            continue
        if in_str and ch == "\t":
            out.append("\\t")
            continue
        out.append(ch)
    return "".join(out)


def extract_json_object(raw: Any) -> dict[str, Any] | None:
    """Extract a JSON object from an AI response (dict or noisy text)."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None

    # Strip markdown code fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start : end + 1]

    for attempt in (
        candidate,
        _escape_newlines_in_json_strings(candidate),
        re.sub(r",\s*([}\]])", r"\1", _escape_newlines_in_json_strings(candidate)),
    ):
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return None


def _parse_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        return max(0, int(round(value)))
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
    if not match:
        return default
    try:
        return max(0, int(round(float(match.group(1).replace(",", ".")))))
    except ValueError:
        return default


def normalize_category(cat: Any, meal_type: str = "refeicao") -> str:
    if meal_type == "pequeno_almoco":
        return "Pequeno-Almoço"
    if meal_type == "sobremesa":
        return "Sobremesa"
    n = _norm(str(cat or ""))
    for valid in VALID_CATEGORIES:
        if _norm(valid) == n:
            return valid
    if n in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[n]
    for alias, target in CATEGORY_ALIASES.items():
        if alias in n:
            return target
    return "Rápido"


def normalize_ai_recipe(raw: dict[str, Any], *, meal_type: str = "refeicao") -> dict[str, Any]:
    """Normalize heterogeneous AI recipe output into the exact shape expected by the UI."""
    # Ingredients may arrive as string, list of strings, or list of dicts
    raw_ing = raw.get("ingredients_csv") or raw.get("ingredients") or ""
    if isinstance(raw_ing, list):
        parts: list[str] = []
        for item in raw_ing:
            if isinstance(item, dict):
                qty = str(item.get("qty") or item.get("quantity") or "").strip()
                unit = str(item.get("unit") or "").strip()
                name = str(item.get("name") or item.get("ingredient") or "").strip()
                piece = f"{qty}{unit} {name}".strip() if qty else name
                if piece:
                    parts.append(piece)
            elif str(item).strip():
                parts.append(str(item).strip())
        ingredients_csv = ", ".join(parts)
    else:
        ingredients_csv = str(raw_ing).strip()

    # Steps may arrive as string or list of strings
    raw_steps = raw.get("steps") or raw.get("instructions") or raw.get("preparation") or ""
    if isinstance(raw_steps, list):
        steps = "\n".join(str(s).strip() for s in raw_steps if str(s).strip())
    else:
        steps = str(raw_steps).strip()
        if steps and "\n" not in steps:
            steps = re.sub(r"\s+(?=\d+\.\s)", "\n", steps)

    return {
        "name": str(raw.get("name") or raw.get("title") or "").strip(),
        "category": normalize_category(raw.get("category"), meal_type=meal_type),
        "cuisine": str(raw.get("cuisine") or "").strip(),
        "method": str(raw.get("method") or "").strip(),
        "prep_time": str(raw.get("prep_time") or raw.get("prepTime") or "").strip(),
        "cook_time": str(raw.get("cook_time") or raw.get("cookTime") or "").strip(),
        "total_time": str(raw.get("total_time") or raw.get("time") or "").strip(),
        "kcal": _parse_int(raw.get("kcal")),
        "protein_g": _parse_int(raw.get("protein_g")),
        "carbs_g": _parse_int(raw.get("carbs_g")),
        "fat_g": _parse_int(raw.get("fat_g")),
        "fiber_g": _parse_int(raw.get("fiber_g")),
        "ingredients_csv": ingredients_csv,
        "steps": steps,
    }


def _has_usable_recipe_data(recipe: dict[str, Any]) -> bool:
    return bool(recipe.get("name") or recipe.get("ingredients_csv") or recipe.get("steps"))


async def async_generate_recipe_with_ai(
    hass: Any,
    *,
    candidates: list[str],
    dish_name: str = "",
    hint_text: str = "",
    existing_ingredients: str = "",
    meal_type: str = "refeicao",
    appliances_desc: list[str] | None = None,
    has_explicit_equipment: bool = False,
    uses_bimby: bool = False,
    has_bimby_friend: bool = False,
    language: str = "pt",
    base_servings: int = 2,
) -> dict[str, Any]:
    """Run resilient AI recipe generation across candidate HA entities with full logging."""
    prompt = build_recipe_prompt(
        dish_name=dish_name,
        hint_text=hint_text,
        existing_ingredients=existing_ingredients,
        meal_type=meal_type,
        appliances_desc=appliances_desc,
        has_explicit_equipment=has_explicit_equipment,
        uses_bimby=uses_bimby,
        has_bimby_friend=has_bimby_friend,
        language=language,
        base_servings=base_servings,
    )
    structure = build_relaxed_structure(language=language)
    json_keys = (
        "name, category, cuisine, method, prep_time, cook_time, total_time, "
        "kcal, protein_g, carbs_g, fat_g, fiber_g, ingredients_csv, steps"
    )
    json_only_prompt = (
        f"{prompt} Return ONLY a single valid JSON object (no markdown fences, no extra prose) "
        f"with these keys: {json_keys}."
    )

    attempts: list[dict[str, Any]] = []

    for entity_id in candidates:
        state_obj = hass.states.get(entity_id) if hasattr(hass, "states") else None
        if state_obj is not None and str(getattr(state_obj, "state", "")).lower() in ("unavailable", "unknown"):
            _LOGGER.warning("Skipping AI entity %s because its state is %s", entity_id, state_obj.state)
            attempts.append({
                "entity_id": entity_id,
                "mode": "skip",
                "ok": False,
                "duration_ms": 0,
                "error": f"Entity state is {state_obj.state}",
            })
            continue

        timeout_s = timeout_for_entity(entity_id)

        if entity_id.startswith("conversation."):
            t0 = time.monotonic()
            try:
                resp = await asyncio.wait_for(
                    hass.services.async_call(
                        "conversation",
                        "process",
                        {"agent_id": entity_id, "text": json_only_prompt},
                        blocking=True,
                        return_response=True,
                    ),
                    timeout=timeout_s,
                )
                speech = (
                    ((resp or {}).get("response") or {}).get("speech", {}).get("plain", {}).get("speech")
                    or (resp or {}).get("speech", {}).get("plain", {}).get("speech")
                    or ""
                )
                parsed = extract_json_object(speech)
                if parsed:
                    recipe = normalize_ai_recipe(parsed, meal_type=meal_type)
                    if _has_usable_recipe_data(recipe):
                        dur = int((time.monotonic() - t0) * 1000)
                        _LOGGER.info("AI recipe generated via %s (conversation) in %dms", entity_id, dur)
                        recipe["_ai_entity"] = entity_id
                        recipe["_ai_mode"] = "conversation"
                        attempts.append({"entity_id": entity_id, "mode": "conversation", "ok": True, "duration_ms": dur})
                        return {"ok": True, "recipe": recipe, "attempts": attempts}
                raise ValueError("Conversation response did not contain valid recipe JSON.")
            except Exception as exc:
                dur = int((time.monotonic() - t0) * 1000)
                _LOGGER.warning("AI recipe failed on %s (conversation) after %dms: %s", entity_id, dur, exc)
                attempts.append({
                    "entity_id": entity_id,
                    "mode": "conversation",
                    "ok": False,
                    "duration_ms": dur,
                    "error": str(exc),
                })
            continue

        # Stage A: ai_task.generate_data with relaxed structure
        timed_out = False
        t0 = time.monotonic()
        try:
            resp = await asyncio.wait_for(
                hass.services.async_call(
                    "ai_task",
                    "generate_data",
                    {
                        "entity_id": entity_id,
                        "task_name": "Plan My Meals Recipe",
                        "instructions": prompt,
                        "structure": structure,
                    },
                    blocking=True,
                    return_response=True,
                ),
                timeout=timeout_s,
            )
            raw_data = (resp or {}).get("data") if isinstance(resp, dict) else resp
            parsed = extract_json_object(raw_data)
            if parsed:
                recipe = normalize_ai_recipe(parsed, meal_type=meal_type)
                if _has_usable_recipe_data(recipe):
                    dur = int((time.monotonic() - t0) * 1000)
                    _LOGGER.info("AI recipe generated via %s (structured) in %dms", entity_id, dur)
                    recipe["_ai_entity"] = entity_id
                    recipe["_ai_mode"] = "structured"
                    attempts.append({"entity_id": entity_id, "mode": "structured", "ok": True, "duration_ms": dur})
                    return {"ok": True, "recipe": recipe, "attempts": attempts}
            raise ValueError(f"Empty or non-object structured response: {str(raw_data)[:160]}")
        except TimeoutError:
            timed_out = True
            dur = int((time.monotonic() - t0) * 1000)
            _LOGGER.warning("AI recipe timed out on %s (structured) after %ds", entity_id, timeout_s)
            attempts.append({
                "entity_id": entity_id,
                "mode": "structured",
                "ok": False,
                "duration_ms": dur,
                "error": f"Timeout ({timeout_s}s)",
            })
        except Exception as exc:
            dur = int((time.monotonic() - t0) * 1000)
            _LOGGER.warning("AI recipe structured call failed on %s after %dms: %s", entity_id, dur, exc)
            attempts.append({
                "entity_id": entity_id,
                "mode": "structured",
                "ok": False,
                "duration_ms": dur,
                "error": str(exc),
            })

        # Stage B: If structured call failed for a non-timeout reason (e.g., schema rejection),
        # retry on the SAME entity without `structure` asking for plain JSON.
        if not timed_out:
            t1 = time.monotonic()
            try:
                resp2 = await asyncio.wait_for(
                    hass.services.async_call(
                        "ai_task",
                        "generate_data",
                        {
                            "entity_id": entity_id,
                            "task_name": "Plan My Meals Recipe JSON",
                            "instructions": json_only_prompt,
                        },
                        blocking=True,
                        return_response=True,
                    ),
                    timeout=timeout_s,
                )
                raw_data2 = (resp2 or {}).get("data") if isinstance(resp2, dict) else resp2
                parsed2 = extract_json_object(raw_data2)
                if parsed2:
                    recipe2 = normalize_ai_recipe(parsed2, meal_type=meal_type)
                    if _has_usable_recipe_data(recipe2):
                        dur2 = int((time.monotonic() - t1) * 1000)
                        _LOGGER.info("AI recipe generated via %s (json fallback) in %dms", entity_id, dur2)
                        recipe2["_ai_entity"] = entity_id
                        recipe2["_ai_mode"] = "json_fallback"
                        attempts.append({"entity_id": entity_id, "mode": "json_fallback", "ok": True, "duration_ms": dur2})
                        return {"ok": True, "recipe": recipe2, "attempts": attempts}
                raise ValueError(f"Unstructured response did not contain valid recipe JSON: {str(raw_data2)[:160]}")
            except Exception as exc2:
                dur2 = int((time.monotonic() - t1) * 1000)
                _LOGGER.warning("AI recipe JSON fallback failed on %s after %dms: %s", entity_id, dur2, exc2)
                attempts.append({
                    "entity_id": entity_id,
                    "mode": "json_fallback",
                    "ok": False,
                    "duration_ms": dur2,
                    "error": str(exc2),
                })

    return {
        "ok": False,
        "error": attempts[0]["error"] if attempts else "No AI entities available.",
        "attempts": attempts,
    }
