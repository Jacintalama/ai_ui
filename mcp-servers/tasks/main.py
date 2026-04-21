"""Tasks service — admin task approval and AI execution."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from db import init_db
from routes_cron import router as cron_router
from routes_execution import router as execution_router
from routes_preview import router as preview_router
from routes_tasks import router as tasks_router
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
app.include_router(tasks_router)
app.include_router(execution_router)
app.include_router(cron_router)
app.include_router(preview_router)
app.mount("/tasks/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tasks"}
