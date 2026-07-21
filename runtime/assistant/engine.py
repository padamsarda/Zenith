"""AssistantEngine: drives one request from user text to assistant reply."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING

from runtime.assistant.assembler import AssistantContextAssembler
from runtime.assistant.events import RequestCompleted, RequestFailed, RequestReceived
from runtime.assistant.permissions import AllowAllPolicy, PermissionPolicy
from runtime.assistant.response import AssistantResponse
from runtime.assistant.status import TERMINAL_STATUSES, RequestStatus
from runtime.assistant.tool_runner import ToolCallRunner
from runtime.assistant.validation import validate_request, validate_turn
from runtime.conversation.message import Message, MessageRole
from shared.exceptions import ZenithError

if TYPE_CHECKING:
    from runtime.assistant.hooks import AssistantHook
    from runtime.assistant.request import AssistantRequest
    from runtime.context import ApplicationContext
    from runtime.providers.base import AssistantProvider

DEFAULT_LOGGER_NAME = "zenith.assistant"
SOURCE = "assistant_engine"


class AssistantEngine:
    """Serves assistant requests through one deterministic pipeline.

    For each request: run `before_request` hooks, validate, resolve the
    conversation and provider, record the user message, then loop —
    assemble a brief, ask the provider for a turn, execute any tool
    calls it requests (each through the `ToolCallRunner`, gated by the
    `PermissionPolicy` and `before_tool` hooks), and finish when a turn
    carries no tool calls. Every outcome becomes an
    `AssistantResponse`; `handle` never raises — a provider bug, a tool
    failure, or a validation error degrades to a failed response, not a
    crashed runtime.

    The engine holds no per-request state: everything it needs arrives
    with the call, mirroring `CommandExecutor.execute`. Its two
    configuration seams are `set_permission_policy` and `add_hook`.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        assembler: AssistantContextAssembler | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        self._assembler = assembler or AssistantContextAssembler()
        self._runner = ToolCallRunner(logger=self._logger)
        self._policy: PermissionPolicy = AllowAllPolicy()
        self._hooks: list[AssistantHook] = []

    @property
    def permission_policy(self) -> PermissionPolicy:
        """The policy consulted before every tool call."""
        return self._policy

    def set_permission_policy(self, policy: PermissionPolicy) -> None:
        """Replace the permission policy consulted before every tool call."""
        self._policy = policy

    def add_hook(self, hook: AssistantHook) -> None:
        """Attach `hook` to the pipeline. Hooks run in the order added."""
        self._hooks.append(hook)

    def handle(
        self, request: AssistantRequest, application_context: ApplicationContext
    ) -> AssistantResponse:
        """Serve `request` and return the outcome as an `AssistantResponse`.

        Emits `RequestReceived` on entry and exactly one of
        `RequestCompleted` or `RequestFailed` on exit. Never raises.
        """
        start = perf_counter()
        application_context.events.emit(
            RequestReceived(
                source=SOURCE,
                payload={
                    "request_id": str(request.request_id),
                    "conversation_id": str(request.conversation_id),
                },
            )
        )
        for hook in self._hooks:
            try:
                hook.before_request(request, application_context)
            except Exception as exc:
                return self._fail(
                    request, application_context, f"Request rejected: {exc}", exc, start, 0
                )
        try:
            validate_request(request)
            application_context.conversations.get(request.conversation_id)
            provider = self._resolve_provider(request, application_context)
            request.transition_to(RequestStatus.RUNNING)
            self._record(request, MessageRole.USER, request.text, application_context)
        except ZenithError as exc:
            return self._fail(request, application_context, str(exc), exc, start, 0)

        max_turns = application_context.config.assistant_max_turns
        turns = 0
        while turns < max_turns:
            turns += 1
            try:
                # Re-fetched every turn, not held across the loop: a
                # ConversationStore is durable state (ADR 0010), and a
                # backend that reconstructs Conversation objects from
                # storage (e.g. SQLiteConversationStore) would otherwise
                # hand the provider a brief missing every message
                # appended since the loop's first fetch.
                conversation = application_context.conversations.get(request.conversation_id)
                brief = self._assembler.assemble(request, conversation, application_context)
                turn = provider.generate_turn(brief)
                validate_turn(turn)
            except ZenithError as exc:
                return self._fail(request, application_context, str(exc), exc, start, turns)
            except Exception as exc:  # a buggy provider must not crash the runtime
                reason = f"Provider '{provider.provider_id}' raised unexpectedly: {exc}"
                return self._fail(request, application_context, reason, exc, start, turns)

            if turn.text is not None:
                self._record(request, MessageRole.ASSISTANT, turn.text, application_context)
            if not turn.tool_calls:
                return self._complete(request, application_context, turn.text, start, turns)
            for call in turn.tool_calls:
                self._runner.run(
                    request,
                    call,
                    application_context,
                    policy=self._policy,
                    hooks=tuple(self._hooks),
                )

        reason = f"No final reply after {max_turns} turns."
        return self._fail(request, application_context, reason, None, start, turns)

    def _resolve_provider(
        self, request: AssistantRequest, application_context: ApplicationContext
    ) -> AssistantProvider:
        """Return the provider serving `request`: its named one, or the configured default."""
        provider_id = (
            request.metadata.get("provider") or application_context.config.assistant_provider
        )
        return application_context.assistant_providers.get(provider_id)

    def _record(
        self,
        request: AssistantRequest,
        role: MessageRole,
        content: str,
        application_context: ApplicationContext,
    ) -> None:
        """Append one message about `request` to its conversation."""
        application_context.conversations.append(
            request.conversation_id,
            Message(role=role, content=content, metadata={"request_id": str(request.request_id)}),
            application_context,
        )

    def _complete(
        self,
        request: AssistantRequest,
        application_context: ApplicationContext,
        text: str | None,
        start: float,
        turns: int,
    ) -> AssistantResponse:
        """Mark `request` COMPLETED, emit `RequestCompleted`, and build the response."""
        duration = perf_counter() - start
        request.transition_to(RequestStatus.COMPLETED)
        self._logger.info(
            "Request %s completed in %.3fs over %d turn(s).", request.request_id, duration, turns
        )
        application_context.events.emit(
            RequestCompleted(
                source=SOURCE,
                payload={
                    "request_id": str(request.request_id),
                    "duration_seconds": duration,
                    "turns": turns,
                },
            )
        )
        response = AssistantResponse(
            success=True,
            text=text or "",
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            duration_seconds=duration,
            turns=turns,
        )
        self._after_request(request, response, application_context)
        return response

    def _fail(
        self,
        request: AssistantRequest,
        application_context: ApplicationContext,
        reason: str,
        exc: BaseException | None,
        start: float,
        turns: int,
    ) -> AssistantResponse:
        """Mark `request` FAILED (if not terminal), emit `RequestFailed`, build the response."""
        duration = perf_counter() - start
        if request.status not in TERMINAL_STATUSES:
            request.transition_to(RequestStatus.FAILED)
        self._logger.error("Request %s failed: %s", request.request_id, reason)
        application_context.events.emit(
            RequestFailed(
                source=SOURCE,
                payload={"request_id": str(request.request_id), "reason": reason},
            )
        )
        response = AssistantResponse(
            success=False,
            text=reason,
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            duration_seconds=duration,
            turns=turns,
            exception=exc,
        )
        self._after_request(request, response, application_context)
        return response

    def _after_request(
        self,
        request: AssistantRequest,
        response: AssistantResponse,
        application_context: ApplicationContext,
    ) -> None:
        """Run `after_request` hooks; failures are logged, never propagated."""
        for hook in self._hooks:
            try:
                hook.after_request(request, response, application_context)
            except Exception:
                self._logger.warning("after_request hook failed.", exc_info=True)
