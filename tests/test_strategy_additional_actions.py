import pytest

from app.services.ai import _normalize_additional_blueprints
from app.services.ai_contracts import AIContractError
from app.services.prompts import build_additional_action_blueprints_prompt


def test_additional_blueprints_require_exact_count_and_normalize_fields():
    parsed = {
        "action_blueprints": [
            {"plan_id": "add_1", "title": "Étude de cas client", "priority": "high", "due_day": 8},
            {"plan_id": "add_2", "title": "Démonstration produit", "priority": "unknown", "due_day": 99},
        ]
    }
    result = _normalize_additional_blueprints(
        parsed, {"additional_action_count": 2, "duration_days": 30}
    )
    assert len(result["action_blueprints"]) == 2
    assert result["action_blueprints"][0]["requires_post_generation"] is True
    assert result["action_blueprints"][1]["priority"] == "medium"
    assert result["action_blueprints"][1]["due_day"] == 30


def test_additional_blueprints_support_non_latin_unique_titles():
    result = _normalize_additional_blueprints(
        {"action_blueprints": [{"plan_id": "add_1", "title": "История клиента", "due_day": 2}]},
        {"additional_action_count": 1, "duration_days": 10},
    )
    assert result["action_blueprints"][0]["title"] == "История клиента"


def test_additional_blueprints_reject_duplicates():
    with pytest.raises(AIContractError):
        _normalize_additional_blueprints(
            {"action_blueprints": [
                {"plan_id": "add_1", "title": "Même action"},
                {"plan_id": "add_2", "title": "Même action"},
            ]},
            {"additional_action_count": 2, "duration_days": 10},
        )


def test_additional_prompt_contains_existing_actions_and_guidance():
    prompt = build_additional_action_blueprints_prompt(
        context={"form_data": {"language": "French", "duration_days": 30}},
        strategy={"title": "Croissance organique"},
        existing_actions=[{"title": "Carrousel pédagogique", "status": "pending"}],
        count=3,
        guidance="Privilégier la vidéo",
    )
    assert "EXACTEMENT 3" in prompt
    assert "Carrousel pédagogique" in prompt
    assert "Privilégier la vidéo" in prompt
