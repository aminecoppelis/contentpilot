"""File persistante de génération d'idées, équivalent du traitement asynchrone n8n.

L'HTTP crée/enfile un job puis répond immédiatement. Le job est traité hors requête
et reste récupérable après redémarrage grâce à ``post_generation_jobs``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.database import get_pool
from app.services import ai
from app.services.ai import AIGenerationError

logger = logging.getLogger("services.post_generation")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
MAX_ATTEMPTS = 3


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _list(value: Any) -> list:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [x.strip() for x in re.split(r"[,;\n]", value) if x.strip()]
    return [str(value).strip()]


def _tags(value: Any) -> list[str]:
    values = _list(value) if not isinstance(value, str) else [x for x in re.split(r"[\s,;]+", value) if x]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        tag = str(raw).strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result[:10]


def normalize_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    website = str(data.get("website") or data.get("site_web") or "").strip()
    if website and not re.match(r"^https?://", website, re.I) and re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/.*)?$", website, re.I):
        website = "https://" + website
    data["website"] = website
    data["site_web"] = website
    company = str(data.get("company") or data.get("entreprise") or "").strip()
    data["company"] = company
    data["entreprise"] = company
    data["default_tags"] = _tags(data.get("default_tags"))
    data["content_domains"] = _list(data.get("content_domains"))
    data["target_audience"] = _list(data.get("target_audience"))
    data["preferred_formats"] = _list(data.get("preferred_formats"))
    urls = _list(data.get("source_urls"))
    blob = "\n".join(str(data.get(k) or "") for k in ("subject", "prompt", "theme", "constraints"))
    urls += [u.rstrip(".,;:!?") for u in URL_RE.findall(blob)]
    data["source_urls"] = list(dict.fromkeys(urls))[:5]
    data["content_context"] = {
        **(_json(data.get("content_context"), {}) or {}),
        "domains": data["content_domains"],
        "domains_text": "\n".join("- " + x for x in data["content_domains"]),
        "website": website,
        "solution": str(data.get("solution") or "").strip(),
        "company": company,
        "default_tags": data["default_tags"],
        "brand_voice": "expert, concret, orienté valeur métier, accessible aux décideurs non techniques",
    }
    return data


async def enqueue_initial(*, payload: dict[str, Any], user_id: str, workspace_id: str) -> tuple[str, str]:
    data = normalize_request_payload(payload)
    subject = str(data.get("subject") or "").strip()
    objective = str(data.get("commercial_objective") or "").strip()
    language = str(data.get("language") or "").strip()
    domains = data.get("content_domains") or []
    formats = data.get("preferred_formats") or []
    try:
        count = int(data.get("post_count") or 5)
    except (TypeError, ValueError):
        count = 5
    if not subject:
        raise ValueError("Sujet obligatoire.")
    if not objective:
        raise ValueError("Objectif commercial obligatoire.")
    if not language:
        raise ValueError("Langue obligatoire.")
    if not domains:
        raise ValueError("Sélectionne au moins un domaine à couvrir.")
    if not formats:
        raise ValueError("Sélectionne au moins un format de publication.")
    if count < 1 or count > 8:
        raise ValueError("Le nombre de posts doit être compris entre 1 et 8.")
    data["post_count"] = count
    data["generation_mode"] = "initial"
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            INSERT INTO public.post_requests (
              title,subject,prompt,commercial_objective,target_sector,language,
              content_domains,target_audience,preferred_formats,constraints,source_urls,
              post_count,form_data,status,user_id,workspace_id
            ) VALUES ($1,$1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10::jsonb,$11,$12::jsonb,'generating',$13::uuid,$14::uuid)
            RETURNING id::text
            """,
            subject, str(data.get("prompt") or data.get("theme") or ""), objective,
            str(data.get("target_sector") or ""), language,
            json.dumps(domains), json.dumps(data.get("target_audience") or []),
            json.dumps(formats), str(data.get("constraints") or ""),
            json.dumps(data.get("source_urls") or []), count, json.dumps(data), user_id, workspace_id,
        )
        request_id = row["id"]
        job = await conn.fetchrow(
            """
            INSERT INTO public.post_generation_jobs(request_id,workspace_id,user_id,mode,requested_count,payload,status)
            VALUES($1::uuid,$2::uuid,$3::uuid,'initial',$4,$5::jsonb,'queued')
            RETURNING id::text
            """, request_id, workspace_id, user_id, count, json.dumps(data)
        )
    return request_id, job["id"]


async def enqueue_append(*, request_id: str, workspace_id: str, user_id: str, count: int, instructions: str = "") -> str:
    count = max(1, min(8, int(count or 3)))
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        req = await conn.fetchrow(
            "SELECT id,status FROM public.post_requests WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL FOR UPDATE",
            request_id, workspace_id,
        )
        if req is None:
            raise LookupError("Demande introuvable.")
        active = await conn.fetchval(
            "SELECT id::text FROM public.post_generation_jobs WHERE request_id=$1::uuid AND status IN ('queued','running','retry') LIMIT 1",
            request_id,
        )
        if active:
            return active
        await conn.execute(
            "UPDATE public.post_requests SET status='generating_more',last_error=NULL,updated_at=now() WHERE id=$1::uuid",
            request_id,
        )
        previous_request_status = str(req["status"] or "").strip().lower()
        row = await conn.fetchrow(
            """
            INSERT INTO public.post_generation_jobs(request_id,workspace_id,user_id,mode,requested_count,instructions,payload,status)
            VALUES(
              $1::uuid,$2::uuid,$3::uuid,'append',$4::integer,$5::text,
              jsonb_build_object(
                'request_id',$1::text,
                'post_count',$4::integer,
                'append_instructions',$5::text,
                'previous_request_status',$6::text
              ),
              'queued'
            )
            RETURNING id::text
            """, request_id, workspace_id, user_id, count, str(instructions or ""), previous_request_status
        )
    return row["id"]


async def _claim(job_id: str | None = None):
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            WITH candidate AS (
              SELECT j.id
              FROM public.post_generation_jobs j
              WHERE ($1::uuid IS NULL OR j.id=$1::uuid)
                AND (
                  j.status IN ('queued','retry')
                  OR (j.status='running' AND COALESCE(j.locked_until,now()-interval '1 second') < now())
                )
                AND j.attempt_count < $2
              ORDER BY j.created_at ASC
              LIMIT 1
              FOR UPDATE SKIP LOCKED
            )
            UPDATE public.post_generation_jobs j
            SET status='running', attempt_count=j.attempt_count+1,
                started_at=COALESCE(j.started_at,now()), locked_until=now()+interval '15 minutes',
                last_error=NULL, updated_at=now()
            FROM candidate c
            WHERE j.id=c.id
            RETURNING j.*
            """, job_id, MAX_ATTEMPTS,
        )
    return row


async def process_job(job_id: str | None = None) -> dict[str, Any]:
    job = await _claim(job_id)
    if job is None:
        return {"stage": "idle"}
    mode = str(job["mode"] or "initial")
    request_id = str(job["request_id"])
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            req = await conn.fetchrow(
                "SELECT * FROM public.post_requests WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL",
                request_id, str(job["workspace_id"]),
            )
            existing = await conn.fetch(
                "SELECT title,hook,recommended_format FROM public.post_ideas WHERE request_id=$1::uuid AND deleted_at IS NULL ORDER BY number",
                request_id,
            )
        if req is None:
            raise RuntimeError("Demande de génération introuvable.")
        base = normalize_request_payload(_json(req["form_data"], {}) or {})
        # Les colonnes restent la source de vérité si une ancienne demande n'avait pas encore tout dans form_data.
        base.update({
            "subject": str(req["subject"] or base.get("subject") or ""),
            "prompt": str(req["prompt"] or base.get("prompt") or base.get("theme") or ""),
            "commercial_objective": str(req["commercial_objective"] or base.get("commercial_objective") or ""),
            "target_sector": str(req["target_sector"] or base.get("target_sector") or ""),
            "language": str(req["language"] or base.get("language") or "français"),
            "constraints": str(req["constraints"] or base.get("constraints") or ""),
            "content_domains": _list(req["content_domains"]) or base.get("content_domains") or [],
            "target_audience": _list(req["target_audience"]) or base.get("target_audience") or [],
            "preferred_formats": _list(req["preferred_formats"]) or base.get("preferred_formats") or [],
            "source_urls": _list(req["source_urls"]) or base.get("source_urls") or [],
        })
        base = normalize_request_payload(base)
        job_payload = _json(job["payload"], {}) or {}
        previous_request_status = str(job_payload.get("previous_request_status") or "").strip().lower()
        append_final_status = "ready_for_review" if previous_request_status in {"ready_for_review", "pending_review"} else "ready"
        base["post_count"] = int(job["requested_count"] or 1)
        base["generation_mode"] = mode
        if mode == "append":
            base["append_instructions"] = str(job["instructions"] or "")
            base["existing_ideas_summary"] = [
                {"title": r["title"], "hook": r["hook"], "recommended_format": r["recommended_format"]}
                for r in existing
            ]

        urls = base.get("source_urls") or []
        if urls:
            try:
                news = await ai.filter_news({"urls": urls, "subject": base["subject"], "prompt": base["prompt"]})
                base["news_filter"] = news.parsed
            except AIGenerationError:
                base["news_filter"] = {"should_use": False}
        result = await ai.generate_ideas(base)
        ideas = result.parsed.get("ideas") or []
        if not ideas:
            raise RuntimeError("La génération n'a retourné aucune idée exploitable.")

        async with pool.acquire() as conn, conn.transaction():
            start_number = await conn.fetchval(
                "SELECT COALESCE(MAX(number),0) FROM public.post_ideas WHERE request_id=$1::uuid AND deleted_at IS NULL",
                request_id,
            )
            if mode == "initial" and int(start_number or 0) > 0:
                # Un job rejoué après crash ne doit pas dupliquer un lot déjà sauvegardé.
                await conn.execute(
                    "UPDATE public.post_generation_jobs SET status='completed',finished_at=now(),locked_until=NULL,updated_at=now() WHERE id=$1::uuid",
                    str(job["id"]),
                )
                await conn.execute("UPDATE public.post_requests SET status='ready',generated_at=COALESCE(generated_at,now()),last_error=NULL,updated_at=now() WHERE id=$1::uuid", request_id)
                return {"stage": "already_saved", "request_id": request_id}
            created = 0
            for offset, idea in enumerate(ideas, start=1):
                ready = idea.get("ready_post") or {}
                number = int(start_number or 0) + offset
                idea_row = await conn.fetchrow(
                    """
                    INSERT INTO public.post_ideas(request_id,user_id,workspace_id,number,status,title,hook,summary,recommended_format,target_sector,target_audience,scores,seo_keywords,raw_idea)
                    VALUES($1::uuid,$2::uuid,$3::uuid,$4,'pending_review',$5,$6,$7,$8,$9,$10,$11::jsonb,$12::jsonb,$13::jsonb)
                    RETURNING id::text
                    """,
                    request_id, str(job["user_id"]), str(job["workspace_id"]), number,
                    idea.get("title", ""), idea.get("hook", ""), idea.get("summary", ""),
                    idea.get("recommended_format", ""), idea.get("target_sector", ""), idea.get("target_audience", ""),
                    json.dumps({k: idea.get(k, 0) for k in (
                        "virality_score","commercial_potential_score","implementation_difficulty_score",
                        "sme_interest_score","enterprise_interest_score","lead_generation_score")}),
                    json.dumps(idea.get("seo_keywords") or []), json.dumps(idea),
                )
                version = await conn.fetchrow(
                    """
                    INSERT INTO public.post_versions(idea_id,workspace_id,version_number,source,title,post_text,hashtags,cta,is_current,raw_version)
                    VALUES($1::uuid,$2::uuid,1,$3,$4,$5,$6::jsonb,$7,true,$8::jsonb)
                    RETURNING id::text
                    """,
                    idea_row["id"], str(job["workspace_id"]),
                    "ai_generation_append" if mode == "append" else "ai_generation",
                    ready.get("title") or idea.get("title") or "", ready.get("text") or "",
                    json.dumps(ready.get("tags") or idea.get("hashtags") or []),
                    ready.get("simple_action") or idea.get("call_to_action") or "", json.dumps(ready),
                )
                await conn.execute("UPDATE public.post_ideas SET current_version_id=$2::uuid WHERE id=$1::uuid", idea_row["id"], version["id"])
                created += 1
            if mode == "append":
                await conn.execute(
                    "UPDATE public.post_requests SET status=$3::text,generated_at=now(),post_count=COALESCE(post_count,0)+$2,last_error=NULL,updated_at=now() WHERE id=$1::uuid",
                    request_id, created, append_final_status,
                )
            else:
                await conn.execute(
                    "UPDATE public.post_requests SET status='ready',generated_at=now(),last_error=NULL,updated_at=now() WHERE id=$1::uuid",
                    request_id,
                )
            await conn.execute(
                "UPDATE public.post_generation_jobs SET status='completed',finished_at=now(),locked_until=NULL,last_error=NULL,updated_at=now() WHERE id=$1::uuid",
                str(job["id"]),
            )
        return {"stage": "done", "request_id": request_id, "saved_count": len(ideas), "mode": mode}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Post generation job failed job_id=%s request_id=%s", job["id"], request_id)
        attempt = int(job["attempt_count"] or 1)
        final = attempt >= MAX_ATTEMPTS
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE public.post_generation_jobs SET status=$2,last_error=$3,locked_until=NULL,finished_at=CASE WHEN $2='failed' THEN now() ELSE NULL END,updated_at=now() WHERE id=$1::uuid",
                str(job["id"]), "failed" if final else "retry", str(exc)[:4000],
            )
            if final:
                if mode == "append":
                    await conn.execute(
                        "UPDATE public.post_requests SET status=$3::text,last_error=$2,updated_at=now() WHERE id=$1::uuid",
                        request_id, str(exc)[:4000], append_final_status,
                    )
                else:
                    await conn.execute("UPDATE public.post_requests SET status='failed',last_error=$2,updated_at=now() WHERE id=$1::uuid", request_id, str(exc)[:4000])
        return {"stage": "failed" if final else "retry", "request_id": request_id, "detail": str(exc), "mode": mode}


def kick(job_id: str) -> None:
    """Démarre tout de suite sans rendre la fiabilité dépendante de cette tâche mémoire.

    Le cron persistant reprendra le job s'il reste queued/running après un crash.
    """
    asyncio.create_task(process_job(job_id))


async def generation_status(*, request_id: str, workspace_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pr.id::text AS request_id,pr.status,pr.last_error,pr.post_count,
                   (SELECT count(*)::int FROM public.post_ideas pi WHERE pi.request_id=pr.id AND pi.deleted_at IS NULL) AS ideas_count,
                   j.id::text AS job_id,j.mode,j.status AS job_status,j.requested_count,j.attempt_count,j.last_error AS job_error
            FROM public.post_requests pr
            LEFT JOIN LATERAL (
              SELECT * FROM public.post_generation_jobs x WHERE x.request_id=pr.id ORDER BY x.created_at DESC LIMIT 1
            ) j ON true
            WHERE pr.id=$1::uuid AND pr.workspace_id=$2::uuid AND pr.deleted_at IS NULL
            """, request_id, workspace_id,
        )
    return dict(row) if row else None
