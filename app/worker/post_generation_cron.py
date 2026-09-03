"""Récupération persistante des générations initiales/additionnelles laissées en file."""
from __future__ import annotations

from app.services.post_generation import process_job


async def run_post_generation_cycle() -> dict:
    return await process_job(None)
