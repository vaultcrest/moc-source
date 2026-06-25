from contextlib import asynccontextmanager

from fastapi import FastAPI

from .routers import parts


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


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
