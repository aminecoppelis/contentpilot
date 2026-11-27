#!/usr/bin/env python3
"""Crée un administrateur actif dans la base configurée pour SocialAI."""

import argparse
import asyncio
from getpass import GetPassWarning, getpass
import os
from pathlib import Path
import sys
import warnings

import asyncpg
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import close_pool, init_pool  # noqa: E402
from app.security import hash_password, is_valid_email, is_valid_password  # noqa: E402


async def create_admin(email: str, password_hash: str) -> bool:
    pool = await init_pool()
    try:
        async with pool.acquire() as conn, conn.transaction():
            user_id = await conn.fetchval('''
                INSERT INTO public.app_users (email, password_hash, role, is_active, activated_at)
                SELECT $1, $2, 'admin', true, now()
                WHERE NOT EXISTS (SELECT 1 FROM public.app_users WHERE lower(email)=$1)
                ON CONFLICT (email) DO NOTHING RETURNING id
            ''', email, password_hash)
            if user_id is None:
                return False
            workspace_id = await conn.fetchval('''
                INSERT INTO public.workspaces (name, owner_user_id, is_personal)
                VALUES ('Espace personnel', $1, true) RETURNING id
            ''', user_id)
            await conn.execute('''
                INSERT INTO public.workspace_members (workspace_id, user_id, role, status, joined_at)
                VALUES ($1, $2, 'owner', 'active', now())
            ''', workspace_id, user_id)
            await conn.execute('UPDATE public.app_users SET last_workspace_id=$1 WHERE id=$2', workspace_id, user_id)
        return True
    finally:
        await close_pool()


async def reset_admin_password(email: str, password_hash: str) -> bool:
    pool = await init_pool()
    try:
        async with pool.acquire() as conn:
            result = await conn.execute('''
                UPDATE public.app_users SET password_hash=$2, updated_at=now()
                WHERE lower(email)=$1 AND lower(role)='admin' AND is_active AND deleted_at IS NULL
            ''', email, password_hash)
        return result == 'UPDATE 1'
    finally:
        await close_pool()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('email', help='Adresse e-mail du nouveau compte')
    parser.add_argument('--reset-password', action='store_true', help='Réinitialiser le mot de passe d’un administrateur actif')
    args = parser.parse_args()
    email = args.email.strip().lower()
    if not is_valid_email(email):
        parser.error('Adresse e-mail invalide.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            password = getpass('Mot de passe : ')
            confirmation = getpass('Confirmer le mot de passe : ')
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        print('Utilisez un terminal interactif pour saisir le mot de passe.', file=sys.stderr)
        return 1
    if password != confirmation:
        parser.error('Les mots de passe ne correspondent pas.')
    if not is_valid_password(password) or len(password.encode('utf-8')) > 72:
        parser.error('Le mot de passe doit contenir au moins 10 caractères et au plus 72 octets UTF-8.')
    try:
        os.chdir(PROJECT_ROOT)
        action = reset_admin_password if args.reset_password else create_admin
        success = asyncio.run(action(email, hash_password(password)))
    except ValidationError:
        print('Configuration invalide. Vérifiez DATABASE_URL dans le fichier .env à la racine du projet.', file=sys.stderr)
        return 1
    except (asyncpg.PostgresError, OSError) as exc:
        print(f'Opération impossible. Vérifiez la configuration et le schéma de la base ({type(exc).__name__}).', file=sys.stderr)
        return 1
    if not success:
        message = ('Aucun administrateur actif trouvé à cette adresse.' if args.reset_password
                   else 'Cette adresse est déjà associée à un compte.')
        print(message, file=sys.stderr)
        return 1
    print(f'Mot de passe réinitialisé : {email}' if args.reset_password else f'Administrateur actif créé : {email}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
