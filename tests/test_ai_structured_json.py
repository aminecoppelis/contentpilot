import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost/post_generator")
os.environ.setdefault("APP_BASE_URL", "https://socialnetwork.coppelis.com")
os.environ.setdefault("OPENROUTER_MAX_OUTPUT_TOKENS", "12000")
os.environ.setdefault("OPENROUTER_JSON_ATTEMPTS", "3")

from app.config import get_settings
from app.services import ai
from app.services.ai_contracts import normalize_strategy, normalize_strategy_plan, normalize_generate_ideas, AIContractError


class StructuredJSONRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        get_settings.cache_clear()

    async def test_truncated_json_is_regenerated_with_larger_budget(self):
        calls = []

        async def fake_call(system, user, *, max_tokens, temperature, json_mode=True):
            calls.append(max_tokens)
            if len(calls) == 1:
                return ai._Completion(
                    content='{"prompt":"réponse coupée',
                    finish_reason="length",
                    usage={},
                    json_mode_used=True,
                )
            return ai._Completion(
                content='{"prompt":"réponse complète"}',
                finish_reason="stop",
                usage={},
                json_mode_used=True,
            )

        with patch.object(ai, "_call_openrouter", side_effect=fake_call):
            result = await ai._run_agent(
                "JSON only", "test", max_tokens=1200, temperature=0.1,
                validator=ai.normalize_reformulate_prompt,
                context={}, agent_name="test",
            )

        self.assertEqual(result.parsed["prompt"], "réponse complète")
        self.assertEqual(len(calls), 2)
        self.assertGreater(calls[1], calls[0])

    async def test_contract_error_also_triggers_regeneration(self):
        calls = []

        async def fake_call(system, user, *, max_tokens, temperature, json_mode=True):
            calls.append(max_tokens)
            content = '{}' if len(calls) == 1 else '{"prompt":"ok"}'
            return ai._Completion(content=content, finish_reason="stop", usage={}, json_mode_used=True)

        with patch.object(ai, "_call_openrouter", side_effect=fake_call):
            result = await ai._run_agent(
                "JSON only", "test", max_tokens=1000, temperature=0.1,
                validator=ai.normalize_reformulate_prompt,
                context={}, agent_name="test_contract",
            )

        self.assertEqual(result.parsed["prompt"], "ok")
        self.assertEqual(len(calls), 2)


class ContractNormalizationTests(unittest.TestCase):
    def test_strategy_plan_requires_three_posts_per_week(self):
        parsed = {
            "strategy": {
                "title": "Plan mensuel",
                "objective_already_reached": False,
                "objective": {"duration_days": 30},
            },
            "action_blueprints": [
                {
                    "plan_id": f"a{i}", "title": f"Post {i}", "reason": "Objectif éditorial",
                    "category": "content", "requires_post_generation": True, "due_day": i,
                }
                for i in range(1, 12)
            ],
        }
        with self.assertRaises(AIContractError):
            normalize_strategy_plan(parsed, {
                "form_data": {"duration_days": 30},
                "minimum_action_count": 15,
            })

    def test_strategy_keeps_only_publishable_post_actions(self):
        strategy = {"title": "Stratégie", "objective": {"duration_days": 30}}
        actions = [
            {
                "title": "Créer un calendrier éditorial",
                "description": "Mettre en place le planning du mois",
                "category": "content", "requires_post_generation": True,
            },
            {
                "title": "Publier un retour d'expérience client",
                "description": "Générer un post avec un enseignement concret",
                "category": "content", "requires_post_generation": True,
                "format": "post", "angle": "avant/après", "cta": "Demander un diagnostic",
            },
            {
                "title": "Faire un audit mensuel",
                "description": "Analyser les KPI", "category": "measurement",
                "requires_post_generation": False,
            },
        ]

        result = normalize_strategy(
            {"strategy": strategy, "actions": actions},
            {"form_data": {"duration_days": 30}},
        )

        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["actions"][0]["title"], "Publier un retour d'expérience client")
        self.assertTrue(result["actions"][0]["requires_post_generation"])
        self.assertEqual(result["actions"][0]["category"], "content")

    def test_strategy_clamps_enums_ranges_and_removes_unverifiable_profile_action(self):
        parsed = {
            "strategy": {
                "title": "Stratégie",
                "objective": {"duration_days": 999, "feasibility_code": "impossible"},
                "diagnostic": {"growth_potential": 99},
                "target_analysis": {"awareness_code": "bad", "decision_stage_code": "bad", "confidence_code": "bad"},
                "objective_timeline": {"pace": "bad", "confidence": "bad"},
            },
            "actions": [
                {
                    "title": "Changer la bio", "description": "Réécrire la bio", "category": "profil",
                    "priority": "urgent", "due_day": 999, "requires_post_generation": True,
                    "profile_update": {"change_needed": True, "proposed_text": "Nouvelle bio"},
                    "calendar_slot": {"recommended_offset_days": 999, "recommended_hour": 2, "spacing_group": "bad"},
                    "media_prefill": {"media_type": "gif", "aspect_ratio": "3:2"},
                }
            ],
        }
        context = {
            "form_data": {"duration_days": 30},
            "network_snapshot": {"biography_available": False, "profile": {}},
        }
        result = normalize_strategy(parsed, context)
        self.assertEqual(result["strategy"]["objective"]["duration_days"], 30)
        self.assertEqual(result["strategy"]["objective"]["feasibility_code"], "medium")
        self.assertEqual(result["strategy"]["diagnostic"]["growth_potential"], 10)
        self.assertEqual(result["actions"], [])

    def test_strategy_keeps_publishable_content_about_audit(self):
        parsed = {
            "strategy": {"title": "Stratégie", "objective": {"duration_days": 30}},
            "actions": [{
                "plan_id": "a9",
                "title": "Comparaison entre audit traditionnel et digital",
                "description": "Créer une infographie qui compare les deux méthodes.",
                "category": "content",
                "priority": "high",
                "due_day": 9,
                "requires_post_generation": True,
                "deliverable": "Post et infographie prêts à publier",
                "media_prefill": {"media_type": "image", "aspect_ratio": "4:5"},
            }],
        }
        result = normalize_strategy(parsed, {"form_data": {"duration_days": 30}})
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["actions"][0]["plan_id"], "a9")

    def test_generate_ideas_rejects_incomplete_count(self):
        idea = {
            "title": "A", "hook": "A", "summary": "A", "call_to_action": "Contactez-nous",
            "hashtags": ["#a", "#b", "#c", "#d", "#e", "#f", "#g", "#h", "#i", "#j"],
            "ready_post": {"title": "A", "text": "Texte utile", "simple_action": "Contactez-nous", "tags": ["#a", "#b", "#c", "#d", "#e", "#f", "#g", "#h", "#i", "#j"]},
        }
        with self.assertRaises(AIContractError):
            normalize_generate_ideas({"ideas": [idea]}, {"post_count": 2})


if __name__ == "__main__":
    unittest.main()
