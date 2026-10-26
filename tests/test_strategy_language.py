from pathlib import Path

from app.routers.strategies import _normalize_strategy_language
from app.services.prompts import build_reformulate_prompt, build_worker_generate_prompt


def test_german_strategy_language_is_normalized():
    assert _normalize_strategy_language("de") == "German"
    assert _normalize_strategy_language("Allemand") == "German"


def test_worker_prompt_explicitly_enforces_selected_language():
    prompt = build_worker_generate_prompt(
        subject="Thema", commercial_objective="Wachstum", target_sector="B2B",
        language="German", preferred_formats=["post"], target_audience=["KMU"],
        constraints="", prompt="Kontext",
    )
    assert "en German" in prompt
    assert "Ne mélange jamais cette langue avec le français" in prompt


def test_instruction_script_explicitly_enforces_selected_language():
    prompt = build_reformulate_prompt({"language": "German", "prompt": "Mehr Leads"})
    assert "en German" in prompt
    assert "dans la langue German" in prompt


def test_calendar_payload_uses_strategy_language():
    sql = (
        Path(__file__).resolve().parents[1]
        / "sql" / "strategy" / "apply_action_n8n_v90.sql"
    ).read_text(encoding="utf-8")
    assert "END AS output_language" in sql
    assert "'language', sp.output_language" in sql
    assert "'language',ac.output_language" in sql
