"""Private grid preferences, always scoped to the authenticated user and workspace."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.database import get_pool
from app.dependencies.auth import require_auth

router = APIRouter(tags=["Table preferences"])
View = Literal["posts", "publications", "strategies", "networks", "users", "members", "invitations", "publication_calendar"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GridFilter(StrictModel):
    field: str = Field(pattern=r"^c\d{1,2}$")
    operator: Literal["equal", "notequal", "contains", "doesnotcontain", "startswith", "endswith",
                      "doesnotstartwith", "doesnotendwith", "greaterthan", "greaterthanorequal",
                      "lessthan", "lessthanorequal", "isnull", "isnotnull", "isempty", "isnotempty"]
    value: str | int | float | bool | None | list[str | int | float | bool | None] = None
    predicate: Literal["and", "or"] = "and"
    matchCase: bool = False
    ignoreAccent: bool = True
    type: Literal["string", "number", "boolean", "date", "datetime"] | None = None


class GridSort(StrictModel):
    field: str = Field(pattern=r"^c\d{1,2}$")
    direction: Literal["Ascending", "Descending"]


class GridColumn(StrictModel):
    field: str = Field(pattern=r"^c\d{1,2}$")
    width: float = Field(175, ge=40, le=2000)
    visible: bool = True


class GridState(StrictModel):
    version: Literal[1] = 1
    columnCount: int = Field(ge=1, le=60)
    filters: list[GridFilter] = Field(default_factory=list, max_length=100)
    sort: list[GridSort] = Field(default_factory=list, max_length=60)
    search: str = Field("", max_length=500)
    pageSize: Literal[10, 20, 50, 100] = 10
    columns: list[GridColumn] = Field(default_factory=list, max_length=60)
    pageFilters: dict[str, str] = Field(default_factory=dict)

    @field_validator("pageFilters")
    @classmethod
    def valid_page_filters(cls, value):
        if any(k not in {"origin", "q", "status", "filter"} or len(v) > 500 for k, v in value.items()):
            raise ValueError("Invalid page filters")
        return value

    @model_validator(mode="after")
    def valid_fields_and_size(self):
        for item in [*self.filters, *self.sort, *self.columns]:
            if int(item.field[1:]) >= self.columnCount:
                raise ValueError("Unknown column")
        if len({c.field for c in self.columns}) != len(self.columns):
            raise ValueError("Duplicate columns")
        if self.columns and not any(c.visible for c in self.columns):
            raise ValueError("At least one column must be visible")
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > 32768:
            raise ValueError("Preferences too large")
        return self


class CalendarState(StrictModel):
    mode: Literal["all", "actions", "publications"] = "all"
    kind: Literal["calendar"] = "calendar"
    version: Literal[1] = 1
    activeView: Literal["Day", "Week", "Month", "Agenda"] = "Month"
    status: Literal["all", "scheduled", "published", "failed", "pending", "processing", "cancelled"] = "all"
    platform: str = Field("all", max_length=32, pattern=r"^[a-z_]+$")


class PreferencePayload(StrictModel):
    state: GridState | CalendarState
    revision: int = Field(ge=0, le=9007199254740991)


@router.get("/table-preferences")
async def get_table_preferences(user=Depends(require_auth)):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT view_key, state, revision FROM public.user_table_preferences WHERE user_id=$1::uuid AND workspace_id=$2::uuid",
            user.id, user.active_workspace_id,
        )
    return {"success": True, "data": {row["view_key"]: {
        "state": json.loads(row["state"]) if isinstance(row["state"], str) else row["state"],
        "revision": row["revision"],
    } for row in rows}}


@router.put("/table-preferences/{view_key}")
async def save_table_preferences(view_key: View, payload: PreferencePayload, user=Depends(require_auth)):
    if (view_key == "publication_calendar") != isinstance(payload.state, CalendarState):
        raise HTTPException(status_code=422, detail="Invalid preference type")
    if view_key == "users" and not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO public.user_table_preferences (user_id, workspace_id, view_key, state, revision)
               VALUES ($1::uuid,$2::uuid,$3,$4::jsonb,$5)
               ON CONFLICT (user_id,workspace_id,view_key)
               DO UPDATE SET state=EXCLUDED.state, revision=EXCLUDED.revision, updated_at=now()
               WHERE user_table_preferences.revision < EXCLUDED.revision""",
            user.id, user.active_workspace_id, view_key, json.dumps(payload.state.model_dump()), payload.revision,
        )
    return {"success": True}
