#!/usr/bin/env bash
# board-stop.sh — Disable heartbeats for all MC board agents
#
# Usage: bash scripts/board-stop.sh
#
# What it does:
#   1. Updates MC database: sets heartbeat_config.every = "0m" for all board agents
#   2. Saves original intervals in a backup table for restore
#   3. Updates gateway openclaw.json: sets heartbeat.every = "0m"
#   4. Clears all agent session transcripts on the gateway
#
# The MC lifecycle reconcile worker reads from the database, so we MUST
# update the database — otherwise it will overwrite gateway config changes.

set -euo pipefail

MC_DB_HOST="192.168.2.66"
MC_DB="mission_control"
MC_DB_USER="postgres"
MC_DB_PASS="postgres"
GATEWAY_HOST="192.168.2.60"
GATEWAY_CONFIG="/root/.openclaw/openclaw.json"
GATEWAY_AGENTS_DIR="/root/.openclaw/agents"

PSQL="PGPASSWORD=$MC_DB_PASS psql -U $MC_DB_USER -h 127.0.0.1 -d $MC_DB -t -A"

echo "=== Board Stop ==="

# Step 1: Backup and disable heartbeats in MC database
echo ""
echo "--- Step 1: Updating MC database ---"
ssh root@$MC_DB_HOST "$PSQL -c \"
  -- Create backup table if needed
  CREATE TABLE IF NOT EXISTS _heartbeat_backup (
    agent_id UUID PRIMARY KEY,
    heartbeat_config JSONB,
    backed_up_at TIMESTAMPTZ DEFAULT now()
  );
  -- Save current values (upsert)
  INSERT INTO _heartbeat_backup (agent_id, heartbeat_config)
  SELECT id, heartbeat_config FROM agents
  WHERE heartbeat_config IS NOT NULL
    AND name != 'OpenClaw Primary Gateway Agent'
  ON CONFLICT (agent_id) DO UPDATE SET
    heartbeat_config = EXCLUDED.heartbeat_config,
    backed_up_at = now();
\""
echo "  Backed up heartbeat configs"

ssh root@$MC_DB_HOST "$PSQL" << 'SQLEOF'
  UPDATE agents
  SET heartbeat_config = (heartbeat_config::jsonb || '{"every": "0m"}'::jsonb)::json
  WHERE heartbeat_config IS NOT NULL
    AND name != 'OpenClaw Primary Gateway Agent';
SQLEOF
echo "  Set heartbeat_config.every = 0m for all board agents"

ssh root@$MC_DB_HOST "$PSQL" << 'SQLEOF'
  UPDATE agents
  SET status = 'offline'
  WHERE heartbeat_config IS NOT NULL
    AND name != 'OpenClaw Primary Gateway Agent'
    AND status NOT IN ('offline', 'deleting');
SQLEOF
echo "  Set status = offline for all board agents"

# Verify
echo ""
echo "  Database state:"
ssh root@$MC_DB_HOST "$PSQL -c \"
  SELECT name, heartbeat_config->>'every' as every FROM agents
  WHERE heartbeat_config IS NOT NULL ORDER BY name;
\"" | while read line; do echo "    $line"; done

# Step 2: Update gateway config
echo ""
echo "--- Step 2: Updating gateway config ---"
ssh root@$GATEWAY_HOST "python3 -c \"
import json

with open('$GATEWAY_CONFIG') as f:
    data = json.load(f)

saved = {}
for a in data.get('agents', {}).get('list', []):
    aid = a.get('id', '')
    if 'gateway' in aid or not (aid.startswith('mc-') or aid.startswith('lead-')):
        continue
    hb = a.get('heartbeat', {})
    saved[aid] = hb.get('every', 'default')
    hb['every'] = '0m'
    a['heartbeat'] = hb

with open('$GATEWAY_CONFIG', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')

with open('$GATEWAY_CONFIG.heartbeat-backup', 'w') as f:
    json.dump(saved, f, indent=2)

print(f'  {len(saved)} agents set to 0m in gateway config')
\""

# Step 3: Clear sessions
echo ""
echo "--- Step 3: Clearing sessions ---"
ssh root@$GATEWAY_HOST "
count=0
for agent_dir in $GATEWAY_AGENTS_DIR/mc-* $GATEWAY_AGENTS_DIR/lead-*; do
    [ -d \"\$agent_dir/sessions\" ] || continue
    agent_id=\$(basename \$agent_dir)
    [[ \"\$agent_id\" == *gateway* ]] && continue

    # Backup and remove .jsonl files
    for f in \$agent_dir/sessions/*.jsonl; do
        [ -f \"\$f\" ] || continue
        mv \"\$f\" \"\$f.board-stop-\$(date +%Y%m%dT%H%M%S).bak\"
        count=\$((count + 1))
    done

    # Clear sessions.json entries
    if [ -f \"\$agent_dir/sessions/sessions.json\" ]; then
        python3 -c \"
import json
with open('\$agent_dir/sessions/sessions.json') as f:
    data = json.load(f)
keys = [k for k in data if 'mc-' in k or 'lead-' in k]
for k in keys: del data[k]
with open('\$agent_dir/sessions/sessions.json', 'w') as f:
    json.dump(data, f, indent=2)
\"
    fi
done
echo \"  \$count session transcripts backed up and cleared\"
"

# Step 4: Send /pause to board memory (syncs UI state)
echo ""
echo "--- Step 4: Pausing board in UI ---"
ssh root@$MC_DB_HOST "PGPASSWORD=$MC_DB_PASS psql -U $MC_DB_USER -h 127.0.0.1 -d $MC_DB -c \"
  INSERT INTO board_memory (id, board_id, content, tags, source, is_chat, created_at)
  SELECT gen_random_uuid(), id, '/pause', '[\"chat\"]'::json, 'user', true, NOW()
  FROM boards WHERE name ILIKE '%dev%' LIMIT 1;
\"" 2>/dev/null
echo "  Board paused in UI"

echo ""
echo "=== Done. Heartbeats OFF in both database and gateway. ==="
echo "=== Run board-start.sh to restore. ==="
