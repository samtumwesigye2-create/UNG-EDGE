from __future__ import annotations
import os
import httpx

ZIPPER_URL = os.getenv("UNG_ZIPPER_URL", "").rstrip("/")
UGAMAP_URL = os.getenv("UNG_UGAMAP_URL", "https://uganda-grid-api-clean-production.up.railway.app").rstrip("/")

async def _get(url: str, headers: dict):
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

async def zipper_validate(code: str, headers: dict):
    if not ZIPPER_URL:
        return {"configured": False, "code": code.zfill(5) if code.isdigit() else code, "valid": False}
    return await _get(f"{ZIPPER_URL}/zipper/validate/{code}", headers)

async def zipper_resolve(code: str, headers: dict):
    if not ZIPPER_URL:
        return {"configured": False, "code": code.zfill(5) if code.isdigit() else code}
    return await _get(f"{ZIPPER_URL}/zipper/{code}", headers)

async def ugamap_zipper(headers: dict):
    if not UGAMAP_URL:
        return {"type": "FeatureCollection", "features": []}
    return await _get(f"{UGAMAP_URL}/geography/zipper", headers)
