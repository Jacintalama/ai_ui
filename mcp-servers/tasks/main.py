"""Tasks service — admin task approval and AI execution."""
import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tasks")

app = FastAPI(title="Tasks Service", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tasks"}
