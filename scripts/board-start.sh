#!/usr/bin/env bash
# board-start.sh — Re-enable heartbeats for all MC board agents
#
# Usage: bash scripts/board-start.sh
#
# What it does:
#   1. Restores heartbeat_config from _heartbeat_backup table in MC database
#   2. Sets agent status to 'online' (lifecycle orchestrator takes over from here)
#   3. Restores gateway openclaw.json from saved backup
#   4. Clears any leftover sessions (fresh start)
#   5. Restarts gateway to pick up new heartbeat timers
#   6. Runs Baileys group sync if WhatsApp groups are configured

set -euo pipefail

MC_DB_HOST="192.168.2.66"
MC_DB="mission_control"
MC_DB_USER="postgres"
MC_DB_PASS="postgres"
GATEWAY_HOST="192.168.2.60"
GATEWAY_CONFIG="/root/.openclaw/openclaw.json"
GATEWAY_AGENTS_DIR="/root/.openclaw/agents"

PSQL="PGPASSWORD=$MC_DB_PASS psql -U $MC_DB_USER -h 127.0.0.1 -d $MC_DB -t -A"

echo "=== Board Start ==="

# Step 1: Restore heartbeats in MC database
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

# Step 3: Restore gateway config
echo ""
echo "--- Step 3: Restoring gateway config ---"
ssh root@$GATEWAY_HOST "python3 -c \"
import json

backup_file = '$GATEWAY_CONFIG.heartbeat-backup'
try:
    with open(backup_file) as f:
        saved = json.load(f)
except FileNotFoundError:
    print('ERROR: No gateway backup found. Run board-stop.sh first.')
    exit(1)

with open('$GATEWAY_CONFIG') as f:
    data = json.load(f)

count = 0
for a in data.get('agents', {}).get('list', []):
    aid = a.get('id', '')
    if aid in saved:
        original = saved[aid]
        hb = a.get('heartbeat', {})
        if original == 'default':
            hb.pop('every', None)
        else:
            hb['every'] = original
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
for agent_dir in $GATEWAY_AGENTS_DIR/mc-*; do
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
keys = [k for k in data if 'mc-' in k]
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

echo ""
echo "=== Done. Board is live: heartbeats ON, sessions fresh, agents online. ==="
