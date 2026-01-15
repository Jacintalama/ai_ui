# Open WebUI Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy Open WebUI locally with Docker Compose, then prepare for cloud deployment for shared team access.

**Architecture:** Two-phase deployment - Phase 1 is local Docker Compose setup for immediate use. Phase 2 is cloud deployment (VPS/cloud provider) with persistent storage, HTTPS, and team access.

**Tech Stack:** Docker, Docker Compose, Open WebUI, Ollama (optional), Nginx (for cloud), Let's Encrypt (HTTPS)

---

## Phase 1: Local Deployment (Today)

### Task 1: Verify Docker Desktop is Running

**Files:**
- None (system verification)

**Step 1: Check Docker is running**

Run:
```bash
docker --version
docker compose version
```
Expected: Version numbers displayed (e.g., Docker version 24.x.x, Docker Compose version v2.x.x)

**Step 2: Verify Docker daemon is active**

Run:
```bash
docker ps
```
Expected: Empty list or running containers (no error)

**If Docker not running:** Open Docker Desktop application and wait for it to start.

---

### Task 2: Create Project Directory Structure

**Files:**
- Create: `docker-compose.yml`
- Create: `.env`
- Create: `.gitignore`

**Step 1: Create docker-compose.yml**

```yaml
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    ports:
      - "3000:8080"
    volumes:
      - open-webui-data:/app/backend/data
    environment:
      - WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-}
    restart: unless-stopped

  # Optional: Uncomment if you want local Ollama
  # ollama:
  #   image: ollama/ollama:latest
  #   container_name: ollama
  #   volumes:
  #     - ollama-data:/root/.ollama
  #   ports:
  #     - "11434:11434"
  #   restart: unless-stopped

volumes:
  open-webui-data:
  # ollama-data:
```

**Step 2: Generate secret key and create .env file**

Run (PowerShell):
```powershell
$secret = -join ((48..57) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
Write-Output "WEBUI_SECRET_KEY=$secret" | Out-File -FilePath .env -Encoding utf8
Write-Output "OLLAMA_BASE_URL=" | Add-Content -Path .env
```

Or create `.env` manually:
```env
WEBUI_SECRET_KEY=your-random-32-character-string-here
OLLAMA_BASE_URL=
```

**Step 3: Create .gitignore**

```gitignore
.env
*.log
```

---

### Task 3: Start Open WebUI

**Files:**
- None (Docker commands)

**Step 1: Pull the latest image**

Run:
```bash
docker compose pull
```
Expected: Image downloaded successfully

**Step 2: Start the containers**

Run:
```bash
docker compose up -d
```
Expected: Container started in detached mode

**Step 3: Verify container is running**

Run:
```bash
docker compose ps
```
Expected: `open-webui` container showing "Up" status

**Step 4: Check logs for any errors**

Run:
```bash
docker compose logs -f open-webui
```
Expected: Startup logs, no errors. Press Ctrl+C to exit.

---

### Task 4: Initial Configuration

**Files:**
- None (Web UI configuration)

**Step 1: Access Open WebUI**

Open browser: http://localhost:3000

Expected: Open WebUI login/signup page

**Step 2: Create Admin Account**

- Click "Sign Up"
- Enter name, email, password
- **IMPORTANT:** First account becomes Administrator automatically

**Step 3: Configure LLM Connection (Admin Settings)**

Navigate to: Admin Panel > Settings > Connections

Option A - OpenAI API:
- Add OpenAI API key
- Models will auto-populate

Option B - Ollama (if running locally):
- Set Ollama URL: `http://host.docker.internal:11434`

Option C - Other OpenAI-compatible APIs:
- Add custom endpoint URL and API key

**Step 4: Test a conversation**

- Start new chat
- Select a model
- Send test message: "Hello, are you working?"
- Expected: Response from LLM

---

### Task 5: Commit Local Setup

**Step 1: Initialize git repository**

Run:
```bash
git init
git add docker-compose.yml .gitignore
git commit -m "feat: initial Open WebUI Docker Compose setup"
```

---

## Phase 2: Cloud Deployment (This Week)

### Task 6: Prepare Cloud Server

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `nginx.conf` (optional, for reverse proxy)

**Step 1: Create production docker-compose file**

```yaml
# docker-compose.prod.yml
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    ports:
      - "127.0.0.1:8080:8080"  # Only expose to localhost for nginx proxy
    volumes:
      - open-webui-data:/app/backend/data
    environment:
      - WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-}
      # Production settings
      - WEBUI_AUTH=True
      - DEFAULT_USER_ROLE=pending  # New users need admin approval
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Nginx reverse proxy with SSL
  nginx:
    image: nginx:alpine
    container_name: nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro  # SSL certificates
    depends_on:
      - open-webui
    restart: unless-stopped

volumes:
  open-webui-data:
```

**Step 2: Create nginx.conf for HTTPS**

```nginx
events {
    worker_connections 1024;
}

http {
    server {
        listen 80;
        server_name your-domain.com;
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name your-domain.com;

        ssl_certificate /etc/nginx/ssl/fullchain.pem;
        ssl_certificate_key /etc/nginx/ssl/privkey.pem;

        location / {
            proxy_pass http://open-webui:8080;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # WebSocket support
            proxy_read_timeout 86400;
        }
    }
}
```

---

### Task 7: Deploy to Cloud Server

**Step 1: SSH into cloud server**

```bash
ssh user@your-server-ip
```

**Step 2: Install Docker on server (if not installed)**

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

**Step 3: Copy files to server**

From local machine:
```bash
scp docker-compose.prod.yml .env nginx.conf user@your-server-ip:~/open-webui/
```

**Step 4: Start production deployment**

On server:
```bash
cd ~/open-webui
docker compose -f docker-compose.prod.yml up -d
```

**Step 5: Setup SSL with Let's Encrypt (recommended)**

```bash
# Install certbot
sudo apt install certbot

# Get certificate
sudo certbot certonly --standalone -d your-domain.com

# Copy to ssl folder
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ./ssl/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem ./ssl/
```

**Step 6: Restart nginx to apply SSL**

```bash
docker compose -f docker-compose.prod.yml restart nginx
```

---

### Task 8: Configure Team Access

**Step 1: Access production Open WebUI**

Open: https://your-domain.com

**Step 2: Create admin account (first signup)**

**Step 3: Configure user settings**

Admin Panel > Settings > Users:
- Set `DEFAULT_USER_ROLE=pending` (users need approval)
- Or `DEFAULT_USER_ROLE=user` (auto-approve)

**Step 4: Invite team members**

Share URL with team, or configure SSO/LDAP if enterprise.

---

## Quick Reference Commands

### Local Development
```bash
# Start
docker compose up -d

# Stop
docker compose down

# View logs
docker compose logs -f

# Update to latest
docker compose pull && docker compose up -d

# Backup data
docker run --rm -v open-webui-data:/data -v $(pwd):/backup alpine tar czf /backup/open-webui-backup.tar.gz /data
```

### Production
```bash
# Start
docker compose -f docker-compose.prod.yml up -d

# Stop
docker compose -f docker-compose.prod.yml down

# Update
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Can't access localhost:3000 | Check `docker compose ps`, verify container is running |
| "Connection refused" to Ollama | Use `host.docker.internal:11434` not `localhost` |
| Logged out after restart | Ensure `WEBUI_SECRET_KEY` is set in `.env` |
| Permission denied (Linux) | Add user to docker group: `sudo usermod -aG docker $USER` |
| SSL certificate issues | Verify cert paths in nginx.conf, check file permissions |

---

## Security Checklist (Production)

- [ ] `WEBUI_SECRET_KEY` is set and secure (32+ random chars)
- [ ] HTTPS enabled with valid SSL certificate
- [ ] Firewall configured (only ports 80, 443 open)
- [ ] `DEFAULT_USER_ROLE=pending` for controlled access
- [ ] Regular backups configured
- [ ] Docker images updated regularly
