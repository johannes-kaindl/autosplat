# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from autosplat import __version__

router = APIRouter()


@router.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})
