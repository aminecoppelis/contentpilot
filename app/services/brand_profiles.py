"""Reusable creation settings, isolated by user and active workspace."""
import json
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.database import get_pool


class BrandProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    company: str = Field(default='', max_length=200)
    website: str = Field(default='', max_length=500)
    solution: str = Field(default='', max_length=1000)
    default_tags: str = Field(default='', max_length=1000)
    constraints: str = Field(default='', max_length=900)
    use_macaron: StrictBool = True
    auto_apply: StrictBool = False


async def load_brand_profile(user_id, workspace_id):
    async with get_pool().acquire() as conn:
        value = await conn.fetchval('''SELECT settings FROM public.app_creation_brand_profiles
            WHERE user_id=$1::uuid AND workspace_id=$2::uuid''', user_id, workspace_id)
    if value is None:
        return None
    return BrandProfile.model_validate(json.loads(value) if isinstance(value, str) else value).model_dump()


async def save_brand_profile(user_id, workspace_id, profile):
    async with get_pool().acquire() as conn:
        await conn.execute('''INSERT INTO public.app_creation_brand_profiles (user_id,workspace_id,settings)
            VALUES ($1::uuid,$2::uuid,$3::jsonb) ON CONFLICT (user_id,workspace_id)
            DO UPDATE SET settings=EXCLUDED.settings, updated_at=now()''',
            user_id, workspace_id, json.dumps(profile.model_dump(), ensure_ascii=False))
