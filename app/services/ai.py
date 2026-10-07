"""Client OpenRouter avec sortie JSON structurée, retry anti-troncature et validation métier."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from app.config import get_settings
from app.services import prompts
from app.services import strategy_n8n_prompts
from app.services.ai_contracts import (
    AIContractError,
    normalize_filter_news,
    normalize_generate_ideas,
    normalize_modify_idea,
    normalize_reformulate_prompt,
    normalize_strategy,
    normalize_strategy_action_batch,
    normalize_strategy_plan,
    normalize_worker_post,
)

logger = logging.getLogger("services.ai")


class AIGenerationError(Exception):
    pass


@dataclass
class AIResult:
    parsed: dict
    raw_text: str


@dataclass
class _Completion:
    content: str
    finish_reason: str | None
    usage: dict[str, Any]
    json_mode_used: bool


def _strip_markdown_fences(text: str) -> str:
    t = str(text or "").strip().lstrip("\ufeff")
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _extract_json_candidate(text: str) -> str:
    """Retire le texte parasite autour d'un objet/tableau JSON complet sans inventer sa fin."""
    t = _strip_markdown_fences(text)
    object_start = t.find("{")
    array_start = t.find("[")
    starts = [pos for pos in (object_start, array_start) if pos >= 0]
    if not starts:
        return t
    start = min(starts)
    opener = t[start]
    closer = "}" if opener == "{" else "]"
    end = t.rfind(closer)
    return t[start:end + 1].strip() if end > start else t[start:].strip()


def _looks_truncated(candidate: str, exc: json.JSONDecodeError | None, finish_reason: str | None) -> bool:
    reason = str(finish_reason or "").lower()
    if reason in {"length", "max_tokens", "max_output_tokens"}:
        return True
    if not candidate:
        return True
    # Si l'erreur se trouve à la toute fin du flux, c'est typiquement une chaîne,
    # une valeur ou une accolade coupée par la limite de tokens.
    if exc is not None and exc.pos >= max(0, len(candidate) - 160):
        return True
    stripped = candidate.rstrip()
    if stripped.startswith("{") and not stripped.endswith("}"):
        return True
    if stripped.startswith("[") and not stripped.endswith("]"):
        return True
    return False


async def _post_openrouter(client: httpx.AsyncClient, payload: dict[str, Any], api_key: str) -> httpx.Response:
    """Deux essais uniquement sur erreur réseau, timeout, 429 ou 5xx."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if (response.status_code == 429 or response.status_code >= 500) and attempt == 0:
                await asyncio.sleep(1.0)
                continue
            return response
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(1.0)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise AIGenerationError("OpenRouter n'a retourné aucune réponse HTTP.")


async def _call_openrouter(
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool = True,
    model: str | None = None,
) -> _Completion:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise AIGenerationError("OPENROUTER_API_KEY manquante")

    selected_model = str(model or settings.openrouter_model).strip() or settings.openrouter_model
    payload: dict[str, Any] = {
        "model": selected_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        # JSON mode + Response Healing : le routeur impose un objet JSON et
        # répare les petites erreurs de syntaxe (virgule/quote/markdown). Une
        # vraie troncature max_tokens reste détectée et régénérée par _run_agent.
        payload["response_format"] = {"type": "json_object"}
        payload["plugins"] = [{"id": "response-healing"}]

    async with httpx.AsyncClient(base_url=settings.openrouter_base_url, timeout=180) as client:
        response = await _post_openrouter(client, payload, settings.openrouter_api_key)
        json_mode_used = json_mode

        # Certains modèles configurables ne supportent pas response_format. Dans
        # ce seul cas on retente immédiatement sans JSON mode, les validateurs
        # serveur restant actifs.
        if json_mode and response.status_code in {400, 404, 422}:
            body = response.text.lower()
            if "response_format" in body or "json" in body or "structured" in body:
                logger.warning("OpenRouter: response_format non supporté par %s, fallback sans JSON mode", selected_model)
                payload.pop("response_format", None)
                response = await _post_openrouter(client, payload, settings.openrouter_api_key)
                json_mode_used = False

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1200]
            raise AIGenerationError(f"OpenRouter HTTP {response.status_code}: {detail}") from exc

        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(str(part.get("text") or "") if isinstance(part, dict) else str(part) for part in content)
            if not isinstance(content, str) or not content.strip():
                raise ValueError("message.content vide")
            return _Completion(
                content=content,
                finish_reason=choice.get("finish_reason"),
                usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
                json_mode_used=json_mode_used,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIGenerationError(f"Réponse OpenRouter invalide: {exc}; payload={response.text[:1000]}") from exc


Validator = Callable[[Any, dict | None], dict]


async def _run_agent(
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
    validator: Validator,
    context: dict | None = None,
    agent_name: str = "agent",
) -> AIResult:
    settings = get_settings()
    max_output = max(2048, int(getattr(settings, "openrouter_max_output_tokens", 12000) or 12000))
    attempts = max(1, min(4, int(getattr(settings, "openrouter_json_attempts", 3) or 3)))
    budget = min(max_output, max_tokens)
    failures: list[str] = []
    last_raw = ""

    for attempt in range(1, attempts + 1):
        retry_note = ""
        if attempt > 1:
            previous_failure = failures[-1] if failures else "réponse non conforme"
            retry_note = (
                "\n\nIMPORTANT — nouvelle tentative serveur : la réponse précédente était tronquée, "
                "mal formée ou non conforme. Régénère l'objet JSON COMPLET depuis le début. "
                "N'abrège aucun champ, ne termine jamais au milieu d'une chaîne et ferme tous les tableaux/objets. "
                f"Erreur précise à corriger : {previous_failure}."
            )
        try:
            completion = await _call_openrouter(
                system + retry_note,
                user,
                max_tokens=budget,
                temperature=temperature,
                json_mode=True,
            )
        except AIGenerationError as exc:
            failures.append(f"tentative {attempt}: appel OpenRouter: {exc}")
            if attempt >= attempts:
                break
            budget = min(max_output, max(budget + 2048, int(budget * 1.6)))
            continue
        except Exception as exc:  # noqa: BLE001
            failures.append(f"tentative {attempt}: appel OpenRouter inattendu: {exc}")
            if attempt >= attempts:
                break
            budget = min(max_output, max(budget + 2048, int(budget * 1.6)))
            continue

        last_raw = completion.content
        candidate = _extract_json_candidate(last_raw)
        parse_error: json.JSONDecodeError | None = None

        if str(completion.finish_reason or "").lower() in {"length", "max_tokens", "max_output_tokens"}:
            failures.append(
                f"tentative {attempt}: sortie tronquée (finish_reason={completion.finish_reason}, "
                f"budget={budget}, caractères={len(candidate)})"
            )
        else:
            try:
                parsed = json.loads(candidate)
                normalized = validator(parsed, context)
                logger.info(
                    "IA %s valide: tentative=%s budget=%s finish_reason=%s chars=%s json_mode=%s",
                    agent_name, attempt, budget, completion.finish_reason, len(candidate), completion.json_mode_used,
                )
                return AIResult(parsed=normalized, raw_text=last_raw)
            except json.JSONDecodeError as exc:
                parse_error = exc
                failures.append(
                    f"tentative {attempt}: JSON invalide à {exc.pos}/{len(candidate)}: {exc.msg} "
                    f"(finish_reason={completion.finish_reason})"
                )
            except AIContractError as exc:
                failures.append(f"tentative {attempt}: contrat invalide: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"tentative {attempt}: validation inattendue: {exc}")

        if attempt >= attempts:
            break

        # Toute erreur JSON/contrat est régénérée. Si elle ressemble à une
        # troncature, on augmente fortement le budget ; sinon on garde au moins
        # +2048 tokens pour laisser au modèle la place de respecter le contrat.
        truncated = _looks_truncated(candidate, parse_error, completion.finish_reason)
        budget = min(
            max_output,
            max(budget + 2048, int(budget * (1.8 if truncated else 1.4))),
        )

    preview_start = _extract_json_candidate(last_raw)[:700]
    preview_end = _extract_json_candidate(last_raw)[-350:] if last_raw else ""
    diagnostic = " | ".join(failures[-attempts:]) or "aucun diagnostic"
    raise AIGenerationError(
        f"{agent_name}: impossible d'obtenir un JSON complet et conforme après {attempts} tentative(s). "
        f"{diagnostic}. Début: {preview_start!r} Fin: {preview_end!r}"
    )


async def filter_news(context: dict) -> AIResult:
    return await _run_agent(
        prompts.FILTER_NEWS_SYSTEM,
        prompts.build_filter_news_prompt(context),
        max_tokens=1200, temperature=0.2,
        validator=normalize_filter_news, context=context, agent_name="filter_news",
    )


async def generate_ideas(context: dict) -> AIResult:
    try:
        count = max(1, min(8, int(context.get("post_count") or context.get("count") or 5)))
    except (TypeError, ValueError):
        count = 5
    # Le volume de sortie est proportionnel au nombre d'idées demandé.
    token_budget = min(12000, max(5000, 1800 + count * 1100))
    return await _run_agent(
        prompts.GENERATE_IDEAS_SYSTEM,
        prompts.build_generate_ideas_prompt(context),
        max_tokens=token_budget, temperature=0.75,
        validator=normalize_generate_ideas, context=context, agent_name="generate_ideas",
    )


async def modify_idea(idea: dict, instructions: str | None, context: dict | None = None) -> AIResult:
    validation_context = {**(context or {}), "recommended_format": (idea or {}).get("recommended_format", "")}
    return await _run_agent(
        prompts.MODIFY_IDEA_SYSTEM,
        prompts.build_modify_idea_prompt(idea, instructions, context or {}),
        max_tokens=3500, temperature=0.7,
        validator=normalize_modify_idea, context=validation_context, agent_name="modify_idea",
    )


async def reformulate_prompt(context: dict) -> AIResult:
    return await _run_agent(
        prompts.REFORMULATE_PROMPT_SYSTEM,
        prompts.build_reformulate_prompt(context),
        max_tokens=2200, temperature=0.4,
        validator=normalize_reformulate_prompt, context=context, agent_name="reformulate_prompt",
    )


async def _strategy_completion(system: str, user: str) -> _Completion:
    """Appel OpenRouter pour la stratégie avec budget suffisant et repli automatique."""
    settings = get_settings()
    max_tokens = max(int(getattr(settings, "openrouter_strategy_max_tokens", 5000) or 5000), 4500)
    temperature = float(getattr(settings, "openrouter_strategy_temperature", 0.3) or 0.3)
    primary_model = str(getattr(settings, "openrouter_strategy_model", "") or settings.openrouter_model or "openai/gpt-4o-mini").strip()
    fallback_model = str(settings.openrouter_model or "openai/gpt-4o-mini").strip()

    try:
        return await _call_openrouter(
            system,
            user,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=False,
            model=primary_model,
        )
    except AIGenerationError as exc:
        if primary_model != fallback_model:
            logger.warning("Strategy generation with %s failed (%s), falling back to %s", primary_model, exc, fallback_model)
            return await _call_openrouter(
                system,
                user,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=False,
                model=fallback_model,
            )
        raise


def _strategy_parse_any(value: Any) -> tuple[dict, str]:
    """Équivalent du parseJson/parseAny des nœuds V54/V56 n8n."""
    current = value
    for _ in range(5):
        if isinstance(current, dict):
            data = current
        else:
            raw = str(current or "").strip().lstrip("\ufeff")
            raw = raw.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'").replace("\x00", "")
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
            raw = re.sub(r"\s*```\s*$", "", raw, flags=re.I).strip()
            first, last = raw.find("{"), raw.rfind("}")
            if first >= 0 and last > first:
                raw = raw[first:last + 1]
            try:
                data = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                return {}, str(exc)
            if not isinstance(data, dict):
                return {}, "La réponse JSON n'est pas un objet."
        if isinstance(data.get("actions"), list) or isinstance(data.get("strategy"), dict):
            return data, ""
        nested = next((data.get(k) for k in ("output", "result", "response", "content", "data", "json")
                       if isinstance(data.get(k), (str, dict))), None)
        if nested is None:
            return data, ""
        current = nested
    return {}, "Profondeur JSON dépassée"


def _strategy_number(value: Any) -> float | None:
    raw = str(value if value is not None else "").replace("\u00a0", "").replace(" ", "").replace("_", "").replace(",", ".")
    raw = raw.replace(".", "", raw.count(".") - 1) if raw.count(".") > 1 else raw
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _strategy_target_followers(context: dict) -> int | None:
    form = context.get("form_data") if isinstance(context.get("form_data"), dict) else {}
    growth = form.get("growth_target") if isinstance(form.get("growth_target"), dict) else {}
    for value in (growth.get("target_absolute"), growth.get("target_value"), form.get("target_value")):
        n = _strategy_number(value)
        if n is not None and n > 0:
            return round(n)
    blob = " ".join(str(form.get(k) or "") for k in ("profile_goal", "instructions", "objective_label")) + " " + str(growth.get("summary") or "")
    match = re.search(r"(\d[\d\s\u00a0._]{0,14})\s*(?:abonn[eé]s?|followers?)", blob, flags=re.I)
    if match:
        n = _strategy_number(match.group(1))
        return round(n) if n is not None else None
    return None


def _strategy_current_followers(context: dict) -> int | None:
    profile_snapshot = context.get("profile_snapshot") if isinstance(context.get("profile_snapshot"), dict) else {}
    profile = profile_snapshot.get("profile") if isinstance(profile_snapshot.get("profile"), dict) else {}
    n = _strategy_number(profile.get("followers_count"))
    return round(n) if n is not None else None


def _strategy_objective_unmet(context: dict) -> bool:
    target = _strategy_target_followers(context)
    current = _strategy_current_followers(context)
    return True if target is None else (current is None or current < target)


def _strategy_low_value(action: dict) -> bool:
    blob = " ".join(str(action.get(k) or "") for k in ("title", "description", "deliverable", "format", "cta"))
    blob = blob.lower()
    return bool(re.search(r"routine d.?interaction|commentaires cibles|repondre a des conversations|répondre à des conversations|commenter des comptes|liker|suivre des comptes|engagement quotidien", blob))


def _strategy_is_publishable_post_action(action: dict) -> bool:
    """Le produit ne planifie temporairement que des contenus publiables."""
    category = str(action.get("category") or "").strip().lower()
    requires_post = action.get("requires_post_generation") is True or str(
        action.get("requires_post_generation") or ""
    ).strip().lower() == "true"
    blob = " ".join(str(action.get(k) or "") for k in (
        "title", "description", "deliverable", "format", "angle"
    )).lower()
    operational_task = bool(re.search(
        r"cr[eé]er (?:un |le )?(?:calendrier|planning)|calendrier [eé]ditorial|"
        r"configurer|mettre en place (?:un |le )?(?:outil|tableau|tracking)|"
        r"(?:faire|r[eé]aliser|effectuer|lancer|mener) (?:un |l['’])?audit|"
        r"audit(?:er)? (?:le |la |les |un |une )?(?:profil|compte|performance|r[eé]sultats)|"
        r"(?:cr[eé]er|faire|mettre en place) (?:un |le )?reporting|"
        r"(?:cr[eé]er|mettre en place) (?:un |le )?tableau de bord|modifier (?:la |le )?(?:bio|profil)",
        blob,
    ))
    return requires_post and category in {"content", "contenu", "post", "publication"} and not operational_task


def _strategy_is_profile_action(action: dict) -> bool:
    blob = " ".join(str(action.get(k) or "") for k in ("category", "title", "description", "deliverable", "output_type")).lower()
    return bool(re.search(r"(^|\b)(profil|profile|bio|biographie|biography)(\b|$)", blob))


def _strategy_profile_action_valid(action: dict, context: dict) -> bool:
    if not _strategy_is_profile_action(action):
        return True
    snap = context.get("profile_snapshot") if isinstance(context.get("profile_snapshot"), dict) else {}
    profile = snap.get("profile") if isinstance(snap.get("profile"), dict) else {}
    update = action.get("profile_update") if isinstance(action.get("profile_update"), dict) else {}
    available = profile.get("biography_available") is True
    change_needed = update.get("change_needed") is True or str(update.get("change_needed") or "").lower() == "true"
    proposed = str(update.get("proposed_text") or action.get("proposed_bio") or action.get("proposed_profile_text") or "").strip()
    reason = str(update.get("reason") or action.get("evidence") or "").strip()
    return bool(available and change_needed and proposed and reason)


def _strategy_usable_actions(parsed: dict, context: dict) -> tuple[list[dict], list[dict]]:
    actions = [a for a in (parsed.get("actions") or []) if isinstance(a, dict)] if isinstance(parsed.get("actions"), list) else []
    candidates = [a for a in actions if str(a.get("title") or "").strip() and not _strategy_low_value(a)]
    invalid = [a for a in candidates if not _strategy_is_publishable_post_action(a)]
    usable = [a for a in candidates if _strategy_is_publishable_post_action(a)]
    return usable, invalid


def _strategy_context_for_normalizer(context: dict) -> dict:
    # Le normaliseur historique Python sait aussi lire network_snapshot. On lui
    # fournit les deux formes sans changer le contexte envoyé à l'IA n8n.
    out = dict(context)
    snap = context.get("profile_snapshot") if isinstance(context.get("profile_snapshot"), dict) else {}
    profile = snap.get("profile") if isinstance(snap.get("profile"), dict) else {}
    out["network_snapshot"] = {
        "profile": profile,
        "biography_available": profile.get("biography_available") is True,
    }
    return out


async def generate_strategy(context: dict) -> AIResult:
    """Génère le plan puis les actions par petits lots parallèles.

    Ce découpage permet d'imposer au moins trois posts par semaine sans demander
    au modèle un unique JSON gigantesque et fragile.
    """
    normalized_context = _strategy_context_for_normalizer(context)
    form_data = context.get("form_data") if isinstance(context.get("form_data"), dict) else {}
    try:
        duration = max(1, min(365, int(form_data.get("duration_days") or 30)))
    except (TypeError, ValueError):
        duration = 30
    minimum_actions = min(duration, ((duration + 6) // 7) * 3)
    plan_context = {**normalized_context, "minimum_action_count": minimum_actions}

    plan_result = await _run_agent(
        prompts.GENERATE_STRATEGY_PLAN_SYSTEM,
        prompts.build_generate_strategy_plan_prompt(plan_context),
        max_tokens=8000,
        temperature=0.3,
        validator=normalize_strategy_plan,
        context=plan_context,
        agent_name="strategy_plan",
    )
    strategy = plan_result.parsed["strategy"]
    blueprints = plan_result.parsed["action_blueprints"]
    if not blueprints:
        return AIResult(parsed={"strategy": strategy, "actions": []}, raw_text=plan_result.raw_text)

    batches = [blueprints[index:index + 4] for index in range(0, len(blueprints), 4)]
    batch_semaphore = asyncio.Semaphore(3)

    async def generate_batch(batch: list[dict]) -> AIResult:
        batch_context = {
            **normalized_context,
            "strategy": strategy,
            "blueprints": batch,
        }
        async with batch_semaphore:
            return await _run_agent(
                prompts.GENERATE_STRATEGY_ACTIONS_SYSTEM,
                prompts.build_generate_strategy_actions_prompt(
                    context=normalized_context, strategy=strategy, blueprints=batch,
                ),
                max_tokens=5000,
                temperature=0.3,
                validator=normalize_strategy_action_batch,
                context=batch_context,
                agent_name="strategy_actions_batch",
            )

    batch_results = await asyncio.gather(*(generate_batch(batch) for batch in batches))
    actions = [action for result in batch_results for action in result.parsed["actions"]]
    if len(actions) < minimum_actions:
        raise AIGenerationError(
            f"PROGRAMME_STRATEGIE_INCOMPLET : {len(actions)} actions reçues, {minimum_actions} requises."
        )
    combined = {"strategy": strategy, "actions": actions}
    return AIResult(parsed=combined, raw_text=json.dumps(combined, ensure_ascii=False))


async def generate_strategy_legacy(context: dict) -> AIResult:
    """Ancien pipeline monolithique conservé temporairement pour diagnostic."""
    first = await _strategy_completion(
        strategy_n8n_prompts.PRIMARY_SYSTEM,
        strategy_n8n_prompts.primary_prompt(context),
    )
    first_parsed, first_error = _strategy_parse_any(first.content)
    first_usable, first_invalid_profile = _strategy_usable_actions(first_parsed, context)
    need_retry = bool(
        first_error
        or first_invalid_profile
        or (_strategy_objective_unmet(context) and not first_usable)
    )

    chosen = first_parsed
    raw_final = first.content
    if need_retry:
        reason = (
            "Réponse JSON IA invalide ou tronquée."
            if first_error else
            "Une ou plusieurs actions ne génèrent pas un post publiable. Toutes les actions doivent être des contenus planifiables."
            if first_invalid_profile else
            "Objectif non atteint mais aucun programme d’actions exploitable."
        )
        second = await _strategy_completion(
            strategy_n8n_prompts.RETRY_SYSTEM,
            strategy_n8n_prompts.retry_prompt(context, first.content, reason),
        )
        second_parsed, second_error = _strategy_parse_any(second.content)
        second_usable, second_invalid_profile = _strategy_usable_actions(second_parsed, context)
        second_valid = bool(second_usable and not second_invalid_profile and not second_error)
        if second_valid:
            chosen = second_parsed
            raw_final = second.content
        else:
            action_pass = await _strategy_completion(
                strategy_n8n_prompts.ACTIONS_SYSTEM,
                strategy_n8n_prompts.actions_prompt(
                    context,
                    first.content,
                    second.content,
                    _strategy_current_followers(context),
                    _strategy_target_followers(context),
                ),
            )
            action_parsed, action_error = _strategy_parse_any(action_pass.content)
            action_usable, action_invalid_profile = _strategy_usable_actions(action_parsed, context)
            action_usable = [a for a in action_usable if _strategy_profile_action_valid(a, context)]
            if action_error or not action_usable:
                raise AIGenerationError(
                    "ACTIONS_IA_DEDIEE_VIDE : la passe IA dédiée aux actions a renvoyé zéro action exploitable. "
                    f"parse_error={action_error or 'aucune'}"
                )
            base_strategy = {}
            for candidate in (second_parsed, first_parsed):
                if isinstance(candidate.get("strategy"), dict) and candidate.get("strategy"):
                    base_strategy = candidate["strategy"]
                    break
            if not base_strategy:
                raise AIGenerationError(
                    "STRATEGIE_IA_INEXPLOITABLE : les deux passes de stratégie n'ont fourni aucun objet strategy JSON exploitable."
                )
            chosen = {"strategy": base_strategy, "actions": action_usable}
            raw_final = json.dumps(chosen, ensure_ascii=False)

    # Comme le parser n8n : on supprime les routines de faible valeur et les
    # actions profil impossibles à justifier avant la sauvegarde.
    usable, _ = _strategy_usable_actions(chosen, context)
    usable = [a for a in usable if _strategy_profile_action_valid(a, context)]
    chosen = {"strategy": chosen.get("strategy") or {}, "actions": usable}
    if _strategy_objective_unmet(context) and not usable:
        raise AIGenerationError("PROGRAMME_STRATEGIE_IA_VIDE : objectif non atteint mais aucune action exploitable.")
    try:
        normalized = normalize_strategy(chosen, _strategy_context_for_normalizer(context))
    except AIContractError as exc:
        raise AIGenerationError(f"Parser stratégie IA : {exc}") from exc
    return AIResult(parsed=normalized, raw_text=raw_final)


async def retry_strategy(strategy_context: dict, first_output: str, retry_reason: str) -> AIResult:
    """Compatibilité API : la logique de retry n8n est déjà incluse dans generate_strategy."""
    return await generate_strategy(strategy_context)


async def generate_worker_post(
    *, subject: str, commercial_objective: str, target_sector: str, language: str,
    preferred_formats: list, target_audience: list, constraints: str, prompt: str,
) -> AIResult:
    """Port du nœud n8n « Worker - Generate with OpenRouter ».

    Ce nœud fait un seul appel modèle avec maxTokens=2600 et temperature=0.65.
    Le parsing/contrôle de la réponse appartient à l'étape suivante du worker,
    comme dans n8n ; une réponse JSON mal formée devient donc une erreur parser
    et non une nouvelle génération OpenRouter interne.
    """
    user_prompt = prompts.build_worker_generate_prompt(
        subject=subject,
        commercial_objective=commercial_objective,
        target_sector=target_sector,
        language=language,
        preferred_formats=preferred_formats,
        target_audience=target_audience,
        constraints=constraints,
        prompt=prompt,
    )
    try:
        completion = await _call_openrouter(
            prompts.WORKER_GENERATE_SYSTEM,
            user_prompt,
            max_tokens=2600,
            temperature=0.65,
            json_mode=False,
        )
    except AIGenerationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIGenerationError(f"Worker OpenRouter : {exc}") from exc
    return AIResult(parsed={}, raw_text=completion.content)
