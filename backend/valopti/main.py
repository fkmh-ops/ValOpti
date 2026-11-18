"""ValOpti — API FastAPI. Lancer : uvicorn valopti.main:app --reload (depuis backend/)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import cache
from .routers import catalog, draft, entities

FRONT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    cache.load()
    yield


app = FastAPI(title="ValOpti API", version="1.0.0", lifespan=lifespan,
              description="Scouting, Draft Maker et prédictions Valorant à partir des données vlr.gg nettoyées.")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

for r in (catalog.router, entities.router, draft.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["catalogue"])
def health():
    return {"status": "ok", "snapshot_date": cache.CACHE.snapshot_date}


# En production, le front compilé (frontend/dist) est servi par la même application
if FRONT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONT_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = FRONT_DIST / path
        return FileResponse(f if path and f.is_file() else FRONT_DIST / "index.html")
