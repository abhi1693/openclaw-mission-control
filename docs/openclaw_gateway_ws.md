# Gateway WebSocket protocol

## Connection Types

OpenClaw Mission Control supports both secure (`wss://`) and non-secure (`ws://`) WebSocket connections to gateways.

### Secure Connections (wss://)

For production environments, always use `wss://` (WebSocket Secure) connections with valid TLS certificates.

### Self-Signed Certificates

For local development or trusted local networks, you can enable support for self-signed TLS certificates:

1. Navigate to the gateway configuration page (Settings → Gateways)
2. When creating or editing a gateway, check the box: **"Allow self-signed TLS certificates"**
3. This option is useful for:
   - Local development: `wss://localhost:18789`
   - Trusted local networks: `wss://192.168.1.100:18789`

**Security Warning**: Only enable this option for localhost or gateways on trusted local networks. Do not use self-signed certificates for production gateways accessible over the internet.

## Configuration Options

When configuring a gateway, you can specify:

- **Gateway URL**: The WebSocket endpoint (e.g., `wss://localhost:18789` or `ws://gateway:18789`)
- **Gateway Token**: Optional authentication token
- **Workspace Root**: The root directory for gateway files (e.g., `~/.openclaw`)
- **Allow self-signed TLS certificates**: Enable/disable self-signed certificate support (default: disabled)

