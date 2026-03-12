FROM node:20-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY package.json .
RUN npm install --production
COPY server.js .
COPY skills/ ./skills/

RUN mkdir -p /workspace

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://127.0.0.1:3000/health || exit 1

CMD ["node", "server.js"]
