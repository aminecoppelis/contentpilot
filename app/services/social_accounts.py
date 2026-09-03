"""Helpers centralisés pour l'accès aux comptes sociaux multi-workspace.

Un compte OAuth réel vit dans ``app_social_accounts``. Son autorisation dans
un workspace vit dans ``app_social_account_workspaces``. Toutes les routes qui
publient, analysent ou modifient un compte doivent utiliser la même règle pour
éviter qu'un bouton fonctionne dans Mes réseaux mais échoue ailleurs.
"""
from __future__ import annotations

from typing import Any


ACCESS_COLUMNS = """
    a.id::text AS id,
    a.user_id::text AS user_id,
    a.workspace_id::text AS owner_workspace_id,
    a.provider,
    a.display_name,
    a.platform_account_name,
    a.external_account_id,
    a.external_parent_id,
    a.external_username,
    a.token_ciphertext,
    a.token_expires_at,
    a.scopes,
    a.metadata,
    a.is_active AS global_is_active,
    a.updated_at,
    (a.workspace_id = $2::uuid) AS is_owner_workspace,
    saw.is_active AS workspace_link_is_active,
    saw.revoked_at AS workspace_link_revoked_at,
    CASE
      WHEN saw.account_id IS NULL AND a.workspace_id = $2::uuid THEN true
      ELSE COALESCE(saw.is_active, false) AND saw.revoked_at IS NULL
    END AS workspace_is_active,
    a.is_active AND (
      CASE
        WHEN saw.account_id IS NULL AND a.workspace_id = $2::uuid THEN true
        ELSE COALESCE(saw.is_active, false) AND saw.revoked_at IS NULL
      END
    ) AS is_active
"""


def accessible_account_query(*, active_only: bool = False) -> str:
    active_clause = """
      AND a.is_active = true
      AND (
        CASE
          WHEN saw.account_id IS NULL AND a.workspace_id = $2::uuid THEN true
          ELSE COALESCE(saw.is_active, false) AND saw.revoked_at IS NULL
        END
      ) = true
    """ if active_only else ""
    return f"""
        SELECT {ACCESS_COLUMNS}
        FROM public.app_social_accounts a
        LEFT JOIN public.app_social_account_workspaces saw
          ON saw.account_id = a.id AND saw.workspace_id = $2::uuid
        WHERE a.id = $1::uuid
          AND a.deleted_at IS NULL
          AND (a.workspace_id = $2::uuid OR saw.account_id IS NOT NULL)
          AND (saw.revoked_at IS NULL OR saw.account_id IS NULL)
          {active_clause}
        LIMIT 1
    """


async def fetch_accessible_account(conn: Any, account_id: str, workspace_id: str, *, active_only: bool = False):
    if not account_id or not workspace_id:
        return None
    return await conn.fetchrow(accessible_account_query(active_only=active_only), account_id, workspace_id)


async def ensure_local_workspace_link(conn: Any, account_id: str, workspace_id: str, user_id: str) -> None:
    """Crée/réactive le lien du workspace d'origine sans dupliquer le token."""
    await conn.execute(
        """
        INSERT INTO public.app_social_account_workspaces (
            account_id, workspace_id, granted_by, role, is_active,
            share_source, shared_at, revoked_at, created_at, updated_at
        ) VALUES ($1::uuid,$2::uuid,$3::uuid,'publisher',true,'local',NULL,NULL,now(),now())
        ON CONFLICT (account_id, workspace_id)
        DO UPDATE SET granted_by=EXCLUDED.granted_by, role='publisher', is_active=true,
                      share_source='local', revoked_at=NULL, updated_at=now()
        """,
        account_id, workspace_id, user_id,
    )


async def ensure_explicit_workspace_link(conn: Any, account_id: str, workspace_id: str, user_id: str) -> None:
    """Crée/réactive un partage explicite vers un autre workspace."""
    await conn.execute(
        """
        INSERT INTO public.app_social_account_workspaces (
            account_id, workspace_id, granted_by, role, is_active,
            share_source, shared_at, revoked_at, created_at, updated_at
        ) VALUES ($1::uuid,$2::uuid,$3::uuid,'publisher',true,'explicit',now(),NULL,now(),now())
        ON CONFLICT (account_id, workspace_id)
        DO UPDATE SET granted_by=EXCLUDED.granted_by, role='publisher', is_active=true,
                      share_source='explicit', shared_at=now(), revoked_at=NULL, updated_at=now()
        """,
        account_id, workspace_id, user_id,
    )
