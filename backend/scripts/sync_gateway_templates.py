from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.db.session import async_session_maker
from app.models.gateways import Gateway
from app.services.template_sync import sync_gateway_templates


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync templates/ to existing OpenClaw gateway agent workspaces."
    )
    parser.add_argument("--gateway-id", type=str, required=True, help="Gateway UUID")
    parser.add_argument("--board-id", type=str, default=None, help="Optional Board UUID filter")
    parser.add_argument(
        "--include-main",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also sync the gateway main agent (default: true)",
    )
    parser.add_argument(
        "--reset-sessions",
        action="store_true",
        help="Reset agent sessions after syncing files (forces agents to re-read workspace)",
    )
    parser.add_argument(
        "--rotate-tokens",
        action="store_true",
        help="Rotate agent tokens when TOOLS.md is missing/unreadable or token drift is detected",
    )
    parser.add_argument(
        "--force-bootstrap",
        action="store_true",
        help="Force BOOTSTRAP.md to be provisioned during sync",
    )
    return parser.parse_args()


async def _run() -> int:
    args = _parse_args()
    gateway_id = UUID(args.gateway_id)
    board_id = UUID(args.board_id) if args.board_id else None

    async with async_session_maker() as session:
        gateway = await session.get(Gateway, gateway_id)
        if gateway is None:
            raise SystemExit(f"Gateway not found: {gateway_id}")

        result = await sync_gateway_templates(
            session,
            gateway,
            user=None,
            include_main=bool(args.include_main),
            reset_sessions=bool(args.reset_sessions),
            rotate_tokens=bool(args.rotate_tokens),
            force_bootstrap=bool(args.force_bootstrap),
            board_id=board_id,
        )

    print(f"gateway_id={result.gateway_id}")
    print(f"include_main={result.include_main} reset_sessions={result.reset_sessions}")
    print(
        f"agents_updated={result.agents_updated} agents_skipped={result.agents_skipped} main_updated={result.main_updated}"
    )
    if result.errors:
        print("errors:")
        for err in result.errors:
            agent = f"{err.agent_name} ({err.agent_id})" if err.agent_id else "n/a"
            print(f"- agent={agent} board_id={err.board_id} message={err.message}")
        return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
