"""Schémas Pydantic liés à l'utilisateur/session — Cahier technique §4.2."""
from __future__ import annotations

from pydantic import BaseModel


class WorkspaceRef(BaseModel):
    id: str
    name: str
    role: str
    is_personal: bool
    is_active: bool
    is_super_admin_access: bool
    owner_name: str = ""
    owner_email: str = ""

    @property
    def display_name(self) -> str:
        if not self.is_personal or not self.is_super_admin_access:
            return self.name
        owner = (self.owner_name or "").strip() or (self.owner_email or "").strip()
        return f"{self.name} · {owner}" if owner else self.name


class AuthUser(BaseModel):
    id: str
    email: str
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    role: str = "user"
    timezone: str = "Europe/Paris"
    is_super_admin: bool = False
    session_id: str
    request_token: str
    active_workspace_id: str = ""
    active_workspace_name: str = ""
    active_workspace_role: str = ""
    workspaces: list[WorkspaceRef] = []

    @property
    def active_workspace_display_name(self) -> str:
        active_id = (self.active_workspace_id or "").strip()
        for workspace in self.workspaces:
            if workspace.id == active_id:
                return workspace.display_name
        return self.active_workspace_name or "Workspace"

    @property
    def initials(self) -> str:
        """Port exact du calcul d'initiales de authDropdownHtml()."""
        first = (self.first_name or "").strip()
        last = (self.last_name or "").strip()
        initials = ((first[:1] if first else "") + (last[:1] if last else "")).upper()
        if initials:
            return initials
        source = (self.full_name or "").strip() or (self.email or "").strip()
        return (source[:1] or "U").upper()
