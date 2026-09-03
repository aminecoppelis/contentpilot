#!/usr/bin/env python3
"""
Gestion des activations de compte en ligne de commande.

Utile quand l'email d'activation n'arrive pas (SMTP mal configuré, message
classé en spam, expéditeur refusé par le fournisseur) : permet de récupérer
un lien valide ou d'activer directement un compte.

Usage :
  venv/bin/python tools/activation.py --list
      Liste les comptes non activés et l'état de leur jeton.

  venv/bin/python tools/activation.py --link user@example.com
      Génère un NOUVEAU lien d'activation valable 24 h et l'affiche.

  venv/bin/python tools/activation.py --activate user@example.com
      Active immédiatement le compte, sans passer par l'email.

  venv/bin/python tools/activation.py --test-mail user@example.com
      Envoie un email de test et détaille précisément ce qui se passe.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings          # noqa: E402
from app.database import init_pool, close_pool, get_pool  # noqa: E402


async def cmd_list() -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.email, u.is_active, u.created_at,
                   t.expires_at, t.used_at,
                   (t.expires_at > now() AND t.used_at IS NULL) AS token_valide
            FROM public.app_users u
            LEFT JOIN LATERAL (
                SELECT expires_at, used_at FROM public.account_activation_tokens
                WHERE user_id = u.id ORDER BY created_at DESC LIMIT 1
            ) t ON true
            WHERE u.deleted_at IS NULL
            ORDER BY u.created_at DESC
            """
        )
    if not rows:
        print("Aucun utilisateur.")
        return 0
    print(f"{'EMAIL':38} {'ACTIF':6} {'JETON':10} CRÉÉ LE")
    print("-" * 78)
    for r in rows:
        actif = "oui" if r["is_active"] else "NON"
        if r["is_active"]:
            jeton = "-"
        elif r["token_valide"]:
            jeton = "valide"
        elif r["used_at"]:
            jeton = "utilisé"
        elif r["expires_at"]:
            jeton = "expiré"
        else:
            jeton = "aucun"
        print(f"{r['email']:38} {actif:6} {jeton:10} {r['created_at']:%d/%m/%Y %H:%M}")
    return 0


async def cmd_link(email: str) -> int:
    settings = get_settings()
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, is_active FROM public.app_users "
            "WHERE lower(email)=lower($1) AND deleted_at IS NULL", email)
        if user is None:
            print(f"Aucun compte pour {email}.")
            return 1
        if user["is_active"]:
            print(f"Le compte {email} est DÉJÀ actif — connexion possible directement.")
            return 0
        await conn.execute(
            "INSERT INTO public.account_activation_tokens (user_id, token_hash, expires_at) "
            "VALUES ($1, $2, now() + interval '24 hours')", user["id"], token_hash)

    url = f"{settings.app_base_url.rstrip('/')}/app/activate?token={token}"
    print("\nLien d'activation (valable 24 h) :\n")
    print(f"  {url}\n")
    return 0


async def cmd_activate(email: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE public.app_users SET is_active = true, "
            "activated_at = COALESCE(activated_at, now()) "
            "WHERE lower(email)=lower($1) AND deleted_at IS NULL RETURNING email", email)
    if row is None:
        print(f"Aucun compte pour {email}.")
        return 1
    print(f"Compte {row['email']} activé. Connexion possible immédiatement.")
    return 0


async def cmd_test_mail(email: str) -> int:
    from app.services.mailer import send_activation_email, _tls_mode

    settings = get_settings()
    use_tls, start_tls = _tls_mode(settings)
    mode = "SSL implicite" if use_tls else ("STARTTLS" if start_tls else "aucun chiffrement")

    print("Configuration SMTP utilisée :")
    print(f"  hôte        : {settings.smtp_host or '(vide -> emails désactivés)'}")
    print(f"  port        : {settings.smtp_port}   ({mode})")
    print(f"  utilisateur : {settings.smtp_user or '(aucun)'}")
    print(f"  expéditeur  : {settings.smtp_from}")
    print()

    if not settings.smtp_enabled:
        print("SMTP_HOST est vide : aucun email ne sera jamais envoyé.")
        print("Utilise --link pour obtenir un lien d'activation.")
        return 1

    ok = await send_activation_email(
        to_email=email, full_name="Test",
        activation_url=f"{settings.app_base_url.rstrip('/')}/app/activate?token=TEST")

    if ok:
        print(f"Le serveur SMTP a ACCEPTÉ le message pour {email}.")
        print()
        print("S'il n'arrive pas, la cause est en aval de l'envoi :")
        print("  - vérifier le dossier indésirables ;")
        print("  - SMTP_FROM doit correspondre à une adresse autorisée sur le")
        print("    compte SMTP (OVH refuse silencieusement les autres) ;")
        print("  - consulter les logs de rejet du fournisseur.")
    else:
        print("Envoi ÉCHOUÉ — la cause exacte figure dans les logs :")
        print("  sudo journalctl -u post-generator | grep -i mailer | tail -5")
    return 0 if ok else 1


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="lister les comptes et l'état des jetons")
    g.add_argument("--link", metavar="EMAIL", help="générer un nouveau lien d'activation")
    g.add_argument("--activate", metavar="EMAIL", help="activer directement le compte")
    g.add_argument("--test-mail", metavar="EMAIL", help="envoyer un email de test et diagnostiquer")
    args = parser.parse_args()

    await init_pool()
    try:
        if args.list:
            return await cmd_list()
        if args.link:
            return await cmd_link(args.link)
        if args.activate:
            return await cmd_activate(args.activate)
        return await cmd_test_mail(args.test_mail)
    finally:
        await close_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
