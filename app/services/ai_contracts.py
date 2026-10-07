"""Validation et normalisation des contrats JSON retournés par les agents IA.

Le prompt reste une première ligne de défense. Ce module est la barrière serveur :
un JSON syntaxiquement valide n'est accepté que si sa forme et ses valeurs sont
compatibles avec le code métier qui le consomme ensuite.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
import json
import re
import unicodedata
from urllib.parse import urlparse


class AIContractError(ValueError):
    """La réponse est du JSON valide mais ne respecte pas le contrat attendu."""


def _dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "oui", "on"}:
        return True
    if text in {"0", "false", "no", "non", "off"}:
        return False
    return default


def _int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).replace("\x00", "").strip()


def _enum(value: Any, allowed: set[str], default: str) -> str:
    text = _text(value).lower()
    return text if text in allowed else default


def _list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _string_list(value: Any, *, limit: int | None = None) -> list[str]:
    values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _text(item)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return result


def _hashtags(value: Any, *, limit: int = 10) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    values: list[Any]
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        values = value.replace(",", " ").replace(";", " ").split()
    else:
        values = []
    for item in values:
        tag = _text(item)
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        tag = tag.split()[0]
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def _ensure_final_cta(text: str, action: str) -> str:
    text = _text(text)
    action = _text(action)
    if not action:
        return text
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    action_key = action.rstrip(".!? ").casefold()
    while paragraphs and paragraphs[-1].rstrip(".!? ").casefold() == action_key:
        paragraphs.pop()
    return "\n\n".join([*paragraphs, action]).strip()




def _normalize_website(value: Any) -> str:
    website = _text(value)
    if not website:
        return ""
    if not re.match(r"^https?://", website, flags=re.I):
        if re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/.*)?$", website, flags=re.I):
            website = "https://" + website
    return website.rstrip("/")


def _slug_hashtag(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return ""
    joined = "".join(word[:1].upper() + word[1:] for word in words)[:48]
    return "#" + joined if joined else ""


def _context_hashtags(context: dict | None, *, limit: int = 10) -> list[str]:
    context = context or {}
    candidates: list[Any] = []
    candidates.extend(_hashtags(context.get("default_tags"), limit=limit))
    content_context = _dict(context.get("content_context"))
    candidates.extend(_hashtags(content_context.get("default_tags"), limit=limit))
    for key in ("content_domains", "target_audience", "preferred_formats"):
        for value in _string_list(context.get(key), limit=10):
            candidates.append(_slug_hashtag(value))
    for key in ("target_sector", "solution", "company", "entreprise"):
        candidates.append(_slug_hashtag(context.get(key)))
    # Valeurs de secours générales : elles n'ajoutent aucun fait ou promesse.
    candidates.extend([
        "#Innovation", "#TransformationDigitale", "#MarketingDigital", "#Entreprise",
        "#Productivite", "#Automatisation", "#Technologie", "#Business",
        "#Contenu", "#ReseauxSociaux",
    ])
    return _hashtags(candidates, limit=limit)


def _strip_trailing_hashtags(text: str) -> str:
    lines = _text(text).splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    while lines:
        line = lines[-1].strip()
        tokens = [t for t in re.split(r"\s+", line) if t]
        if tokens and all(t.startswith("#") for t in tokens):
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
            continue
        break
    return "\n".join(lines).strip()


def _finalize_ready_post_text(text: str, action: str, tags: list[str], website: str) -> str:
    body = _strip_trailing_hashtags(text)
    if website:
        parsed = urlparse(website)
        variants = [website]
        if parsed.netloc:
            variants.append(parsed.netloc + (parsed.path.rstrip("/") if parsed.path not in ("", "/") else ""))
        for variant in sorted(set(v for v in variants if v), key=len, reverse=True):
            body = re.sub(r"(?im)^\s*" + re.escape(variant) + r"/?\s*$", "", body)
            body = body.replace(variant, "")
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
    body = _ensure_final_cta(body, action)
    parts = [body]
    if website:
        parts.append(website)
    if tags:
        parts.append(" ".join(tags))
    return "\n\n".join(part for part in parts if part).strip()


def normalize_filter_news(parsed: Any, _context: dict | None = None) -> dict:
    data = _dict(parsed)
    if not data:
        raise AIContractError("Le filtre actualité doit être un objet JSON.")
    return {
        **data,
        "relevance_score": _int(data.get("relevance_score"), 0, 10, 0),
        "risk_score": _int(data.get("risk_score"), 0, 10, 10),
        "topic": _text(data.get("topic")),
        "usable_angle": _text(data.get("usable_angle")),
        "source_summary": _text(data.get("source_summary")),
        "should_use": _bool(data.get("should_use"), False),
    }


def _extract_ideas(parsed: Any) -> list:
    if isinstance(parsed, list):
        return parsed
    data = _dict(parsed)
    for key in ("ideas", "post_ideas", "posts", "postIdeas", "contents", "items", "results"):
        if isinstance(data.get(key), list):
            return data[key]
    if isinstance(data.get("ideas"), dict):
        return list(data["ideas"].values())
    return []


def _normalize_idea(raw: Any, *, worker: bool = False, context: dict | None = None) -> dict:
    idea = deepcopy(_dict(raw))
    if not idea:
        raise AIContractError("Une idée générée n'est pas un objet JSON.")

    ready = _dict(idea.get("ready_post"))
    title = _text(idea.get("title") or ready.get("title"))
    post_text = _text(ready.get("text") or idea.get("post_text") or idea.get("text") or idea.get("content"))
    action = _text(ready.get("simple_action") or idea.get("call_to_action") or idea.get("cta"))
    if not title:
        raise AIContractError("Une idée générée ne contient pas de title.")
    if not post_text:
        raise AIContractError(f"L'idée « {title} » ne contient pas ready_post.text.")
    if not action:
        raise AIContractError(f"L'idée « {title} » ne contient pas de CTA final.")

    hashtags = _hashtags(idea.get("hashtags"), limit=10)
    ready_tags = _hashtags(ready.get("tags"), limit=10)
    combined_seed = [*ready_tags, *hashtags, *_context_hashtags(context, limit=10)]
    ready_tags = _hashtags(combined_seed, limit=10)

    minimum_tags = 5
    if len(ready_tags) < minimum_tags:
        raise AIContractError(f"L'idée « {title} » contient moins de {minimum_tags} hashtags exploitables.")
    if worker and not 250 <= len(post_text) <= 1500:
        raise AIContractError(f"ready_post.text doit contenir entre 250 et 1500 caractères (reçu: {len(post_text)}).")

    score_fields = (
        "virality_score", "commercial_potential_score", "implementation_difficulty_score",
        "sme_interest_score", "enterprise_interest_score", "lead_generation_score",
    )
    for field in score_fields:
        idea[field] = _int(idea.get(field), 0, 10, 0)

    idea["title"] = title
    idea["hook"] = _text(idea.get("hook") or title)
    idea["summary"] = _text(idea.get("summary") or idea["hook"])
    idea["call_to_action"] = action
    idea["hashtags"] = hashtags or ready_tags[:10]
    idea["seo_keywords"] = _string_list(idea.get("seo_keywords"), limit=20)
    website = _normalize_website((context or {}).get("website") or (context or {}).get("site_web") or _dict((context or {}).get("content_context")).get("website"))
    final_tags = ready_tags[:10]
    idea["ready_post"] = {
        **ready,
        "title": _text(ready.get("title") or title),
        "text": _finalize_ready_post_text(post_text, action, final_tags, website),
        "simple_action": action,
        "tags": final_tags,
    }
    idea["hashtags"] = final_tags
    return idea


def normalize_generate_ideas(parsed: Any, context: dict | None = None) -> dict:
    context = context or {}
    expected = _int(context.get("post_count") or context.get("count"), 1, 8, 5)
    ideas = [_normalize_idea(value, context=context) for value in _extract_ideas(parsed)]
    if len(ideas) < expected:
        raise AIContractError(f"Nombre d'idées incomplet : {len(ideas)} reçu(s), {expected} attendu(s).")
    for idea in ideas[:expected]:
        combined = _hashtags([*(idea.get("hashtags") or []), *(idea.get("ready_post", {}).get("tags") or []), *_context_hashtags(context, limit=10)], limit=10)
        if len(combined) < 10:
            raise AIContractError(f"L'idée « {idea.get('title', '')} » ne peut pas être finalisée avec 10 hashtags.")
        idea["hashtags"] = combined[:10]
        idea["ready_post"]["tags"] = combined[:10]
        idea["ready_post"]["text"] = _finalize_ready_post_text(
            idea["ready_post"]["text"], idea["ready_post"]["simple_action"], combined[:10],
            _normalize_website(context.get("website") or context.get("site_web") or _dict(context.get("content_context")).get("website")),
        )
    return {"ideas": ideas[:expected]}


def normalize_modify_idea(parsed: Any, context: dict | None = None) -> dict:
    data = _dict(parsed)
    raw = data.get("idea") if isinstance(data.get("idea"), dict) else data
    idea = _normalize_idea(raw, context=context)
    source_format = _text((context or {}).get("recommended_format"))
    if source_format:
        idea["recommended_format"] = source_format
    return {"idea": idea}


def normalize_reformulate_prompt(parsed: Any, _context: dict | None = None) -> dict:
    data = _dict(parsed)
    prompt = _text(data.get("prompt"))
    if not prompt:
        raise AIContractError("La réponse de reformulation ne contient pas le champ prompt.")
    return {"prompt": prompt}


_ALLOWED_IMAGE_STYLES = {
    "photo_realiste", "illustration_b2b", "mockup_saas", "infographie", "isometrique",
    "flat_design", "3d", "cover_linkedin", "visuel_reel", "avatar", "objet_anime",
}
_ALLOWED_VIDEO_STYLES = {
    "demo_produit", "video_explicative", "avant_apres", "storytelling_court", "motion_design",
    "video_realiste", "avatar", "objet_anime",
}


def normalize_strategy(parsed: Any, context: dict | None = None) -> dict:
    context = context or {}
    data = _dict(parsed)
    strategy = deepcopy(_dict(data.get("strategy")))
    if not strategy:
        raise AIContractError("La réponse stratégie ne contient pas l'objet strategy.")

    form_data = _dict(context.get("form_data"))
    duration = _int(form_data.get("duration_days") or _dict(strategy.get("objective")).get("duration_days"), 1, 365, 30)
    objective = _dict(strategy.get("objective"))
    objective["duration_days"] = duration
    objective["feasibility_code"] = _enum(objective.get("feasibility_code"), {"low", "medium", "high"}, "medium")
    strategy["objective"] = objective

    title = _text(strategy.get("title"))
    if not title:
        raise AIContractError("La stratégie ne contient pas de title.")
    strategy["title"] = title
    strategy["objective_already_reached"] = _bool(strategy.get("objective_already_reached"), False)

    diagnostic = _dict(strategy.get("diagnostic"))
    for key in (
        "profile_maturity", "positioning_clarity", "content_consistency",
        "audience_fit", "conversion_readiness", "growth_potential",
    ):
        diagnostic[key] = _int(diagnostic.get(key), 0, 10, 0)
    strategy["diagnostic"] = diagnostic

    target = _dict(strategy.get("target_analysis"))
    target["awareness_code"] = _enum(
        target.get("awareness_code"),
        {"unaware", "problem_aware", "solution_aware", "product_aware", "ready_to_buy"},
        "problem_aware",
    )
    target["decision_stage_code"] = _enum(
        target.get("decision_stage_code"),
        {"discovery", "consideration", "conversion", "retention"},
        "discovery",
    )
    target["confidence_code"] = _enum(target.get("confidence_code"), {"low", "medium", "high"}, "medium")
    strategy["target_analysis"] = target

    review = _dict(strategy.get("expert_marketing_review"))
    review["feasibility_code"] = _enum(review.get("feasibility_code"), {"low", "medium", "high"}, "medium")
    strategy["expert_marketing_review"] = review

    timeline = _dict(strategy.get("objective_timeline"))
    timeline["max_days"] = _int(timeline.get("max_days"), 0, 365, duration)
    timeline["estimated_days_to_target"] = _int(timeline.get("estimated_days_to_target"), 0, 365, duration)
    timeline["confidence"] = _enum(timeline.get("confidence"), {"low", "medium", "high"}, "medium")
    timeline["pace"] = _enum(timeline.get("pace"), {"aggressive", "balanced", "conservative"}, "balanced")
    strategy["objective_timeline"] = timeline

    adaptive = _dict(strategy.get("adaptive_control"))
    checkpoints = []
    for checkpoint_raw in _list(adaptive.get("checkpoints"))[:4]:
        checkpoint = _dict(checkpoint_raw)
        if not checkpoint:
            continue
        checkpoint["offset_ratio"] = _float(checkpoint.get("offset_ratio"), 0.0, 1.0, 0.33)
        checkpoint["expected_progress_ratio"] = _float(checkpoint.get("expected_progress_ratio"), 0.0, 1.0, 0.3)
        checkpoints.append(checkpoint)
    adaptive["checkpoints"] = checkpoints
    strategy["adaptive_control"] = adaptive

    profile_snapshot = _dict(context.get("profile_snapshot"))
    snapshot_profile = _dict(profile_snapshot.get("profile"))
    network = _dict(context.get("network_snapshot"))
    profile = snapshot_profile or _dict(network.get("profile"))
    biography_available = _bool(
        profile.get("biography_available"),
        _bool(network.get("biography_available"), False),
    )
    biography = _text(profile.get("biography") or profile.get("about") or profile.get("description"))

    actions: list[dict] = []
    for raw_action in _list(data.get("actions")):
        action = deepcopy(_dict(raw_action))
        if not action:
            continue
        action["title"] = _text(action.get("title"))
        action["description"] = _text(action.get("description"))
        if not action["title"] or not action["description"]:
            raise AIContractError("Une action stratégie est dépourvue de title ou description.")
        action["priority"] = _enum(action.get("priority"), {"low", "medium", "high"}, "medium")
        action["due_day"] = _int(action.get("due_day"), 1, duration, 1)
        action["requires_post_generation"] = _bool(action.get("requires_post_generation"), False)

        category = _text(action.get("category"), "content").lower()
        if category in {"contenu", "post", "publication"}:
            category = "content"
        elif category in {"profile", "bio", "biography", "profil/bio"}:
            category = "profil"
        action["category"] = category

        # Mode actuel du produit : aucune tâche manuelle/opérationnelle dans
        # une stratégie. Chaque action doit aboutir à un post planifiable.
        if category != "content" or not action["requires_post_generation"]:
            continue
        operational_blob = " ".join(_text(action.get(key)).lower() for key in (
            "title", "description", "deliverable", "format", "angle"
        ))
        if re.search(
            r"cr[eé]er (?:un |le )?(?:calendrier|planning)|calendrier [eé]ditorial|"
            r"configurer|mettre en place (?:un |le )?(?:outil|tableau|tracking)|"
            r"(?:faire|r[eé]aliser|effectuer|lancer|mener) (?:un |l['’])?audit|"
            r"audit(?:er)? (?:le |la |les |un |une )?(?:profil|compte|performance|r[eé]sultats)|"
            r"(?:cr[eé]er|faire|mettre en place) (?:un |le )?reporting|"
            r"(?:cr[eé]er|mettre en place) (?:un |le )?tableau de bord|modifier (?:la |le )?(?:bio|profil)",
            operational_blob,
        ):
            continue

        profile_update = _dict(action.get("profile_update"))
        profile_update["change_needed"] = _bool(profile_update.get("change_needed"), False)
        profile_update["current_text"] = _text(profile_update.get("current_text"))
        profile_update["reason"] = _text(profile_update.get("reason"))
        profile_update["proposed_text"] = _text(profile_update.get("proposed_text"))
        if category == "profil" or profile_update["change_needed"]:
            # Sans bio réellement récupérée, on ne peut pas conclure qu'elle doit être modifiée.
            if not biography_available:
                continue
            action["category"] = "profil"
            action["requires_post_generation"] = False
            profile_update["current_text"] = biography
            if not profile_update["change_needed"]:
                # Une action profil sans changement nécessaire n'apporte aucun livrable.
                continue
            if not profile_update["proposed_text"]:
                raise AIContractError(f"L'action profil « {action['title']} » ne contient pas proposed_text.")
        action["profile_update"] = profile_update

        calendar = _dict(action.get("calendar_slot"))
        calendar["recommended_offset_days"] = _int(calendar.get("recommended_offset_days"), 1, duration, action["due_day"])
        calendar["recommended_hour"] = _int(calendar.get("recommended_hour"), 7, 21, 11)
        calendar["spacing_group"] = _enum(
            calendar.get("spacing_group"),
            {"quick_win", "proof", "education", "conversion", "measurement"},
            "education",
        )
        action["calendar_slot"] = calendar

        media = _dict(action.get("media_prefill"))
        media_type = _enum(media.get("media_type"), {"image", "video"}, "image")
        media["media_type"] = media_type
        media["image_styles"] = [x for x in _string_list(media.get("image_styles"), limit=2) if x in _ALLOWED_IMAGE_STYLES]
        media["video_styles"] = [x for x in _string_list(media.get("video_styles"), limit=2) if x in _ALLOWED_VIDEO_STYLES]
        media["aspect_ratio"] = _enum(media.get("aspect_ratio"), {"1:1", "4:5", "9:16", "16:9"}, "9:16" if media_type == "video" else "4:5")
        media["instructions"] = _text(media.get("instructions"))
        media["video_scenario_text"] = _text(media.get("video_scenario_text")) if media_type == "video" else ""
        action["media_prefill"] = media
        action["kpi"] = _dict(action.get("kpi"))
        actions.append(action)

    return {"strategy": strategy, "actions": actions}



def normalize_strategy_plan(parsed: Any, context: dict | None = None) -> dict:
    """Valide la partie stratégie + un plan d'actions compact.

    Les actions détaillées sont générées séparément par petits lots afin qu'une
    stratégie longue ne puisse plus être tronquée au milieu d'un énorme JSON.
    """
    context = context or {}
    data = _dict(parsed)
    base = normalize_strategy({"strategy": data.get("strategy"), "actions": []}, context)
    strategy = base["strategy"]

    form_data = _dict(context.get("form_data"))
    duration = _int(form_data.get("duration_days") or _dict(strategy.get("objective")).get("duration_days"), 1, 365, 30)
    network = _dict(context.get("network_snapshot"))
    biography_available = _bool(network.get("biography_available"), False)

    blueprints: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(_list(data.get("action_blueprints"))):
        item = deepcopy(_dict(raw))
        if not item:
            continue
        plan_id = _text(item.get("plan_id") or f"a{index + 1}")
        if not plan_id or plan_id in seen:
            raise AIContractError("Chaque action_blueprint doit avoir un plan_id unique.")
        seen.add(plan_id)
        title = _text(item.get("title"))
        reason = _text(item.get("reason") or item.get("evidence"))
        if not title or not reason:
            raise AIContractError(f"Le blueprint {plan_id} doit contenir title et reason.")
        category = _text(item.get("category"), "content").lower()
        if category in {"contenu", "post", "publication"}:
            category = "content"
        elif category in {"profile", "bio", "biography", "profil/bio"}:
            category = "profil"
        requires_post = _bool(item.get("requires_post_generation"), category == "content")
        if category != "content" or not requires_post:
            continue
        blueprints.append({
            **item,
            "plan_id": plan_id,
            "title": title,
            "reason": reason,
            "category": category,
            "priority": _enum(item.get("priority"), {"low", "medium", "high"}, "medium"),
            "due_day": _int(item.get("due_day"), 1, duration, min(duration, index + 1)),
            "requires_post_generation": True,
        })

    if not strategy["objective_already_reached"] and not blueprints:
        raise AIContractError("L'objectif n'est pas indiqué comme atteint : action_blueprints ne peut pas être vide.")

    minimum_actions = _int(context.get("minimum_action_count"), 0, duration, 0)
    if not strategy["objective_already_reached"] and len(blueprints) < minimum_actions:
        raise AIContractError(
            f"Plan trop court : {len(blueprints)} action(s), {minimum_actions} requises "
            "pour assurer au moins trois posts par semaine."
        )

    # Une stratégie de N jours ne peut matériellement pas avoir davantage d'actions
    # quotidiennes distinctes que de jours. Cette borne dépend donc de l'horizon,
    # elle n'est pas un quota éditorial arbitraire.
    if len(blueprints) > duration:
        raise AIContractError(
            f"Trop d'actions planifiées ({len(blueprints)}) pour une durée de {duration} jours."
        )

    return {"strategy": strategy, "action_blueprints": blueprints}


def normalize_strategy_action_batch(parsed: Any, context: dict | None = None) -> dict:
    """Valide un petit lot d'actions et exige une correspondance 1:1 avec le plan."""
    context = context or {}
    blueprints = _list(context.get("blueprints"))
    expected_ids = [_text(_dict(bp).get("plan_id")) for bp in blueprints]
    expected_ids = [value for value in expected_ids if value]
    data = _dict(parsed)
    raw_actions = _list(data.get("actions"))
    if len(raw_actions) != len(expected_ids):
        raise AIContractError(
            f"Lot d'actions incomplet : {len(raw_actions)} reçu(s), {len(expected_ids)} attendu(s)."
        )

    # Les champs de pilotage viennent du plan déjà validé. Le modèle détaille
    # le contenu mais ne doit pas pouvoir faire échouer tout le lot en modifiant
    # accidentellement un plan_id, une date, une catégorie ou le booléen post.
    reconciled_actions: list[dict] = []
    for raw_action, raw_blueprint in zip(raw_actions, blueprints):
        action = deepcopy(_dict(raw_action))
        blueprint = _dict(raw_blueprint)
        for field in (
            "plan_id", "title", "category", "priority", "due_day",
            "requires_post_generation",
        ):
            action[field] = blueprint.get(field)
        reconciled_actions.append(action)

    strategy = _dict(context.get("strategy"))
    normalized = normalize_strategy({"strategy": strategy, "actions": reconciled_actions}, context)
    actions = normalized["actions"]
    if len(actions) != len(expected_ids):
        raise AIContractError(
            "Une ou plusieurs actions ont été rejetées par les règles métier du profil/contrat."
        )

    received_ids = [_text(action.get("plan_id")) for action in actions]
    if received_ids != expected_ids:
        raise AIContractError(
            f"plan_id du lot invalide : reçu {received_ids}, attendu {expected_ids}."
        )

    return {"actions": actions}

def _worker_text(value: Any, maximum: int = 12000) -> str:
    return str(value if value is not None else "").strip()[:maximum]


def _worker_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item if item is not None else "").strip() for item in value if str(item if item is not None else "").strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,;\n]", value) if item.strip()]
    return []


def _worker_score(value: Any, fallback: int) -> float | int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    number = max(0, min(10, number))
    return int(number) if number.is_integer() else number


def _worker_hashtag(value: Any) -> str:
    clean = str(value if value is not None else "").strip()
    clean = re.sub(r"^#+", "", clean)
    clean = re.sub(r"\s+", "", clean)
    return "#" + clean if clean else ""


def _worker_extract_ideas(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    data = _dict(parsed)
    if isinstance(data.get("ideas"), list):
        return data["ideas"]
    for key in ("posts", "post_ideas", "items", "results", "data"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def normalize_worker_post(parsed: Any, context: dict | None = None) -> dict:
    """Port strict de « Worker - Parse ready post » du workflow n8n V90."""
    ctx = context or {}
    ideas = _worker_extract_ideas(parsed)
    if not ideas or not isinstance(ideas[0], dict):
        raise AIContractError("OpenRouter n’a retourné aucune idée exploitable.")

    source = deepcopy(ideas[0])
    ready = _dict(source.get("ready_post"))
    post_text = _worker_text(
        ready.get("text") or source.get("post_text") or source.get("text") or source.get("content"),
        5000,
    )
    if len(post_text) < 120:
        raise AIContractError("ready_post.text est absent ou trop court.")

    forbidden = (
        "objectif stratégique :",
        "action à transformer en contenu :",
        "livrable attendu :",
        "contrainte de planning ia :",
        "persona :",
        "post depuis stratégie :",
    )
    lowered = post_text.lower()
    for marker in forbidden:
        if marker in lowered:
            raise AIContractError(f"Le texte généré contient une instruction interne : {marker}")

    if _worker_text(ctx.get("prompt"), 5000) == post_text or _worker_text(ctx.get("subject"), 500) == post_text:
        raise AIContractError("OpenRouter a recopié le prompt ou le sujet au lieu de rédiger un post.")

    action = _worker_text(ready.get("simple_action") or source.get("call_to_action") or source.get("cta"), 300)
    if not action:
        action = "Commentez DÉMO pour recevoir un exemple concret."
    action_key = re.sub(r"[.!?]+$", "", action.lower()).strip()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", post_text) if part.strip()]
    while paragraphs and re.sub(r"[.!?]+$", "", paragraphs[-1].lower()).strip() == action_key:
        paragraphs.pop()
    post_text = "\n\n".join([*paragraphs, action]).strip()

    tag_seed = _worker_list(ready.get("tags"))
    if not tag_seed:
        tag_seed = _worker_list(source.get("hashtags"))
    tags: list[str] = []
    for value in tag_seed:
        tag = _worker_hashtag(value)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 10:
            break
    while len(tags) < 5:
        for fallback in ("#Stratégie", "#Contenu", "#Business", "#Innovation", "#Productivité"):
            if fallback not in tags:
                tags.append(fallback)
            if len(tags) >= 5:
                break

    audience = ctx.get("target_audience")
    if isinstance(audience, list):
        audience = ", ".join(str(v) for v in audience)
    preferred = ctx.get("preferred_formats")
    if isinstance(preferred, list):
        preferred = preferred[0] if preferred else ""

    idea = {
        **source,
        "title": _worker_text(source.get("title") or ready.get("title") or "Idée de post", 180),
        "hook": _worker_text(source.get("hook") or source.get("title") or post_text[:160], 280),
        "summary": _worker_text(source.get("summary") or post_text[:600], 1200),
        "target_sector": _worker_text(source.get("target_sector") or ctx.get("target_sector") or "", 180),
        "target_audience": _worker_text(source.get("target_audience") or audience or "", 260),
        "recommended_format": _worker_text(source.get("recommended_format") or preferred or "Post", 100),
        "call_to_action": action,
        "hashtags": tags,
        "seo_keywords": _worker_list(source.get("seo_keywords"))[:12],
        "virality_score": _worker_score(source.get("virality_score"), 7),
        "commercial_potential_score": _worker_score(source.get("commercial_potential_score"), 8),
        "implementation_difficulty_score": _worker_score(source.get("implementation_difficulty_score"), 3),
        "sme_interest_score": _worker_score(source.get("sme_interest_score"), 8),
        "enterprise_interest_score": _worker_score(source.get("enterprise_interest_score"), 7),
        "lead_generation_score": _worker_score(source.get("lead_generation_score"), 8),
        "ready_post": {
            **ready,
            "title": _worker_text(ready.get("title") or source.get("title") or "Post prêt à publier", 180),
            "text": post_text,
            "simple_action": action,
            "tags": tags,
        },
        "generation_source": "calendar_clean_openrouter_v1",
    }
    return {"ideas": [idea]}


def parse_worker_post_response(value: Any, context: dict | None = None) -> dict:
    """Parsing JSON strict calqué sur parseJson() du nœud n8n Worker V90."""
    if isinstance(value, (dict, list)):
        parsed = value
    else:
        raw = _worker_text(value, 60000)
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw, flags=re.I).strip()
        if not raw:
            raise AIContractError("OpenRouter a retourné une réponse vide.")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end <= start:
                raise AIContractError("La réponse OpenRouter n’est pas un JSON exploitable.")
            try:
                parsed = json.loads(raw[start:end + 1])
            except (json.JSONDecodeError, TypeError) as exc:
                raise AIContractError("La réponse OpenRouter n’est pas un JSON exploitable.") from exc
    return normalize_worker_post(parsed, context)
