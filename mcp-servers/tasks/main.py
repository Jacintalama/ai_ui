"""Tasks service — admin task approval and AI execution."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from db import init_db
from routes_webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tasks")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialized")
    yield


app = FastAPI(title="Tasks Service", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tasks"}
