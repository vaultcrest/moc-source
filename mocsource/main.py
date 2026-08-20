import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import parts

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)s [%(name)s] %(message)s",
)

STATIC_DIR = pathlib.Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="MOC Source",
    description="LEGO MOC part sourcing and acquisition planning tool",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(parts.router)

# Static pages — add new HTML files to static/ and wire up a route below
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/icon48.png")


@app.get("/privacy", include_in_schema=False)
async def privacy():
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/guide", include_in_schema=False)
async def guide():
    return FileResponse(STATIC_DIR / "guide.html")


@app.get("/studio-palettes", include_in_schema=False)
async def studio_palettes():
    return FileResponse(STATIC_DIR / "studio-palettes.html")
