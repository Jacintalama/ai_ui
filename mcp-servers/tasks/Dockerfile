FROM python:3.11-slim

# Install Node.js (for @anthropic-ai/claude-code) and git
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8210
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8210"]
