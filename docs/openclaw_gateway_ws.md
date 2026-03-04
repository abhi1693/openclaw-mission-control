# Gateway WebSocket protocol

## Connection Types

OpenClaw Mission Control supports both secure (`wss://`) and non-secure (`ws://`) WebSocket connections to gateways.

### Secure Connections (wss://)

For production environments, always use `wss://` (WebSocket Secure) connections with valid TLS certificates.

### Self-Signed Certificates

You can enable support for self-signed TLS certificates with a toggle:

1. Navigate to the gateway configuration page (Settings → Gateways)
2. When creating or editing a gateway, enable: **"Allow self-signed TLS certificates"**
3. This applies to any `wss://` gateway URL for that gateway configuration.

When enabled, Mission Control skips TLS certificate verification for that gateway connection.

**Security Warning**: Enabling this weakens transport security and should only be used when you explicitly trust the endpoint and network path. Prefer valid CA-signed certificates for production gateways.

## Configuration Options

When configuring a gateway, you can specify:

- **Gateway URL**: The WebSocket endpoint (e.g., `wss://localhost:18789` or `ws://gateway:18789`)
- **Gateway Token**: Optional authentication token. Tokens are currently returned in API responses; a future release will redact them from read endpoints. Treat gateway API responses as sensitive and store tokens securely.
- **Workspace Root**: The root directory for gateway files (e.g., `~/.openclaw`)
- **Allow self-signed TLS certificates**: Toggle TLS certificate verification off for this gateway's `wss://` connections (default: disabled)
