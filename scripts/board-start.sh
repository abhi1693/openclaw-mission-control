#!/usr/bin/env bash
# board-start.sh — Re-enable heartbeats for all MC board agents
#
# Usage: bash scripts/board-start.sh
#
# What it does:
#   1. Restores heartbeat_config from _heartbeat_backup table in MC database
#   2. Sets agent status to 'online'
#   3. Restores gateway openclaw.json from MC database (source of truth)
#   4. Clears any leftover sessions (fresh start)
#   5. Restarts gateway to pick up new heartbeat timers
#   6. Runs Baileys group sync if WhatsApp groups are configured

set -euo pipefail

MC_DB_HOST="192.168.2.66"
MC_DB="mission_control"
MC_DB_USER="postgres"
MC_DB_PASS="postgres"
MC_APP_HOST="192.168.2.64"
GATEWAY_HOST="192.168.2.60"
GATEWAY_CONFIG="/root/.openclaw/openclaw.json"
GATEWAY_AGENTS_DIR="/root/.openclaw/agents"

PSQL="PGPASSWORD=$MC_DB_PASS psql -U $MC_DB_USER -h 127.0.0.1 -d $MC_DB -t -A"

echo "=== Board Start ==="

# Step 1: Restore heartbeats in MC database from backup table
echo ""
echo "--- Step 1: Restoring MC database ---"
ssh root@$MC_DB_HOST "$PSQL" << 'SQLEOF'
  UPDATE agents a
  SET heartbeat_config = b.heartbeat_config
  FROM _heartbeat_backup b
  WHERE a.id = b.agent_id;
SQLEOF
echo "  Restored heartbeat configs from backup"

# Step 2: Set agent status to online
ssh root@$MC_DB_HOST "$PSQL" << 'SQLEOF'
  UPDATE agents
  SET status = 'online'
  WHERE heartbeat_config IS NOT NULL
    AND name != 'OpenClaw Primary Gateway Agent'
    AND status = 'offline';
SQLEOF
echo "  Set status = online for all board agents"

# Verify
echo ""
echo "  Database state:"
ssh root@$MC_DB_HOST "$PSQL -c \"
  SELECT name, status, heartbeat_config->>'every' as every FROM agents
  WHERE heartbeat_config IS NOT NULL ORDER BY name;
\"" | while read line; do echo "    $line"; done

# Step 3: Restore gateway config FROM DATABASE (source of truth)
# This reads each agent's heartbeat_config->>'every' from the DB
# and applies it to the gateway config. No separate backup file needed.
echo ""
echo "--- Step 3: Restoring gateway config from database ---"

# Get agent intervals from DB as JSON
# Use openclaw_session_id to derive gateway agent ID (agent:KEY:main → KEY)
# This handles both mc-{uuid} workers and lead-{board_id} board leads
DB_INTERVALS=$(ssh root@$MC_DB_HOST "$PSQL" << 'SQLEOF'
  SELECT json_object_agg(
    split_part(openclaw_session_id, ':', 2),
    heartbeat_config->>'every'
  )::text
  FROM agents
  WHERE heartbeat_config IS NOT NULL
    AND openclaw_session_id IS NOT NULL
    AND name != 'OpenClaw Primary Gateway Agent';
SQLEOF
)

echo "$DB_INTERVALS" | ssh root@$GATEWAY_HOST "python3 -c \"
import json, sys

intervals = json.loads(sys.stdin.read().strip())

with open('$GATEWAY_CONFIG') as f:
    data = json.load(f)

count = 0
for a in data.get('agents', {}).get('list', []):
    aid = a.get('id', '')
    if aid in intervals and intervals[aid]:
        hb = a.get('heartbeat', {})
        hb['every'] = intervals[aid]
        a['heartbeat'] = hb
        count += 1

with open('$GATEWAY_CONFIG', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')

print(f'  {count} agents restored in gateway config')
\""

# Step 4: Clear sessions for fresh start
echo ""
echo "--- Step 4: Clearing sessions ---"
ssh root@$GATEWAY_HOST "
count=0
for agent_dir in $GATEWAY_AGENTS_DIR/mc-* $GATEWAY_AGENTS_DIR/lead-*; do
    [ -d \"\$agent_dir/sessions\" ] || continue
    agent_id=\$(basename \$agent_dir)
    [[ \"\$agent_id\" == *gateway* ]] && continue

    for f in \$agent_dir/sessions/*.jsonl; do
        [ -f \"\$f\" ] || continue
        mv \"\$f\" \"\$f.board-start-\$(date +%Y%m%dT%H%M%S).bak\"
        count=\$((count + 1))
    done

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
echo \"  \$count session transcripts cleared\"
"

# Step 5: Restart gateway to start fresh heartbeat timers
echo ""
echo "--- Step 5: Restarting gateway ---"
ssh root@$GATEWAY_HOST "systemctl --user restart openclaw-gateway"
echo "  Gateway restarted"

# Step 6: Wait for WhatsApp to connect, then sync groups (needed for group messaging)
echo ""
echo "--- Step 6: WhatsApp group sync ---"
sleep 10
if ssh root@$GATEWAY_HOST "test -f /tmp/sync-and-send.cjs"; then
    ssh root@$GATEWAY_HOST "systemctl --user stop openclaw-gateway && sleep 2 && node /tmp/sync-and-send.cjs 2>/dev/null && systemctl --user start openclaw-gateway" 2>&1 | grep -E 'Synced|Message sent|Connected|Done' || true
    echo "  Group sync complete"
else
    echo "  Skipped (no sync script found)"
fi

# Step 6b: Send /resume to board memory (syncs UI state)
echo ""
echo "--- Step 6b: Resuming board in UI ---"
ssh root@$MC_DB_HOST "$PSQL" << 'SQLEOF'
  INSERT INTO board_memory (id, board_id, content, tags, source, is_chat, created_at)
  SELECT gen_random_uuid(), id, '/resume', '["chat"]'::json, 'user', true, NOW()
  FROM boards WHERE name ILIKE '%dev%' LIMIT 1;
SQLEOF
echo "  Board resumed in UI"

# Step 7: Enable heartbeats
echo ""
echo "--- Step 7: Enabling heartbeats ---"
sleep 10

# Enable heartbeats via gateway CLI (no hardcoded token needed)
ssh root@$GATEWAY_HOST "openclaw gateway call set-heartbeats --params '{\"enabled\":true}' 2>&1 | grep -E '(ok|enabled|error|failed)'" && \
  echo "  heartbeatsEnabled = true" || \
  echo "  WARNING: could not enable heartbeats via RPC (gateway may not be running)"

# Step 7b: Sync templates FIRST to resync any token hashes that drifted during gateway restart
MC_API="http://$MC_APP_HOST:8000"
echo ""
echo "--- Step 7b: Syncing templates (token hash resync) ---"
LOCAL_AUTH_TOKEN=$(ssh root@$MC_APP_HOST "grep LOCAL_AUTH_TOKEN /home/mcontrol/openclaw-mission-control/backend/.env 2>/dev/null | sed 's/LOCAL_AUTH_TOKEN=//' | head -1")
GW_ID=$(curl -s -H "Authorization: Bearer $LOCAL_AUTH_TOKEN" "$MC_API/api/v1/gateways" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); items=d.get('items',d) if isinstance(d,dict) else d; print(items[0]['id'] if items else '')" 2>/dev/null)
if [ -n "$GW_ID" ]; then
  SYNC_RESULT=$(curl -s -X POST "$MC_API/api/v1/gateways/$GW_ID/templates/sync" \
    -H "Authorization: Bearer $LOCAL_AUTH_TOKEN" \
    -H "Content-Type: application/json" 2>/dev/null)
  synced=$(echo "$SYNC_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('agents_updated', d.get('agents_synced','?')))" 2>/dev/null)
  errors=$(echo "$SYNC_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('errors',[])))" 2>/dev/null)
  echo "  Synced: $synced agents, $errors errors"
else
  echo "  WARNING: could not find gateway ID for template sync"
fi

# Step 7c: Check in all agents AFTER token hashes are resynced
echo ""
echo "--- Step 7c: Initial agent check-in ---"
TOKENS=$(ssh root@$GATEWAY_HOST "grep -rh 'AUTH_TOKEN=' /root/.openclaw/workspace/workspace-mc-*/TOOLS.md /root/.openclaw/workspace/workspace-lead-*/TOOLS.md 2>/dev/null | sed 's/.*AUTH_TOKEN=//' | sed 's/\`//' | sort -u")

count=0
for token in $TOKENS; do
    [ -z "$token" ] && continue
    name=$(curl -s -X POST "$MC_API/api/v1/agent/heartbeat" -H "X-Agent-Token: $token" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','?'))" 2>/dev/null || echo "?")
    if [ -n "$name" ] && [ "$name" != "?" ]; then
        count=$((count + 1))
    fi
done
echo "  $count agents checked in"

echo ""
echo "=== Done. Board is live: heartbeats ON, sessions fresh, agents online. ==="
