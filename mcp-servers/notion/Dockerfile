# mcp-servers/notion/Dockerfile
# Notion MCP Server with mcpo HTTP wrapper
# Uses @notionhq/notion-mcp-server with internal integration token (ntn_*)
FROM node:20-slim

RUN apt-get update && apt-get install -y python3 python3-pip curl --no-install-recommends \
    && pip3 install --break-system-packages mcpo "mcp<2" "fastapi<0.130" \
    && npm install -g @notionhq/notion-mcp-server \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

EXPOSE 8000

CMD ["sh", "-c", "mcpo --host 0.0.0.0 --port 8000 --api-key \"$MCP_API_KEY\" -- npx @notionhq/notion-mcp-server"]
