"""Parité du flux stratégie/calendrier avec le workflow n8n V90 fourni.

Les règles de qualification d'une action et le SQL d'application proviennent du
workflow « Post Generator V0 - Unified Calendar Worker V90 » fourni comme source
de vérité. Ce module ne décide pas de nouveaux comportements métier.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "strategy" / "apply_action_n8n_v90.sql"
APPLY_ACTION_SQL = _SQL_PATH.read_text(encoding="utf-8")

# Le fichier reste le SQL n8n V90 exact pour audit/parité. À l'exécution Python,
# seule la chaîne d'affichage du fuseau dans le prompt est rendue dynamique ;
# les calculs horaires eux-mêmes utilisent le TimeZone de la transaction.
APPLY_ACTION_SQL_USER_TZ = APPLY_ACTION_SQL.replace(
    "base.recommended_publish_for AT TIME ZONE 'Europe/Paris',",
    "base.recommended_publish_for AT TIME ZONE COALESCE(NULLIF(base.kpi#>>'{calendar_plan,audience_timezone}',''),'Europe/Paris'),",
).replace(
    "|| ' Europe/Paris.'",
    "|| ' ' || COALESCE(NULLIF(base.kpi#>>'{calendar_plan,audience_timezone}',''),'Europe/Paris') || '.'",
)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_TRUE = {"true", "t", "1", "yes", "on", "oui"}
_FALSE = {"false", "f", "0", "no", "off", "non"}


def is_uuid(value: Any) -> bool:
    return bool(_UUID_RE.match(str(value or "").strip()))


def uuid_list(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else str(value or "").split(",")
    out: list[str] = []
    for item in raw:
        item = str(item or "").strip()[:80]
        if is_uuid(item) and item not in out:
            out.append(item)
    return out


def _text(value: Any, max_len: int = 5000) -> str:
    return str(value or "").strip()[:max_len]


def _obj(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def explicit_boolean(value: Any) -> bool | None:
    if value is True or value is False:
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def extract_deliverable(action: dict) -> str:
    direct = _text(
        action.get("deliverable") or action.get("livrable") or action.get("output")
        or action.get("expected_output") or action.get("asset"), 260
    )
    if direct:
        return direct
    desc = str(action.get("description") or "")
    for part in [p.strip() for p in desc.split("|") if p.strip()]:
        match = re.match(r"^(livrable|deliverable|sortie|output)\s*:\s*(.+)$", part, re.I)
        if match and match.group(2):
            return _text(match.group(2), 260)
    match = re.search(r"(?:livrable|deliverable|sortie|output)\s*:\s*([^|.\n]+)", desc, re.I)
    if match:
        return _text(match.group(1), 260)
    text = " ".join(str(action.get(k) or "") for k in ("title", "description", "category")).lower()
    if any(v in text for v in ("reel", "réel", "vidéo", "video")):
        return "1 reel prêt à publier"
    if any(v in text for v in ("carrousel", "carousel")):
        return "1 carrousel prêt à publier"
    if any(v in text for v in ("bio", "profil")):
        return "optimisation profil / bio"
    if any(v in text for v in ("kpi", "mesur", "analyse")):
        return "analyse KPI et recommandation corrective"
    if any(v in text for v in ("planning", "calendrier")):
        return "planning de contenus"
    return "1 post prêt à publier"


def infer_deliverable_kind(deliverable: Any) -> str:
    text = str(deliverable or "").lower()
    if any(v in text for v in ("reel", "réel", "vidéo", "video")):
        return "reel"
    if any(v in text for v in ("carrousel", "carousel")):
        return "carousel"
    if any(v in text for v in ("séquence", "sequence")) or re.search(r"[2-8]\s*(posts|contenus|reels|carrousels|carousel)", text):
        return "sequence"
    if any(v in text for v in ("audit", "bio", "profil")):
        return "profile_update"
    if any(v in text for v in ("kpi", "mesure", "analyse", "reporting")):
        return "analysis"
    if any(v in text for v in ("planning", "calendrier")):
        return "planning"
    return "post"


def extract_format(action: dict, deliverable: str = "") -> str:
    direct = _text(
        action.get("format") or action.get("content_format") or action.get("preferred_format")
        or action.get("post_format") or action.get("asset_format"), 220
    )
    if direct:
        return direct
    desc = str(action.get("description") or "")
    for part in [p.strip() for p in desc.split("|") if p.strip()]:
        match = re.match(r"^(format|forme|support)\s*:\s*(.+)$", part, re.I)
        if match and match.group(2):
            return _text(match.group(2), 220)
    match = re.search(r"(?:format|forme|support)\s*:\s*([^|.\n]+)", desc, re.I)
    if match:
        return _text(match.group(1), 220)
    text = " ".join(str(action.get(k) or "") for k in ("title", "description", "deliverable", "output_type")).lower()
    if any(v in text for v in ("reel", "réel", "vidéo", "video")):
        return "reel court 30-45s"
    if any(v in text for v in ("carrousel", "carousel")):
        return "carrousel 6 slides"
    if any(v in text for v in ("séquence", "sequence")):
        return "séquence de posts courts"
    if any(v in text for v in ("bio", "profil", "audit")):
        return "checklist opérationnelle"
    if any(v in text for v in ("kpi", "mesure", "analyse", "reporting")):
        return "rapport synthèse + recommandations"
    return "post texte court"


def infer_format_kind(fmt: Any, deliverable: Any) -> str:
    text = f"{fmt or ''} {deliverable or ''}".lower()
    if any(v in text for v in ("reel", "réel", "short", "vidéo", "video")):
        return "reel"
    if any(v in text for v in ("carrousel", "carousel", "slides")):
        return "carousel"
    if any(v in text for v in ("séquence", "sequence")) or re.search(r"[2-8]\s*(posts|contenus|reels|réels|carrousels|carousel)", text):
        return "sequence"
    if any(v in text for v in ("checklist", "audit", "bio", "profil")):
        return "checklist"
    if any(v in text for v in ("rapport", "kpi", "analyse", "reporting", "synthèse", "synthese")):
        return "report"
    return "text_post"


def action_requires_post_generation(action: dict, slot: dict | None = None) -> bool:
    slot = slot or {}
    if "requires_post_generation" in action:
        raw = action.get("requires_post_generation")
    elif "generation_required" in action:
        raw = action.get("generation_required")
    elif "requires_post_generation" in slot:
        raw = slot.get("requires_post_generation")
    else:
        raw = slot.get("generation_required")
    explicit = explicit_boolean(raw)
    if explicit is not None:
        return explicit

    category = _text(action.get("category"), 80).lower()
    title = _text(action.get("title"), 500).lower()
    deliverable = _text(action.get("deliverable"), 500).lower()
    fmt = _text(action.get("format"), 500).lower()
    description = _text(action.get("description"), 2000).lower()
    deliverable_kind = _text(action.get("deliverable_kind") or slot.get("deliverable_kind"), 80).lower()
    format_kind = _text(action.get("format_kind") or slot.get("format_kind"), 80).lower()
    full_text = " ".join((title, description, deliverable, fmt))

    if category in {"profil", "profile", "mesure", "measurement", "analysis", "analyse", "engagement"}:
        return False
    if deliverable_kind in {"profile_update", "analysis", "planning"}:
        return False
    if format_kind in {"checklist", "report"}:
        return False
    operational = re.search(
        r"(?:bio|profil|lien du profil|landing page|page de vente|formulaire|tracking|pixel|configuration|paramétrage|parametrage|reporting|tableau décisionnel|tableau decisionnel|analyse kpi|mesurer les résultats|mesurer les resultats)",
        full_text,
    )
    publishable = re.search(r"(?:post|reel|réel|vidéo|video|image|contenu publiable|publication|carrousel|carousel|thread)", full_text)
    if operational and not publishable:
        return False
    return True


def scheduling_action_kind(action: dict, slot: dict | None = None) -> str:
    slot = slot or {}
    category = _text(action.get("category"), 80).lower()
    title = _text(action.get("title"), 500).lower()
    deliverable = _text(action.get("deliverable"), 500).lower()
    fmt = _text(action.get("format"), 500).lower()
    description = _text(action.get("description"), 2000).lower()
    deliverable_kind = _text(action.get("deliverable_kind") or slot.get("deliverable_kind"), 80).lower()
    format_kind = _text(action.get("format_kind") or slot.get("format_kind"), 80).lower()
    full_text = " ".join((title, description, deliverable, fmt))

    if (
        category in {"profil", "profile"}
        or deliverable_kind == "profile_update"
        or re.search(r"(?:cta visible sur le profil|bio[, ]|lien du profil|modifier la bio|réécrire la bio|reecrire la bio|réécrire le cta du profil|reecrire le cta du profil|optimisation profil|mise à jour du profil|mise a jour du profil|contenu épinglé|contenu epingle)", f"{deliverable} {fmt} {title}")
    ):
        return "profile"
    if (
        category in {"mesure", "measurement", "analysis", "analyse"}
        or deliverable_kind == "analysis"
        or format_kind == "report"
        or re.search(r"(?:faire un bilan|tableau décisionnel|tableau decisionnel|décision par pilier|decision par pilier|analyse kpi|mesurer les résultats|mesurer les resultats)", full_text)
    ):
        return "measurement"
    if category == "engagement" or re.search(r"(?:routine d.interaction|commentaires ciblés|commentaires cibles|réponses aux questions|reponses aux questions|interagir uniquement avec des conversations)", full_text):
        return "engagement"
    return "publishable_content" if action_requires_post_generation(action, slot) else "operational"


def canonical_action_payload(action: dict, target_analysis: dict | None = None, timezone_name: str | None = None) -> tuple[dict, dict]:
    """Reproduit les enrichissements persistés par le parser n8n avant INSERT."""
    out = dict(action or {})
    deliverable = extract_deliverable(out)
    deliverable_kind = infer_deliverable_kind(deliverable)
    out["deliverable"] = deliverable
    out["deliverable_kind"] = deliverable_kind

    fmt = extract_format(out, deliverable)
    format_kind = infer_format_kind(fmt, deliverable)
    out["format"] = fmt
    out["content_format"] = fmt
    out["format_kind"] = format_kind

    raw_slot = _obj(out.get("calendar_plan")) or _obj(out.get("calendar_slot"))
    raw_slot["deliverable"] = deliverable
    raw_slot["deliverable_kind"] = deliverable_kind
    raw_slot["format"] = fmt
    raw_slot["format_kind"] = format_kind
    requires = action_requires_post_generation(out, raw_slot)
    schedule_kind = scheduling_action_kind(out, raw_slot)
    raw_slot["generation_required"] = requires
    raw_slot["requires_post_generation"] = requires
    raw_slot["schedule_kind"] = schedule_kind
    if timezone_name:
        raw_slot["audience_timezone"] = str(timezone_name)

    kpi = _obj(out.get("kpi"))
    kpi["deliverable"] = deliverable
    kpi["deliverable_kind"] = deliverable_kind
    kpi["content_format"] = fmt
    kpi["format"] = fmt
    kpi["format_kind"] = format_kind
    kpi["calendar_plan"] = raw_slot
    if isinstance(target_analysis, dict):
        kpi["target_analysis"] = target_analysis
        kpi["primary_target"] = target_analysis.get("primary_target")

    media = _obj(out.get("media_prefill"))
    return kpi, media
