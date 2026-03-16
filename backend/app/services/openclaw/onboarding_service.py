"""Board onboarding gateway messaging service."""

from __future__ import annotations

from app.core.logging import TRACE_LEVEL
from app.models.board_onboarding import BoardOnboardingSession
from app.models.boards import Board
from app.services.openclaw.coordination_service import AbstractGatewayMessagingService
from app.services.openclaw.exceptions import GatewayOperation, map_gateway_error_to_http_exception
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.shared import GatewayAgentIdentity


class BoardOnboardingMessagingService(AbstractGatewayMessagingService):
    """Gateway message dispatch helpers for onboarding routes."""

    async def dispatch_start_prompt(
        self,
        *,
        board: Board,
        prompt: str,
        correlation_id: str | None = None,
    ) -> str:
        trace_id = GatewayDispatchService.resolve_trace_id(
            correlation_id, prefix="onboarding.start"
        )
        self.logger.log(
            TRACE_LEVEL,
            "gateway.onboarding.start_dispatch.start trace_id=%s board_id=%s",
            trace_id,
            board.id,
        )
        gateway, config = await GatewayDispatchService(
            self.session
        ).require_gateway_config_for_board(board)
        session_key = GatewayAgentIdentity.session_key(gateway)
        try:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name="Gateway Agent",
                message=prompt,
                deliver=False,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.onboarding.start_dispatch.failed trace_id=%s board_id=%s error=%s",
                trace_id,
                board.id,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(
                GatewayOperation.ONBOARDING_START_DISPATCH,
                exc,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            self.logger.critical(
                "gateway.onboarding.start_dispatch.failed_unexpected trace_id=%s board_id=%s "
                "error_type=%s error=%s",
                trace_id,
                board.id,
                exc.__class__.__name__,
                str(exc),
            )
            raise
        self.logger.info(
            "gateway.onboarding.start_dispatch.success trace_id=%s board_id=%s session_key=%s",
            trace_id,
            board.id,
            session_key,
        )
        return session_key

    async def dispatch_answer(
        self,
        *,
        board: Board,
        onboarding: BoardOnboardingSession,
        answer_text: str,
        correlation_id: str | None = None,
    ) -> None:
        trace_id = GatewayDispatchService.resolve_trace_id(
            correlation_id, prefix="onboarding.answer"
        )
        self.logger.log(
            TRACE_LEVEL,
            "gateway.onboarding.answer_dispatch.start trace_id=%s board_id=%s onboarding_id=%s",
            trace_id,
            board.id,
            onboarding.id,
        )
        _gateway, config = await GatewayDispatchService(
            self.session
        ).require_gateway_config_for_board(board)
        try:
            await self._dispatch_gateway_message(
                session_key=onboarding.session_key,
                config=config,
                agent_name="Gateway Agent",
                message=answer_text,
                deliver=False,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.onboarding.answer_dispatch.failed trace_id=%s board_id=%s "
                "onboarding_id=%s error=%s",
                trace_id,
                board.id,
                onboarding.id,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(
                GatewayOperation.ONBOARDING_ANSWER_DISPATCH,
                exc,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            self.logger.critical(
                "gateway.onboarding.answer_dispatch.failed_unexpected trace_id=%s board_id=%s "
                "onboarding_id=%s error_type=%s error=%s",
                trace_id,
                board.id,
                onboarding.id,
                exc.__class__.__name__,
                str(exc),
            )
            raise
        self.logger.info(
            "gateway.onboarding.answer_dispatch.success trace_id=%s board_id=%s onboarding_id=%s",
            trace_id,
            board.id,
            onboarding.id,
        )
