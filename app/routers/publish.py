"""Publication multi-réseaux : immédiate ou planifiée.

La planification est locale : une demande ``scheduled`` est enregistrée en
BDD puis exécutée par ``publication_cron`` à l'heure prévue. Aucune API Meta
n'est appelée au moment où l'utilisateur clique sur « Programmer ».
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.database import get_pool
from app.dependencies.auth import require_auth
from app.services.publishing import final_post_text, media_kind, outcome_error, publish_to_account
from app.user_timezone import parse_user_datetime

router = APIRouter(tags=["Publish"])


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_scheduled_at(value: str | None, timezone_name: str) -> datetime | None:
    try:
        return parse_user_datetime(value, timezone_name)
    except ValueError:
        return None


def _infer_content_type(platform: str, media_type: str, target: dict, raw_idea: dict) -> str:
    explicit = str(target.get("publish_content_type") or "").strip().lower()
    if explicit in ("standard", "post"):
        return "standard"
    if explicit in ("reel", "story"):
        return explicit
    recommended = str(raw_idea.get("recommended_format") or "").lower()
    if "story" in recommended:
        return "story"
    if "reel" in recommended:
        return "reel"
    if platform == "instagram" and media_type == "video":
        return "reel"
    return "standard"


def _validate_publication_combination(provider: str, platform: str, content_type: str,
                                      media_type: str, metadata: dict) -> str | None:
    """Return the V90 capability-matrix error, or ``None`` when supported."""
    provider = str(provider or "").strip().lower()
    platform = str(platform or "").strip().lower()
    content_type = "standard" if str(content_type or "").strip().lower() in ("", "post", "standard") else str(content_type).strip().lower()
    media_type = str(media_type or "none").strip().lower() or "none"
    connection = str((metadata or {}).get("connection_provider") or "").strip().lower()
    service = str((metadata or {}).get("service") or "").strip().lower()
    is_buffer = provider == "buffer" or connection == "buffer"

    if is_buffer:
        if platform == "linkedin":
            if content_type != "standard":
                return "LinkedIn via Buffer accepte uniquement le type Post dans ce workflow."
            if media_type not in ("none", "image", "video"):
                return "Le média LinkedIn sélectionné est invalide."
            return None
        if platform == "instagram":
            if content_type == "standard":
                return None if media_type in ("image", "video") else "Un Post Instagram via Buffer nécessite une image ou une vidéo."
            if content_type == "reel":
                return None if media_type == "video" else "Un Reel Instagram via Buffer nécessite une vidéo."
            if content_type == "story":
                return None if media_type in ("image", "video") else "Une Story Instagram via Buffer nécessite une image ou une vidéo."
            return "Type de publication Instagram Buffer invalide."
        if platform == "facebook":
            if content_type == "story":
                return "La Story Facebook n’est pas exposée dans ce workflow Buffer."
            if content_type == "reel":
                return None if media_type == "video" else "Un Reel Facebook via Buffer nécessite une vidéo."
            if content_type == "standard":
                return None if media_type in ("none", "image", "video") else "Le média Facebook sélectionné est invalide."
            return "Type de publication Facebook Buffer invalide."
        return "Ce réseau n’est pas pris en charge par la branche Buffer du workflow."

    if provider == "instagram" and platform == "instagram":
        if content_type == "standard":
            return None if media_type == "image" else "Un Post Instagram direct nécessite une image accessible par URL HTTPS publique."
        if content_type == "reel":
            return None if media_type == "video" else "Un Reel Instagram direct nécessite une vidéo."
        if content_type == "story":
            return None if media_type in ("image", "video") else "Une Story Instagram directe nécessite une image ou une vidéo."
        return "Type de publication Instagram direct invalide."

    if provider == "facebook" and platform == "facebook":
        if content_type == "story":
            return "La Story Facebook Meta n’est pas implémentée dans ce workflow."
        if content_type == "reel":
            return None if media_type == "video" else "Un Reel Facebook Meta nécessite une vidéo."
        if content_type == "standard":
            return None if media_type in ("none", "image", "video") else "Le média Facebook sélectionné est invalide."
        return "Type de publication Facebook Meta invalide."

    # Preserve routing compatibility for legacy account metadata while refusing
    # combinations that the selected provider cannot identify.
    if service and platform and platform not in service and provider == "buffer":
        return f"Le canal Buffer sélectionné ne correspond pas à {platform}."
    return None


@router.post("/post-ideas-publish")
async def post_ideas_publish(payload: dict = Body(...), user=Depends(require_auth)):
    idea_id = str(payload.get("idea_id") or "").strip()
    version_id = str(payload.get("version_id") or "").strip()
    media_id = str(payload.get("media_id") or "").strip() or None
    targets = payload.get("targets") if isinstance(payload.get("targets"), list) else []
    if not idea_id or not version_id or not targets:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Idée, version et au moins un réseau sont requis."}, status_code=422)

    pool = get_pool()
    async with pool.acquire() as conn:
        idea = await conn.fetchrow(
            """
            SELECT id::text, raw_idea
            FROM public.post_ideas
            WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL
            """,
            idea_id, user.active_workspace_id,
        )
        version = await conn.fetchrow(
            """
            SELECT id::text, post_text, hashtags, cta
            FROM public.post_versions
            WHERE id=$1::uuid AND idea_id=$2::uuid AND workspace_id=$3::uuid
            """,
            version_id, idea_id, user.active_workspace_id,
        )
        media = None
        if media_id:
            media = await conn.fetchrow(
                """
                SELECT id::text, public_url, external_url, media_type, status
                FROM public.post_media
                WHERE id=$1::uuid AND idea_id=$2::uuid AND workspace_id=$3::uuid
                """,
                media_id, idea_id, user.active_workspace_id,
            )

    if idea is None or version is None:
        return JSONResponse({"success": False, "error": "NOT_FOUND",
                             "message": "L'idée ou sa version courante est introuvable dans ce workspace."}, status_code=404)
    if media_id and (media is None or str(media["status"] or "") != "ready"):
        return JSONResponse({"success": False, "error": "MEDIA_NOT_READY",
                             "message": "Le média sélectionné n'est pas prêt ou n'appartient pas à cette idée."}, status_code=422)

    raw_idea = _json_object(idea["raw_idea"])
    final_text = final_post_text(
        raw_idea,
        version_text=str(version["post_text"] or ""),
        cta=str(version["cta"] or ""),
        hashtags=version["hashtags"],
    )
    media_url = (media["public_url"] or media["external_url"]) if media else None
    kind = media_kind(media)

    account_ids = list(dict.fromkeys(str(t.get("account_id") or "").strip() for t in targets if t.get("account_id")))
    accounts_by_id: dict[str, object] = {}
    if account_ids:
        async with pool.acquire() as conn:
            account_rows = await conn.fetch(
                """
                SELECT a.id::text, a.provider, a.external_account_id, a.external_parent_id,
                       a.token_ciphertext, a.metadata
                FROM public.app_social_accounts a
                LEFT JOIN public.app_social_account_workspaces saw
                  ON saw.account_id=a.id AND saw.workspace_id=$2::uuid
                WHERE a.id = ANY($1::uuid[]) AND a.deleted_at IS NULL AND a.is_active=true
                  AND (a.workspace_id=$2::uuid OR saw.account_id IS NOT NULL)
                  AND (
                    CASE WHEN saw.account_id IS NULL AND a.workspace_id=$2::uuid THEN true
                         ELSE COALESCE(saw.is_active,false) AND saw.revoked_at IS NULL END
                  ) = true
                """,
                account_ids, user.active_workspace_id,
            )
        accounts_by_id = {r["id"]: r for r in account_rows}

    results: list[dict] = []
    for target in targets:
        account_id = str(target.get("account_id") or "").strip()
        account = accounts_by_id.get(account_id)
        requested_provider = str(target.get("provider") or "").strip().lower()
        if account is None:
            results.append({"account_id": account_id, "provider": requested_provider,
                            "status": "failed", "error": "Compte social actif introuvable dans ce workspace."})
            continue

        transport_provider = str(account["provider"] or "").strip().lower()
        if requested_provider and requested_provider != transport_provider:
            results.append({"account_id": account_id, "provider": transport_provider,
                            "status": "failed", "error": "Le fournisseur du compte ne correspond pas à la sélection."})
            continue

        metadata = _json_object(account["metadata"])
        service = str(metadata.get("service") or "").strip().lower()
        platform = str(target.get("platform") or (service if transport_provider == "buffer" else transport_provider)).strip().lower()
        if not platform:
            platform = transport_provider
        content_type = _infer_content_type(platform, kind, target, raw_idea)
        combination_error = _validate_publication_combination(
            transport_provider, platform, content_type, kind, metadata,
        )
        if combination_error:
            results.append({"account_id": account_id, "provider": transport_provider, "platform": platform,
                            "status": "failed", "error": combination_error})
            continue
        publish_mode = "scheduled" if str(target.get("publish_mode") or "").lower() == "scheduled" else "immediate"
        scheduled_dt = _parse_scheduled_at(target.get("scheduled_at"), user.timezone) if publish_mode == "scheduled" else None
        if publish_mode == "scheduled" and (scheduled_dt is None or scheduled_dt <= datetime.now(timezone.utc)):
            results.append({"account_id": account_id, "provider": transport_provider, "platform": platform,
                            "status": "failed", "error": "La date de programmation doit être dans le futur."})
            continue

        base_response = {
            "social_account_id": account_id,
            "transport_provider": transport_provider,
            "platform": platform,
            "publish_content_type": content_type,
            "published_by_user_id": user.id,
            "user_timezone": user.timezone,
        }
        initial_status = "scheduled" if publish_mode == "scheduled" else "processing"
        async with pool.acquire() as conn:
            pub_row = await conn.fetchrow(
                """
                INSERT INTO public.post_publications (
                    idea_id, workspace_id, version_id, media_id, platform, publication_type,
                    status, publish_mode, scheduled_at, post_text_snapshot, hashtags_snapshot,
                    media_url_snapshot, response
                ) VALUES ($1::uuid,$2::uuid,$3::uuid,$4::uuid,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)
                RETURNING id::text AS publication_id
                """,
                idea_id, user.active_workspace_id, version_id, media_id, platform, content_type,
                initial_status, publish_mode, scheduled_dt, final_text, version["hashtags"], media_url,
                json.dumps(base_response),
            )

        publication_id = pub_row["publication_id"]
        if publish_mode == "scheduled":
            async with pool.acquire() as conn:
              async with conn.transaction():
                await conn.execute(
                    "UPDATE public.post_ideas SET status='scheduled', updated_at=now() "
                    "WHERE id=$1::uuid AND workspace_id=$2::uuid AND status <> 'published'",
                    idea_id, user.active_workspace_id,
                )
                await conn.execute(
                    """
                    INSERT INTO public.post_activity_logs (workspace_id, entity_type, entity_id, action, details)
                    VALUES ($1::uuid,'post_publication',$2::uuid,'scheduled',
                            jsonb_build_object('platform',$3::text,'scheduled_at',$4::text))
                    """,
                    user.active_workspace_id, publication_id, platform, scheduled_dt.isoformat(),
                )
            results.append({"account_id": account_id, "provider": transport_provider, "platform": platform,
                            "status": "scheduled", "publication_id": publication_id,
                            "scheduled_at": scheduled_dt.isoformat()})
            continue

        try:
            outcome = await publish_to_account(
                account, platform=platform, media_type=kind, media_url=media_url,
                text=final_text, publish_content_type=content_type,
            )
        except Exception as exc:  # noqa: BLE001
            outcome = {"error": str(exc)}
        error_message = outcome_error(outcome)
        status = "failed" if error_message else "published"
        response_payload = {**base_response, "provider_response": outcome}
        async with pool.acquire() as conn:
          async with conn.transaction():
            await conn.execute(
                """
                UPDATE public.post_publications
                SET status=$2, response=$3::jsonb, error_message=$4,
                    published_by=CASE WHEN $2='published' THEN $5::uuid ELSE published_by END,
                    published_at=CASE WHEN $2='published' THEN now() ELSE published_at END,
                    updated_at=now()
                WHERE id=$1::uuid
                """,
                publication_id, status, json.dumps(response_payload), error_message, user.id,
            )
            if status == "published":
                await conn.execute(
                    "UPDATE public.post_ideas SET status='published', updated_at=now() "
                    "WHERE id=$1::uuid AND workspace_id=$2::uuid",
                    idea_id, user.active_workspace_id,
                )
            await conn.execute(
                """
                INSERT INTO public.post_activity_logs (workspace_id, entity_type, entity_id, action, details)
                VALUES ($1::uuid,'post_publication',$2::uuid,$3,
                        jsonb_build_object('platform',$4::text,'error',$5::text))
                """,
                user.active_workspace_id, publication_id, status, platform, error_message or "",
            )
        results.append({"account_id": account_id, "provider": transport_provider, "platform": platform,
                        "status": status, "publication_id": publication_id, "error": error_message})

    has_success = any(r.get("status") in ("published", "scheduled") for r in results)
    failures = [r for r in results if r.get("status") == "failed"]
    message = "Publication traitée."
    if has_success and failures:
        message = f"Publication partielle : {len(failures)} cible(s) en erreur."
    elif failures and not has_success:
        message = failures[0].get("error") or "Publication impossible."
    elif all(r.get("status") == "scheduled" for r in results if r):
        message = "Publication programmée."
    return JSONResponse({"success": has_success, "message": message, "data": {"results": results}},
                        status_code=200 if has_success else 422)
