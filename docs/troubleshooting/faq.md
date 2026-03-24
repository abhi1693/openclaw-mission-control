# Frequently Asked Questions (FAQ)

This FAQ addresses common questions and issues when setting up and using OpenClaw Mission Control.

## Table of Contents

- [General Questions](#general-questions)
- [Installation & Setup](#installation--setup)
- [Gateway Configuration](#gateway-configuration)
- [Authentication Issues](#authentication-issues)
- [Connection Problems](#connection-problems)
- [Agent & Board Issues](#agent--board-issues)
- [Performance & Scaling](#performance--scaling)

---

## General Questions

### What is the difference between OpenClaw and Mission Control?

**OpenClaw** is the runtime environment that executes AI agent tasks on your local machine or server. It provides the `openclaw` CLI and Gateway WebSocket server.

**Mission Control** is the web-based control plane that manages multiple OpenClaw instances. It provides:
- A unified dashboard for all your agents
- Board/task management
- Gateway connections
- Approval workflows
- Audit logging

Think of OpenClaw as the "engine" and Mission Control as the "dashboard and control center."

### Do I need both OpenClaw and Mission Control?

No, they can be used independently:

- **OpenClaw alone**: Use the CLI (`openclaw gateway start`, `openclaw exec`) for local agent execution
- **Mission Control alone**: Manage and monitor agents through the web UI (requires connecting to OpenClaw Gateway)
- **Together**: Get the full experience with centralized management + local execution

### What are the system requirements?

**Minimum:**
- 2 CPU cores
- 4GB RAM
- Docker + Docker Compose v2.22.0+
- Linux or macOS

**Recommended:**
- 4+ CPU cores
- 8GB+ RAM
- SSD storage

---

## Installation & Setup

### The installer fails with "Docker not found"

**Problem**: Running `./install.sh` or the curl command shows Docker is not found.

**Solutions:**

1. **Install Docker first**:
   ```bash
   # Ubuntu/Debian
   curl -fsSL https://get.docker.com | sh
   
   # macOS
   brew install --cask docker
   ```

2. **Add your user to the docker group** (Linux):
   ```bash
   sudo usermod -aG docker $USER
   # Log out and back in for changes to take effect
   ```

3. **Verify Docker works**:
   ```bash
   docker run hello-world
   ```

### "LOCAL_AUTH_TOKEN must be at least 50 characters"

**Problem**: The backend fails to start with this error.

**Solution**: Generate a secure token:

```bash
# Option 1: Use openssl
openssl rand -base64 40

# Option 2: Use Python
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

# Option 3: Use /dev/urandom
cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 50 | head -n 1
```

Then set it in your `.env`:
```bash
LOCAL_AUTH_TOKEN=your-generated-token-here
```

### How do I upgrade to a new version?

1. Pull the latest changes:
   ```bash
   git pull origin master
   ```

2. Rebuild and restart:
   ```bash
   docker compose -f compose.yml --env-file .env up -d --build --force-recreate
   ```

3. Verify the upgrade:
   ```bash
   curl http://localhost:8000/healthz
   ```

---

## Gateway Configuration

### How do I connect Mission Control to my OpenClaw Gateway?

**Step-by-step:**

1. **Start your OpenClaw Gateway**:
   ```bash
   openclaw gateway start
   ```
   Default port is 18789.

2. **In Mission Control**, go to **Settings → Gateways → Add Gateway**

3. **Configure the connection**:
   | Field | Value (Local) | Value (Remote) |
   |-------|---------------|----------------|
   | Gateway URL | `ws://localhost:18789` | `wss://your-server:18789` |
   | Workspace Root | `~/.openclaw` | Path on the remote server |
   | Allow self-signed TLS | Off | On (if using self-signed certs) |

4. **Test the connection** - Click "Test Connection" or save and check the status indicator

### "Connection refused" when adding a gateway

**Problem**: Cannot connect to the OpenClaw Gateway.

**Checklist:**

1. **Is the gateway running?**
   ```bash
   openclaw gateway status
   # Should show: Gateway is running on port 18789
   ```

2. **Is the port correct?**
   ```bash
   # Check what port OpenClaw is using
   openclaw gateway status | grep port
   
   # Check if the port is listening
   netstat -tlnp | grep 18789
   # or
   lsof -i :18789
   ```

3. **Firewall issues?**
   ```bash
   # Check if port is open
   nc -zv localhost 18789
   ```

4. **Using Docker?** You need to use the Docker host IP:
   - macOS/Windows: `ws://host.docker.internal:18789`
   - Linux: `ws://172.17.0.1:18789` (or your docker0 bridge IP)

### Should I use `ws://` or `wss://`?

| Protocol | Use Case | Security |
|----------|----------|----------|
| `ws://` | Local development only | ❌ Unencrypted |
| `wss://` | Production, remote servers | ✅ Encrypted |

**Always use `wss://` for:**
- Remote servers
- Production environments
- Any network you don't fully control

### How do I use self-signed certificates?

1. When adding/editing a gateway in Mission Control, enable **"Allow self-signed TLS certificates"**

2. This skips certificate verification - only use this for:
   - Development environments
   - Internal networks you control
   - Testing

For production, use certificates from a trusted CA (Let's Encrypt, etc.).

---

## Authentication Issues

### "401 Unauthorized" or "Invalid token" errors

**Problem**: API calls fail with authentication errors.

**Solutions:**

1. **Check your token**:
   ```bash
   # Test your token
   curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/v1/health
   ```

2. **Token may have drifted** (especially after reinstalls):
   
   Re-sync tokens via Mission Control:
   - Go to **Settings → Gateways**
   - Click **"Sync Templates with Token Rotation"**
   
   Or via API:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/gateways/GATEWAY_ID/templates/sync?rotate_tokens=true" \
     -H "Authorization: Bearer YOUR_LOCAL_AUTH_TOKEN"
   ```

3. **Verify AUTH_MODE**:
   - Check `.env` has `AUTH_MODE=local` (or `clerk` if using Clerk)
   - For `local` mode, ensure `LOCAL_AUTH_TOKEN` is set and ≥ 50 characters

### What's the difference between LOCAL_AUTH_TOKEN and Gateway Token?

| Token | Purpose | Where to Set |
|-------|---------|--------------|
| `LOCAL_AUTH_TOKEN` | Authenticate API requests to Mission Control | `.env` file |
| Gateway Token | Authenticate Gateway WebSocket connection | Generated automatically, stored in Mission Control |

You typically only need to worry about `LOCAL_AUTH_TOKEN` during setup.

---

## Connection Problems

### Frontend loads but API calls fail

**Symptoms**: The Mission Control UI loads but shows errors or blank data.

**Check `NEXT_PUBLIC_API_URL`:**

1. In your `.env` file, check:
   ```bash
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

2. **Important**: This URL must be **reachable from your browser**, not just from the server.

3. **Common mistakes:**
   - Using `http://backend:8000` (Docker internal hostname - won't work from browser)
   - Using `http://127.0.0.1:8000` (may fail in some Docker setups)
   - Using `http://localhost:8000` when accessing from another machine

4. **Fix for remote access:**
   ```bash
   # Use the actual IP or domain
   NEXT_PUBLIC_API_URL=http://192.168.1.100:8000
   # or
   NEXT_PUBLIC_API_URL=https://mc-api.example.com
   ```

### CORS errors in browser console

**Problem**: Browser shows "CORS policy" errors.

**Solution**: Add your frontend origin to `CORS_ORIGINS` in `.env`:

```bash
# For local development
CORS_ORIGINS=http://localhost:3000

# For multiple origins
CORS_ORIGINS=http://localhost:3000,https://mc.example.com

# For any origin (development only!)
CORS_ORIGINS=*
```

Restart the backend after changing this:
```bash
docker compose -f compose.yml --env-file .env restart backend
```

---

## Agent & Board Issues

### Board onboarding is stuck

**Problem**: Creating a board shows indefinite "provisioning" or "creating" state.

**Checklist:**

1. **Is the queue worker running?**
   ```bash
   # Check running containers
   docker compose ps
   
   # You should see: backend, frontend, db, redis, worker
   ```

2. **Check worker logs**:
   ```bash
   docker compose logs -f worker
   ```

3. **Redis connectivity**:
   ```bash
   # Verify Redis is accessible
   docker compose exec backend redis-cli -h redis ping
   # Should return: PONG
   ```

4. **Force retry**:
   - Go to **Settings → Gateways**
   - Click **"Sync Templates"** for your gateway
   - Try creating the board again

### Agents show as "offline"

**Problem**: Gateway is connected but agents show offline status.

**Troubleshooting steps:**

1. **Check the agent provisioning flow**:
   ```bash
   # View logs
   docker compose logs -f worker | grep lifecycle
   ```

2. **Expected log pattern**:
   ```
   lifecycle.queue.enqueued
   queue.worker.success
   lifecycle.reconcile.skip_not_stuck
   ```

3. **If you see repeated `lifecycle.reconcile.retriggered`**:
   - Agent is not checking in
   - Check gateway logs: `openclaw gateway logs`
   - Verify agent token is valid

4. **Manual wake**:
   - In Mission Control, go to the agent
   - Click **"Update/Provision"** to trigger a new wake

### "exec command permission" errors

**Problem**: Tasks fail with permission errors when running commands.

**Solutions:**

1. **Check container user**:
   The backend runs as non-root user (`appuser`). Ensure:
   - File permissions allow `appuser` to read/write
   - Bind mounts have correct ownership

2. **Fix permissions**:
   ```bash
   # Find the container user UID
   docker compose exec backend id
   # Example: uid=1000(appuser)
   
   # Fix host directory ownership
   sudo chown -R 1000:1000 /path/to/mount
   ```

3. **For Docker-in-Docker scenarios**:
   You may need to run with elevated privileges or adjust the Docker socket permissions.

---

## Performance & Scaling

### Mission Control feels slow

**Optimization tips:**

1. **Database**: Ensure Postgres has enough resources
   ```bash
   # Check DB performance
   docker compose exec db psql -U postgres -c "SELECT * FROM pg_stat_activity;"
   ```

2. **Redis**: Verify Redis is not memory-constrained
   ```bash
   docker compose exec redis redis-cli info memory
   ```

3. **Frontend**: Clear browser cache or check browser DevTools Network tab for slow requests

4. **Worker scaling**: For high task volume, you can run multiple workers:
   ```bash
   docker compose up -d --scale worker=3
   ```

### How do I back up my data?

**Backup Postgres:**
```bash
# Create backup
docker compose exec db pg_dump -U postgres mission_control > backup.sql

# Restore backup
cat backup.sql | docker compose exec -T db psql -U postgres
```

**Backup volumes:**
```bash
# Stop the stack
docker compose down

# Backup the volume
docker run --rm -v openclaw-mission-control_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres-backup.tar.gz -C /data .

# Start the stack
docker compose up -d
```

---

## Still Having Issues?

If this FAQ doesn't resolve your problem:

1. **Check the logs**:
   ```bash
   docker compose logs -f
   ```

2. **Review detailed troubleshooting guides**:
   - [Gateway Agent Provisioning](./gateway-agent-provisioning.md)
   - [Gateway WebSocket Protocol](../openclaw_gateway_ws.md)

3. **Search existing issues**:
   https://github.com/abhi1693/openclaw-mission-control/issues

4. **Join the Slack community**:
   https://join.slack.com/t/oc-mission-control/

5. **Create a new issue** with:
   - Mission Control version (`git log --oneline -1`)
   - OpenClaw version (`openclaw version`)
   - Relevant logs (sanitized)
   - Steps to reproduce
