import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routers import parts

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


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/icon48.png")


@app.get("/privacy", include_in_schema=False)
async def privacy():
    return FileResponse(STATIC_DIR / "privacy.html")
