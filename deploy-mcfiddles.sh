#!/bin/bash
# Deploy Mission Control to mcfiddles.ai VM
#
# This script deploys Mission Control alongside the existing OpenClaw platform.
# Mission Control runs in Docker and is accessed through the platform's /control/* proxy.
#
# Prerequisites:
# 1. SSH access to the VM (35.193.148.179)
# 2. Docker and docker-compose installed on the VM
# 3. .env.mcfiddles configured with secure tokens/passwords
#
# Usage:
#   ./deploy-mcfiddles.sh

set -euo pipefail

# Configuration
VM_IP="35.193.148.179"
VM_USER="${VM_USER:-justinkline}"
DEPLOY_DIR="/opt/mission-control"

echo "=== Mission Control Deployment for mcfiddles.ai ==="

# Check for configured env file (prefer .env.production, fallback to .env.mcfiddles)
ENV_FILE=""
if [[ -f ".env.production" ]] && ! grep -q "CHANGE_ME" .env.production 2>/dev/null; then
    ENV_FILE=".env.production"
elif [[ -f ".env.mcfiddles" ]] && ! grep -q "CHANGE_ME" .env.mcfiddles 2>/dev/null; then
    ENV_FILE=".env.mcfiddles"
else
    echo "ERROR: No configured env file found."
    echo "Please configure .env.production or .env.mcfiddles with secure values."
    echo "Replace CHANGE_ME placeholders with secure passwords and tokens."
    echo ""
    echo "Generate a secure token with:"
    echo "  openssl rand -base64 64 | tr -d '\\n' | head -c 64"
    exit 1
fi
echo "Using env file: $ENV_FILE"

echo "1. Creating deployment directory on VM..."
ssh "${VM_USER}@${VM_IP}" "sudo mkdir -p ${DEPLOY_DIR} && sudo chown ${VM_USER}:${VM_USER} ${DEPLOY_DIR}"

echo "2. Copying files to VM..."
# Copy necessary files
scp -r ./backend "${VM_USER}@${VM_IP}:${DEPLOY_DIR}/"
scp -r ./frontend "${VM_USER}@${VM_IP}:${DEPLOY_DIR}/"
scp ./compose.mcfiddles.yml "${VM_USER}@${VM_IP}:${DEPLOY_DIR}/compose.yml"
scp "./${ENV_FILE}" "${VM_USER}@${VM_IP}:${DEPLOY_DIR}/.env"

echo "3. Building and starting Mission Control..."
ssh "${VM_USER}@${VM_IP}" "cd ${DEPLOY_DIR} && docker compose -f compose.yml --env-file .env up -d --build"

echo "4. Checking status..."
ssh "${VM_USER}@${VM_IP}" "cd ${DEPLOY_DIR} && docker compose -f compose.yml ps"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Mission Control is now running on the VM:"
echo "  Backend:  http://localhost:8100 (internal)"
echo "  Frontend: http://localhost:3100 (internal)"
echo ""
echo "Next steps:"
echo "1. Add the following environment variables to the OpenClaw platform deployment:"
echo "   OPENCLAW_MISSION_CONTROL_URL=http://localhost:8100"
echo "   OPENCLAW_MISSION_CONTROL_FRONTEND_URL=http://localhost:3100"
echo "   OPENCLAW_MISSION_CONTROL_AUTH_TOKEN=<same token from .env.mcfiddles>"
echo ""
echo "2. Redeploy the platform to pick up the new settings."
echo ""
echo "3. Access Mission Control at: https://mcfiddles.ai/control/"
