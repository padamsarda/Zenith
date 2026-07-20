"""Shared runtime resources used across the application."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from configs.config import Config
from runtime.assistant.engine import AssistantEngine
from runtime.capabilities.skill_registry import SkillRegistry
from runtime.capabilities.tool_registry import ToolRegistry
from runtime.commands.executor import CommandExecutor
from runtime.conversation.store import ConversationStore
from runtime.plugins.registry import PluginRegistry
from runtime.providers.registry import AssistantProviderRegistry
from runtime.registry import ServiceRegistry
from runtime.state import RuntimeState
from shared.events.bus import EventBus
from shared.utils.time_utils import utc_now

APPLICATION_VERSION = "0.1.0"


@dataclass
class ApplicationContext:
    """Holds the resources every subsystem needs instead of using globals.

    A single `ApplicationContext` is created and owned by the `Runtime`.
    Subsystems should be given the context (or the specific resource they
    need from it) rather than importing shared state directly. New shared
    resources belong here as the runtime grows.
    """

    config: Config
    logger: logging.Logger
    version: str = APPLICATION_VERSION
    started_at: datetime = field(default_factory=utc_now)
    state: RuntimeState = RuntimeState.INITIALIZING
    services: ServiceRegistry = field(default_factory=ServiceRegistry)
    events: EventBus = field(default_factory=EventBus)
    commands: CommandExecutor = field(default_factory=CommandExecutor)
    plugins: PluginRegistry = field(default_factory=PluginRegistry)
    conversations: ConversationStore = field(default_factory=ConversationStore)
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    skills: SkillRegistry = field(default_factory=SkillRegistry)
    assistant_providers: AssistantProviderRegistry = field(
        default_factory=AssistantProviderRegistry
    )
    assistant: AssistantEngine = field(default_factory=AssistantEngine)
