"""
Service d'envoi d'emails transactionnels (SMTP), Cahier technique §11.

Réplique le style visuel identifié dans le nœud original
"AUTH - Préparer email activation" (carte blanche arrondie, accent indigo,
police système) sans copier la marque/domaine du client d'origine.
"""
from __future__ import annotations

import logging
from email.message import EmailMessage
from html import escape

import aiosmtplib

from app.config import get_settings

logger = logging.getLogger("services.mailer")

ACCENT_COLOR = "#4f46e5"


def _base_html(title: str, greeting: str, body_html: str, cta_url: str | None = None, cta_label: str | None = None) -> str:
    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
        <p style="margin:24px 0">
          <a href="{cta_url}" style="display:inline-block;background:{ACCENT_COLOR};color:#ffffff;
             text-decoration:none;font-weight:bold;padding:12px 22px;border-radius:10px">{cta_label}</a>
        </p>"""
    return f"""<!doctype html><html lang="fr"><body style="margin:0;padding:0;background:#f4f7fb;font-family:Arial,sans-serif;color:#111827">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f7fb;padding:28px">
<tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:22px;padding:28px">
<tr><td>
<p style="margin:0 0 10px;color:{ACCENT_COLOR};font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:.08em">{title}</p>
<p style="margin:0 0 18px;color:#475569;line-height:1.55">{greeting}</p>
{body_html}
{cta_block}
</td></tr></table></td></tr></table></body></html>"""


def _tls_mode(settings) -> tuple[bool, bool]:
    """
    Détermine le mode de chiffrement à partir du port, sauf réglage explicite.

    Les deux modes sont incompatibles entre eux :
      - port 465 : SSL implicite (SMTPS) -> use_tls=True.
        La session est chiffrée dès la connexion. Se connecter en clair sur ce
        port provoque « Unexpected EOF received » : le serveur ferme aussitôt.
      - port 587 : STARTTLS -> start_tls=True.
        La session démarre en clair puis bascule en TLS.
      - port 25 / 1025 : aucun chiffrement (relais local, capteur de test).

    SMTP_USE_TLS ou SMTP_START_TLS explicitement à true dans .env priment
    sur cette détection.
    """
    port = int(settings.smtp_port or 0)

    if settings.smtp_use_tls:
        return True, False
    if settings.smtp_start_tls:
        return False, True

    if port == 465:
        logger.debug("SMTP: port 465 détecté -> SSL implicite (use_tls)")
        return True, False
    if port in (587, 2587):
        logger.debug("SMTP: port %s détecté -> STARTTLS", port)
        return False, True
    return False, False


class MailerError(Exception):
    """Échec d'envoi d'email. Volontairement distinct des autres erreurs pour
    que les routes puissent décider de continuer malgré tout."""


async def _send(to_email: str, subject: str, html: str, text: str | None = None) -> bool:
    """
    Envoie immédiatement un email et attend la réponse du serveur SMTP.

    Retourne True uniquement si le serveur SMTP a accepté le message.
    L'appelant décide ensuite si l'échec doit bloquer l'action ou simplement
    être journalisé. Les emails d'activation et d'invitation sont appelés
    directement depuis leurs routes HTTP et ne passent jamais par un worker.
    """
    settings = get_settings()
    if not to_email:
        logger.warning("Mailer: destinataire vide, email '%s' non envoyé", subject)
        return False

    if not settings.smtp_enabled:
        logger.warning(
            "Mailer: SMTP désactivé (SMTP_HOST vide) — email '%s' vers %s non envoyé",
            subject, to_email)
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text or "Ce message nécessite un client compatible HTML.")
    msg.add_alternative(html, subtype="html")

    use_tls, start_tls = _tls_mode(settings)

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=settings.smtp_timeout,
        )
        logger.info("Mailer: email '%s' envoyé à %s", subject, to_email)
        return True
    except Exception as exc:  # noqa: BLE001
        hint = ""
        text = str(exc).lower()
        if "unexpected eof" in text or "wrong version number" in text:
            hint = (" — incohérence de chiffrement : port 465 exige SMTP_USE_TLS=true, "
                    "port 587 exige SMTP_START_TLS=true")
        elif "authentication" in text or "535" in text:
            hint = " — identifiants refusés (SMTP_USER / SMTP_PASSWORD)"
        elif "connection refused" in text or "errno 111" in text:
            hint = " — aucun serveur à cette adresse (vérifie SMTP_HOST / SMTP_PORT)"
        elif "timed out" in text:
            hint = " — délai dépassé (port bloqué par un pare-feu ?)"
        logger.error(
            "Mailer: envoi impossible vers %s (%s:%s, use_tls=%s, start_tls=%s) — %s : %s%s",
            to_email, settings.smtp_host, settings.smtp_port, use_tls, start_tls,
            type(exc).__name__, exc, hint)
        return False


async def send_activation_email(*, to_email: str, full_name: str, activation_url: str) -> bool:
    """Envoi immédiat du mail d’activation, fidèle au V90 n8n."""
    safe_name = escape(full_name or to_email, quote=True)
    safe_activation_url = escape(activation_url, quote=True)
    html = f"""<!doctype html><html lang="fr"><body style="margin:0;padding:0;background:#f4f7fb;font-family:Arial,sans-serif;color:#111827">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f7fb;padding:28px"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:22px;padding:28px"><tr><td>
<p style="margin:0 0 10px;color:#4f46e5;font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:.08em">Activation du compte</p>
<h1 style="margin:0 0 14px;font-size:26px;line-height:1.15;color:#111827">Active ton compte</h1>
<p style="margin:0 0 18px;color:#475569;line-height:1.55">Bonjour {safe_name},<br>ton compte Post Generator a été créé. Clique sur le bouton ci-dessous pour l’activer.</p>
<p style="margin:24px 0"><a href="{safe_activation_url}" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:bold;border-radius:14px;padding:13px 18px">Activer mon compte</a></p>
<p style="margin:0;color:#64748b;font-size:13px;line-height:1.45">Ce lien expire dans 24 heures. Si le bouton ne fonctionne pas, copie ce lien dans ton navigateur :<br><span style="word-break:break-all;color:#334155">{safe_activation_url}</span></p>
</td></tr></table></td></tr></table></body></html>"""
    text = f"Bonjour {full_name or to_email},\n\nActive ton compte Post Generator avec ce lien :\n{activation_url}\n\nCe lien expire dans 24 heures."
    return await _send(to_email, "Active ton compte Post Generator", html, text)


async def send_account_change_email(*, to_email: str, full_name: str) -> bool:
    html = _base_html(
        title="Confirmation de compte",
        greeting=f"Bonjour {full_name or to_email},<br>l'adresse email de ton compte Post Generator vient d'être modifiée.",
        body_html="<p style='margin:0;color:#94a3b8;font-size:13px'>Si tu n'es pas à l'origine de ce changement, contacte le support immédiatement.</p>",
    )
    return await _send(to_email, "Ton compte Post Generator a été modifié", html)


async def send_workspace_invite_email(
    *, to_email: str, workspace_name: str, invite_url: str, role: str = "member"
) -> bool:
    """Envoi immédiat de l’invitation workspace, dans la requête utilisateur."""
    role_label = "Administrateur" if str(role).lower() == "admin" else "Membre"
    safe_workspace_name = escape(workspace_name or "Workspace", quote=True)
    safe_invite_url = escape(invite_url, quote=True)
    html = (
        f"<p>Vous avez été invité à rejoindre le workspace « {safe_workspace_name} » "
        f"Post Generator avec le rôle {role_label}.</p>"
        f"<p><a href=\"{safe_invite_url}\">Accepter l’invitation</a></p>"
        "<p>Ce lien expire dans 7 jours.</p>"
    )
    text = (
        f"Vous avez été invité à rejoindre le workspace « {workspace_name} » "
        f"avec le rôle {role_label}.\n\nAccepter l’invitation :\n{invite_url}\n\n"
        "Ce lien expire dans 7 jours."
    )
    return await _send(to_email, "Invitation au workspace", html, text)


async def send_generation_ready_email(*, to_email: str, full_name: str, request_url: str) -> bool:
    html = _base_html(
        title="Génération terminée",
        greeting=f"Bonjour {full_name or to_email},<br>tes idées de posts sont prêtes à consulter.",
        body_html="",
        cta_url=request_url, cta_label="Voir les idées générées",
    )
    return await _send(to_email, "Tes idées de posts sont prêtes", html)


async def send_worker_error_email(
    *, recipient: str | None, first_name: str, stage: str, message: str, calendar_id: str,
    subject_name: str = "Sujet planifié", request_id: str = "", error_node: str = "Nœud inconnu",
    attempt_count: int = 0,
) -> bool:
    """Port fonctionnel de « Worker - Build error email » du n8n V90."""
    settings = get_settings()
    to_email = recipient or "support@coppelis.com"
    safe_first = escape(first_name or "", quote=True)
    safe_subject = escape(subject_name or "Sujet planifié", quote=True)
    safe_stage = escape(stage or "calendar_clean_worker_failed", quote=True)
    safe_node = escape(error_node or "Nœud inconnu", quote=True)
    safe_message = escape(message or "Erreur de génération.", quote=True)
    safe_calendar = escape(calendar_id or "indisponible", quote=True)
    safe_request = escape(request_id or "indisponible", quote=True)
    greeting = f"Bonjour {safe_first}," if safe_first else "Bonjour,"
    base = (settings.app_base_url or "https://socialnetwork.coppelis.com").rstrip("/")
    view_url = (f"{base}/app/posts/view?request_id={request_id}" if request_id else f"{base}/app/strategies")
    html = f"""
<div style="font-family:Arial,sans-serif;max-width:720px;margin:auto;color:#0f172a">
  <div style="background:#0f172a;color:#fff;padding:18px 22px;border-radius:14px 14px 0 0">
    <div style="font-size:12px;font-weight:700;letter-spacing:.08em">POST GENERATOR</div>
    <div style="font-size:22px;font-weight:700;margin-top:5px">Erreur de génération planifiée</div>
  </div>
  <div style="border:1px solid #e2e8f0;border-top:0;padding:22px;border-radius:0 0 14px 14px">
    <p>{greeting}</p>
    <p>La génération OpenRouter n’a pas été finalisée.</p>
    <table style="width:100%;border-collapse:collapse">
      <tr><td style="padding:7px 0;font-weight:700">Sujet</td><td>{safe_subject}</td></tr>
      <tr><td style="padding:7px 0;font-weight:700">Étape</td><td>{safe_stage}</td></tr>
      <tr><td style="padding:7px 0;font-weight:700">Nœud</td><td>{safe_node}</td></tr>
      <tr><td style="padding:7px 0;font-weight:700">Erreur</td><td>{safe_message}</td></tr>
      <tr><td style="padding:7px 0;font-weight:700">Tentative</td><td>{attempt_count or 'indisponible'} / 3</td></tr>
      <tr><td style="padding:7px 0;font-weight:700">request_id</td><td>{safe_request}</td></tr>
      <tr><td style="padding:7px 0;font-weight:700">calendar_id</td><td>{safe_calendar}</td></tr>
    </table>
    <p style="margin-top:22px"><a href="{escape(view_url, quote=True)}" style="background:#4f46e5;color:#fff;text-decoration:none;padding:11px 16px;border-radius:10px;display:inline-block">Ouvrir le sujet</a></p>
  </div>
</div>"""
    return await _send(to_email, f"[Post Generator] Erreur planification · {subject_name or 'Sujet planifié'}", html)


async def send_validation_reminder_email_raw(
    *, to_email: str, first_name: str, workspace_name: str, idea_title: str,
    request_subject: str, post_excerpt: str, validation_url: str, reminder_number: int,
) -> bool:
    """
    Port EXACT du template HTML du nœud "VALIDATION - Construire email
    rappel" (VALIDATION_EMAIL_HTML_V68_2026_08_07) — reproduit ici
    caractère pour caractère plutôt que via `_base_html`, car la mise en
    forme diffère légèrement du gabarit générique (bandeau "Post Generator"
    en majuscules, badge de rappel, bloc sujet/idée dédié, mention de
    l'intervalle de 2h). Voir sql/validation/claim_reminders.sql pour la
    provenance des champs.
    """
    def esc(value: str) -> str:
        return (
            (value or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;")
        )

    greeting = f"Bonjour {esc(first_name)}," if first_name else "Bonjour,"
    reminder_label = "Nouveau contenu à valider" if reminder_number <= 1 else f"Rappel de validation n°{reminder_number}"
    subject = f"Post Generator — Validation requise : {idea_title[:90]}"

    excerpt_html = ""
    if post_excerpt:
        excerpt_html = (
            '<div style="margin:18px 0;padding:16px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0">'
            '<div style="font-size:12px;font-weight:800;color:#64748b;margin-bottom:7px">APERÇU DU POST</div>'
            f'<div style="color:#334155;line-height:1.55;white-space:pre-wrap">{esc(post_excerpt)}</div></div>'
        )

    button = ""
    if validation_url:
        button = (
            f'<p style="margin:24px 0 0"><a href="{esc(validation_url)}" '
            'style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;'
            'border-radius:12px;padding:12px 18px;font-weight:800">Ouvrir et valider</a></p>'
        )

    html = (
        '<!doctype html><html lang="fr"><body style="margin:0;background:#f4f7fb;'
        'font-family:Inter,Arial,sans-serif;color:#0f172a">'
        '<div style="max-width:680px;margin:0 auto;padding:28px 18px">'
        '<div style="background:#fff;border:1px solid #e2e8f0;border-radius:20px;padding:28px">'
        '<div style="font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;'
        'color:#6366f1;margin-bottom:10px">Post Generator</div>'
        f'<span style="display:inline-block;background:#eef2ff;color:#4338ca;border-radius:999px;'
        f'padding:6px 10px;font-size:12px;font-weight:800;margin-bottom:14px">{esc(reminder_label)}</span>'
        '<h1 style="font-size:25px;line-height:1.2;margin:0 0 16px">Une validation est en attente</h1>'
        f'<p style="margin:0 0 12px;color:#334155;line-height:1.6">{greeting}</p>'
        f'<p style="margin:0 0 18px;color:#334155;line-height:1.6">Un contenu est prêt à être validé '
        f'dans le workspace <b>{esc(workspace_name or "Workspace")}</b>.</p>'
        '<div style="background:#fafafa;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin:18px 0">'
        f'<p style="margin:0 0 8px"><b>Sujet :</b> {esc(request_subject or idea_title)}</p>'
        f'<p style="margin:0"><b>Idée :</b> {esc(idea_title or "Post à valider")}</p></div>'
        f'{excerpt_html}{button}'
        '<p style="margin:22px 0 0;color:#64748b;font-size:12px;line-height:1.55">Un rappel sera renvoyé '
        'toutes les 2 heures tant que ce contenu reste à valider. Les rappels s’arrêtent automatiquement '
        'dès qu’il est validé ou refusé.</p>'
        '</div></div></body></html>'
    )
    return await _send(to_email, subject, html)
