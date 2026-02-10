"""CLI script to sync template files into gateway agent workspaces."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync templates/ to existing OpenClaw gateway agent workspaces.",
    )
    parser.add_argument("--gateway-id", type=str, required=True, help="Gateway UUID")
    parser.add_argument(
        "--board-id",
        type=str,
        default=None,
        help="Optional Board UUID filter",
    )
    parser.add_argument(
        "--include-main",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also sync the gateway main agent (default: true)",
    )
    parser.add_argument(
        "--reset-sessions",
        action="store_true",
        help=("Reset agent sessions after syncing files " "(forces agents to re-read workspace)"),
    )
    parser.add_argument(
        "--rotate-tokens",
        action="store_true",
        help=(
            "Rotate agent tokens when TOOLS.md is missing/unreadable " "or token drift is detected"
        ),
    )
    parser.add_argument(
        "--force-bootstrap",
        action="store_true",
        help="Force BOOTSTRAP.md to be provisioned during sync",
    )
    return parser.parse_args()


async def _run() -> int:
    from app.db.session import async_session_maker
    from app.models.gateways import Gateway
    from app.services.openclaw import GatewayTemplateSyncOptions, sync_gateway_templates

    args = _parse_args()
    gateway_id = UUID(args.gateway_id)
    board_id = UUID(args.board_id) if args.board_id else None

    async with async_session_maker() as session:
        gateway = await session.get(Gateway, gateway_id)
        if gateway is None:
            message = f"Gateway not found: {gateway_id}"
            raise SystemExit(message)

        result = await sync_gateway_templates(
            session,
            gateway,
            options=GatewayTemplateSyncOptions(
                user=None,
                include_main=bool(args.include_main),
                reset_sessions=bool(args.reset_sessions),
                rotate_tokens=bool(args.rotate_tokens),
                force_bootstrap=bool(args.force_bootstrap),
                board_id=board_id,
            ),
        )

    sys.stdout.write(f"gateway_id={result.gateway_id}\n")
    sys.stdout.write(
        f"include_main={result.include_main} " f"reset_sessions={result.reset_sessions}\n",
    )
    sys.stdout.write(
        f"agents_updated={result.agents_updated} "
        f"agents_skipped={result.agents_skipped} "
        f"main_updated={result.main_updated}\n",
    )
    if result.errors:
        sys.stdout.write("errors:\n")
        for err in result.errors:
            agent = f"{err.agent_name} ({err.agent_id})" if err.agent_id else "n/a"
            sys.stdout.write(
                f"- agent={agent} board_id={err.board_id} message={err.message}\n",
            )
        return 1
    return 0


def main() -> None:
    """Run the async CLI workflow and exit with its return code."""
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
