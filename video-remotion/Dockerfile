FROM node:22-bookworm-slim

# System libraries Remotion's headless Chrome needs, plus the user-selectable
# font library (all open-license Debian packages; compositions reference them
# via CSS fontFamily, no @font-face) and fontconfig so renderer text resolves.
# ffmpeg for local muxing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates fontconfig fonts-inter fonts-liberation2 ffmpeg \
        fonts-roboto fonts-open-sans fonts-lato fonts-bebas-neue \
        fonts-ebgaramond fonts-cantarell fonts-jetbrains-mono fonts-firacode \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
        libcairo2 libasound2 libatspi2.0-0 libx11-6 libxcb1 libxext6 libxi6 \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Pre-install the headless Chromium at build time so the first render does not pay for it.
RUN npx remotion browser ensure
EXPOSE 8090
CMD ["npm", "run", "server"]
