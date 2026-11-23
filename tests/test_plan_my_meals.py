"""Unit tests for Plan My Meals core DB, starter catalog, migration, and supermarket pricing."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "custom_components" / "plan_my_meals"

# Load submodules without requiring Home Assistant runtime in pure unit tests
pkg = types.ModuleType("plan_my_meals")
pkg.__path__ = [str(PKG_DIR)]
sys.modules["plan_my_meals"] = pkg

def _load(sub: str):
    spec = importlib.util.spec_from_file_location(f"plan_my_meals.{sub}", PKG_DIR / f"{sub}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"plan_my_meals.{sub}"] = mod
    spec.loader.exec_module(mod)
    return mod

const = _load("const")
prices = _load("prices")
database = _load("database")
ai_recipes = _load("ai_recipes")


class TestPlanMyMeals(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "plan_my_meals.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_starter_recipes_seed_and_copyright_safe_images(self) -> None:
        store = database.PlanMyMealsDB(self.db_path)
        try:
            state = store.initialize()
            recs = state["recipes"]
            self.assertGreaterEqual(len(recs), 30)
            for r in recs:
                self.assertTrue(r["image_url"].startswith("/plan_my_meals_static/img/"))
                self.assertTrue(r["image_url"].endswith(".svg"))
        finally:
            store.close()

    def test_legacy_migration_preserves_custom_recipes_and_images(self) -> None:
        legacy_path = Path(self.tmp.name) / "legacy.json"
        legacy_path.write_text(
            json.dumps({
                "version": 3,
                "servings": 4,
                "weeklyPlan": [{"day": d, "lunch": {"id": "r1", "name": "Bacalhau", "items": []}, "dinner": {"id": "r2", "name": "Sopa", "items": []}} for d in const.DAYS],
                "recipes": [
                    {"id": "r1", "name": "Bacalhau", "image_url": "/local/meals_img/r1.jpg", "rating": 5, "items": []},
                ],
                "pantry": ["sal"],
            }),
            encoding="utf-8",
        )
        store = database.PlanMyMealsDB(self.db_path, legacy_state_path=legacy_path)
        try:
            state = store.initialize()
            self.assertTrue(state["migrated_from_legacy"])
            self.assertEqual(state["recipes"][0]["image_url"], "/local/meals_img/r1.jpg")
            self.assertEqual(state["recipes"][0]["rating"], 5)
        finally:
            store.close()

    def test_supermarket_prices_average_cost_and_shopping_label(self) -> None:
        html_cont = (
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Ovomaltine 400g","url":"/produto/ovomaltine",'
            '"offers":{"@type":"Offer","price":"11.00","priceCurrency":"EUR"}}'
            '</script>'
        )
        html_auchan = (
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Ovomaltine 400g","url":"/pt/ovomaltine/1.html",'
            '"offers":{"@type":"Offer","price":"9.00","priceCurrency":"EUR"}}'
            '</script>'
        )

        async def fake_fetch(url: str, timeout: int = 10) -> str:
            if "continente.pt" in url:
                return html_cont
            if "auchan.pt" in url:
                return html_auchan
            raise RuntimeError("offline")

        offers = asyncio.run(
            prices.search_supermarkets(
                "Ovomaltine",
                fetch_fn=fake_fetch,
                country="PT",
                enabled_supermarkets=["continente.pt", "auchan.pt"],
            )
        )
        summary = prices.summarize_offers("Ovomaltine", offers)
        self.assertEqual(summary["min_price"], 9.0)
        self.assertEqual(summary["min_store"], "Auchan")
        self.assertEqual(summary["avg_price"], 10.0)
        self.assertEqual(summary["tag"], "9€ Auchan")
        self.assertEqual(summary["min_url"], "https://www.auchan.pt/pt/ovomaltine/1.html")

        store = database.PlanMyMealsDB(self.db_path)
        try:
            state = store.initialize()
            state["servings"] = 4
            state["weeklyPlan"][0]["lunch"] = {
                "id": "custom1",
                "name": "Pequeno-almoço",
                "items": [{"name": "Ovomaltine", "qty": 1, "unit": "un"}],
            }
            for i in range(7):
                if i > 0:
                    state["weeklyPlan"][i]["lunch"] = {"id": f"e{i}", "name": "—", "items": []}
                state["weeklyPlan"][i]["dinner"] = {"id": f"d{i}", "name": "—", "items": []}
            store.save_state(state)
            for of in offers:
                store.upsert_supermarket_price("Ovomaltine", of["supermarket"], of["store_domain"], of["price"], of["title"], of["url"])

            full = store.get_state()
            self.assertEqual(full["costSummary"]["week_avg_eur"], 10.0)
            self.assertEqual(full["costSummary"]["per_person_avg_eur"], 2.5)

            ings = store.aggregate_ingredients(ha_todo_summaries=[])
            ovo = next(i for i in ings if i["key"] == "ovomaltine")
            self.assertEqual(ovo["ha_text"], "Ovomaltine (2 un) (9€ Auchan)")
            self.assertEqual(ovo["min_url"], "https://www.auchan.pt/pt/ovomaltine/1.html")
        finally:
            store.close()

    def test_bimby_and_accessories_migration_and_recipe_persistence(self) -> None:
        # Bimby is treated as a regular appliance and Bimby Friend is a sub-accessory of Bimby
        self.assertIn("bimby", const.APPLIANCE_OPTIONS)
        self.assertIn("bimby_friend", const.APPLIANCE_ACCESSORIES["bimby"])
        self.assertIn("varoma", const.APPLIANCE_ACCESSORIES["bimby"])

        # Legacy bimbyMode + bimbyFriend flags migrate cleanly into appliances + accessories
        migrated = database.normalize_kitchen({
            "appliances": ["forno"],
            "bimbyMode": True,
            "bimbyFriend": True,
        })
        self.assertIn("bimby", migrated["appliances"])
        self.assertIn("forno", migrated["appliances"])
        self.assertIn("bimby_friend", migrated["accessories"]["bimby"])

        # Per-recipe appliances and sub-accessories are persisted on create & edit
        store = database.PlanMyMealsDB(self.db_path)
        try:
            store.initialize()
            res = store.upsert_recipe({
                "id": "rec-bimby-1",
                "name": "Arroz de Tamboril na Bimby",
                "appliances": ["bimby", "forno"],
                "accessories": {"bimby": ["bimby_friend", "varoma"]},
                "items": [{"name": "Tamboril", "qty": 400, "unit": "g"}],
            })
            self.assertTrue(res["ok"])
            self.assertEqual(res["recipe"]["appliances"], ["bimby", "forno"])
            self.assertEqual(res["recipe"]["accessories"], {"bimby": ["bimby_friend", "varoma"]})

            reloaded = next(r for r in store.get_state()["recipes"] if r["id"] == "rec-bimby-1")
            self.assertEqual(reloaded["appliances"], ["bimby", "forno"])
            self.assertEqual(reloaded["accessories"]["bimby"], ["bimby_friend", "varoma"])
        finally:
            store.close()

    def test_frontend_ui_invariants(self) -> None:
        html = (PKG_DIR / "frontend" / "app.html").read_text(encoding="utf-8")
        # Topbar Bimby + Friend button removed
        self.assertNotIn("topbarBimbyBadge", html)
        # Bimby Friend is a sub-accessory of Bimby
        self.assertIn('id: "bimby_friend"', html)
        # Dynamic kitchen panel & per-recipe appliance picker present
        self.assertIn('id="kitchenPanel"', html)
        self.assertIn('id="recipeAppliancesPicker"', html)
        # Smart recipe search: autocomplete, spell correction, and create-from-search button
        self.assertIn('id="recipeSearchSuggestions"', html)
        self.assertIn('id="recipeSearchCorrection"', html)
        self.assertIn("data-create-from-search", html)

    def test_upgrade_and_partial_save_preserve_all_user_data(self) -> None:
        # Simulate an existing v0.1.1 SQLite DB with legacy kitchen format + custom data
        store = database.PlanMyMealsDB(self.db_path)
        try:
            old_state = {
                "version": 4,
                "servings": 6,
                "weeklyPlan": [{"day": d, "lunch": {"id": "custom-1", "name": "Francesinha", "items": []}, "dinner": {"id": "r1", "name": "Sopa", "items": []}} for d in const.DAYS],
                "weeks": {"2026-W46": []},
                "pantry": ["azeite", "alho"],
                "kitchen": {"appliances": ["forno", "airfryer"], "bimbyMode": True, "bimbyFriend": True},
                "recipes": [
                    {"id": "custom-1", "name": "Francesinha", "rating": 5, "source": "app", "items": [{"name": "Bife", "qty": 200, "unit": "g"}]},
                ],
                "customRecipes": [
                    {"id": "custom-1", "name": "Francesinha", "rating": 5, "source": "app", "items": [{"name": "Bife", "qty": 200, "unit": "g"}]},
                ],
                "recipeRatings": {"custom-1": 5},
                "mealHistoryStats": {"custom-1": 4},
                "recipeGuides": {"custom-1": {"steps": "1. Grelhar o bife."}},
                "ingredientPrices": {"bife": {"min_price": 5.5}},
            }
            store._save_raw(old_state)

            # Re-initializing after upgrade preserves all data and migrates Bimby + Friend
            loaded = store.initialize()
            self.assertEqual(loaded["servings"], 6)
            self.assertEqual(loaded["pantry"], ["azeite", "alho"])
            self.assertEqual(loaded["recipeRatings"]["custom-1"], 5)
            self.assertEqual(loaded["mealHistoryStats"]["custom-1"], 4)
            self.assertIn("bimby", loaded["kitchen"]["appliances"])
            self.assertIn("bimby_friend", loaded["kitchen"]["accessories"]["bimby"])

            # A partial save_state (omitting recipes/mealHistoryStats/ingredientPrices) must not wipe them
            store.save_state({"servings": 5, "kitchen": loaded["kitchen"]}, updated_by="Tester")
            after = store.get_state()
            self.assertEqual(after["servings"], 5)
            self.assertEqual(len(after["recipes"]), 1)
            self.assertEqual(after["recipes"][0]["name"], "Francesinha")
            self.assertEqual(after["mealHistoryStats"]["custom-1"], 4)
            self.assertEqual(after["recipeGuides"]["custom-1"]["steps"], "1. Grelhar o bife.")
        finally:
            store.close()

    def test_price_refresh_metadata_and_shopping_options_ui(self) -> None:
        store = database.PlanMyMealsDB(self.db_path)
        try:
            store.initialize()
            store.upsert_supermarket_price("Salmão", "Continente", "continente.pt", 12.99, "Salmão Fresco", "")
            meta = store.record_price_refresh(searched=10, priced=7, mode="ai", updated_by="Automation")
            self.assertEqual(meta["searched"], 10)
            self.assertEqual(meta["priced"], 7)
            self.assertEqual(meta["mode"], "ai")
            self.assertEqual(meta["total_priced_items"], 1)
            self.assertTrue(meta["last_run_at"])

            full = store.get_state()
            self.assertEqual(full["priceRefreshMeta"]["priced"], 7)
            self.assertEqual(full["priceRefreshMeta"]["total_priced_items"], 1)
            self.assertEqual(full["priceRefreshMeta"]["updated_by"], "Automation")
        finally:
            store.close()

        html = (PKG_DIR / "frontend" / "app.html").read_text(encoding="utf-8")
        for marker in ("btnShoppingOptions", "shoppingOptionsDialog", "selPriceSearchMode", "chkIncludeQty", "chkIncludePrice", "btnRunPriceRefreshNow"):
            self.assertIn(marker, html)

    def test_similarity_proposes_alternative_variant(self) -> None:
        store = database.PlanMyMealsDB(self.db_path)
        try:
            store.initialize()
            sim = store.check_similarity(
                "Bacalhau à Brás na Airfryer",
                items=[{"name": "Bacalhau desfiado", "qty": 300, "unit": "g"}, {"name": "Ovos", "qty": 4, "unit": "un"}],
                meal_type="refeicao",
            )
            self.assertIn(sim["status"], ("variant_candidate", "duplicate"))
            self.assertIsNotNone(sim["parent_id"])
            self.assertIn("Bacalhau", sim["parent_name"])
            self.assertTrue(sim["suggested_variant_name"])
        finally:
            store.close()

    def test_i18n_locales_parity_and_manifest(self) -> None:
        locales_dir = PKG_DIR / "frontend" / "locales"
        manifest = json.loads((locales_dir / "index.json").read_text(encoding="utf-8"))
        codes = [lang["code"] for lang in manifest["languages"]]
        self.assertIn("pt", codes)
        self.assertIn("en", codes)

        def flatten_keys(obj: dict, prefix: str = "") -> set[str]:
            keys: set[str] = set()
            for k, v in obj.items():
                full = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    keys |= flatten_keys(v, full)
                else:
                    keys.add(full)
            return keys

        pt_keys = flatten_keys(json.loads((locales_dir / "pt.json").read_text(encoding="utf-8")))
        en_keys = flatten_keys(json.loads((locales_dir / "en.json").read_text(encoding="utf-8")))
        self.assertEqual(pt_keys, en_keys)
        self.assertGreater(len(en_keys), 150)

        # Also verify HA translations parity
        ha_en = flatten_keys(json.loads((PKG_DIR / "translations" / "en.json").read_text(encoding="utf-8")))
        ha_pt = flatten_keys(json.loads((PKG_DIR / "translations" / "pt.json").read_text(encoding="utf-8")))
        ha_str = flatten_keys(json.loads((PKG_DIR / "strings.json").read_text(encoding="utf-8")))
        self.assertEqual(ha_en, ha_pt)
        self.assertEqual(ha_en, ha_str)

        html = (PKG_DIR / "frontend" / "app.html").read_text(encoding="utf-8")
        for marker in ('id="langSelect"', "data-i18n=", "initI18n()", "generate_recipe_ai"):
            self.assertIn(marker, html)

    def test_ai_recipe_resilient_parsing_and_fallback(self) -> None:
        # 1) Tolerant JSON extraction (markdown fence + unescaped newline + trailing comma)
        messy = (
            "Here is your recipe:\n```json\n"
            '{\n  "name": "Grilled Salmon",\n  "category": "Fish",\n'
            '  "kcal": "480 kcal",\n  "protein_g": "42g",\n'
            '  "ingredients_csv": ["300g Salmon", "200g Broccoli"],\n'
            '  "steps": "1. Season salmon.\n2. Airfry at 180C for 12 min.",\n}\n```'
        )
        extracted = ai_recipes.extract_json_object(messy)
        self.assertIsNotNone(extracted)
        norm = ai_recipes.normalize_ai_recipe(extracted, meal_type="refeicao")
        self.assertEqual(norm["name"], "Grilled Salmon")
        self.assertEqual(norm["category"], "Peixe")
        self.assertEqual(norm["kcal"], 480)
        self.assertEqual(norm["protein_g"], 42)
        self.assertEqual(norm["ingredients_csv"], "300g Salmon, 200g Broccoli")
        self.assertIn("2. Airfry", norm["steps"])

        # 2) Two-stage fallback: skip unavailable entity, recover when structured fails -> JSON fallback succeeds
        calls: list[tuple[str, str, bool]] = []

        class _FakeState:
            def __init__(self, state: str) -> None:
                self.state = state

        class _FakeStates:
            def __init__(self) -> None:
                self._map = {
                    "ai_task.offline": _FakeState("unavailable"),
                    "ai_task.primary": _FakeState("idle"),
                }

            def get(self, eid: str):
                return self._map.get(eid)

        class _FakeServices:
            async def async_call(self, domain: str, service: str, data: dict, **kwargs):
                has_struct = "structure" in data
                calls.append((data.get("entity_id", ""), service, has_struct))
                if has_struct:
                    raise RuntimeError("Schema validation error on structured output")
                return {
                    "data": '```json\n{"name": "Arroz de Pato", "category": "Aves", "ingredients_csv": "300g Pato, 200g Arroz", "steps": ["1. Cozer o pato.", "2. Levar ao forno."]}\n```'
                }

        fake_hass = types.SimpleNamespace(states=_FakeStates(), services=_FakeServices())
        res = asyncio.run(
            ai_recipes.async_generate_recipe_with_ai(
                fake_hass,
                candidates=["ai_task.offline", "ai_task.primary"],
                dish_name="Arroz de Pato",
                language="pt",
            )
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["recipe"]["name"], "Arroz de Pato")
        self.assertEqual(res["recipe"]["_ai_mode"], "json_fallback")
        # Offline entity was skipped; primary tried structured then json_fallback
        self.assertEqual(
            calls,
            [
                ("ai_task.primary", "generate_data", True),
                ("ai_task.primary", "generate_data", False),
            ],
        )

    def test_readmes_have_hacs_badge_and_language_links(self) -> None:
        hacs_url = "https://my.home-assistant.io/redirect/hacs_repository/?owner=pleote-dev&repository=plan-my-meals&category=integration"
        badge_img = "https://my.home-assistant.io/badges/hacs_repository.svg"
        en_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        pt_readme = (ROOT / "README.pt.md").read_text(encoding="utf-8")
        self.assertIn(hacs_url, en_readme)
        self.assertIn(badge_img, en_readme)
        self.assertIn("README.pt.md", en_readme)
        self.assertIn(hacs_url, pt_readme)
        self.assertIn(badge_img, pt_readme)
        self.assertIn("README.md", pt_readme)


if __name__ == "__main__":
    unittest.main()
