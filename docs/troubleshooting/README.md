# Troubleshooting

## Guides

- [Frequently Asked Questions (FAQ)](./faq.md) - Common questions and quick solutions
- [Gateway agent provisioning and check-in](./gateway-agent-provisioning.md) - Detailed agent lifecycle debugging

## Quick Fixes

| Issue | Quick Check |
|-------|-------------|
| Frontend can't reach backend | Check `NEXT_PUBLIC_API_URL` is browser-reachable |
| Auth errors | Verify `AUTH_MODE` and `LOCAL_AUTH_TOKEN` (≥50 chars) |
| DB connection issues | Check `postgres_data` volume exists and is not corrupted |
| Gateway connection refused | Verify `openclaw gateway status` and firewall rules |
| Agent offline | Check queue worker is running (`docker compose ps`) |

## Getting Help

1. Check the [FAQ](./faq.md) for common issues
2. Review the detailed guides above
3. Search [existing issues](https://github.com/abhi1693/openclaw-mission-control/issues)
4. Join the [Slack community](https://join.slack.com/t/oc-mission-control/)

> **Note**
> When reporting issues, include Mission Control version, OpenClaw version, and relevant logs.
