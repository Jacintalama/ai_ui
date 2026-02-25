# mcp-servers/scheduler/Dockerfile
# Scheduler MCP Server — FastAPI app with OpenAPI spec
# No mcpo needed: this is already an HTTP server (not MCP stdio)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
