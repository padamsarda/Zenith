"""EngineeringWorkflowPlugin: the first genuine Skill, teaching a safe order
of operations for engineering tasks over the built-in tool suite (ADR 0016).

The reference example for `docs/plugins.md`'s loading convention: an
immediate subdirectory of `plugins/` with a `plugin.py` exposing
`create_plugin()`. Contributes only a `Skill` — never a `Tool` — so it
stays safe to load unconditionally at startup: skills are instructional
text with no permission question (ADR 0013), unlike a tool, which would
be free to act under whatever `PermissionPolicy` a deployment has
configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.capabilities.skill import Skill
from runtime.plugins.manifest import PluginManifest
from runtime.plugins.plugin import Plugin

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest
    from runtime.context import ApplicationContext
    from runtime.plugins.context import PluginContext
    from runtime.plugins.registry import PluginRegistry

PLUGIN_ID = "engineering-workflow"
SKILL_ID = "engineering-workflow"

INSTRUCTIONS = """\
When a request asks you to change code in a project, prefer this order \
of operations over editing blind:

1. Inspect before you write. Read the file (or run a status/diff check) \
so your change is grounded in what is actually there, not assumed.
2. Prefer the smallest change that satisfies the request. Do not \
restructure, rename, or "clean up" code the request did not ask about.
3. Review your own edit as a diff before treating the task as done, the \
same way a careful engineer reviews a patch before sending it.
4. Run the project's tests after changing code that has them, and read \
the failures rather than assuming green.
5. Leave the working tree in a state you could hand to a human reviewer: \
no partial edits, no unrelated changes swept in.

If your tool catalog includes `filesystem`, `shell`, `git`, `diff`, and \
`test_runner` tools, they map directly to these steps: `filesystem` or \
`git status`/`git diff` for step 1, `diff` or `git diff` for step 3, and \
`test_runner` for step 4. If a given deployment has not registered one \
of them, follow the same order of operations with whatever capabilities \
you do have."""


class EngineeringWorkflowSkill(Skill):
    """Instructs the provider to inspect, minimize, review, and test.

    Deliberately generic rather than tied to this repository's own
    conventions (`CLAUDE.md`) — a skill's instructions must stay valid
    for whatever project the assistant is pointed at, not just this one.
    """

    @property
    def skill_id(self) -> str:
        return SKILL_ID

    @property
    def name(self) -> str:
        return "Engineering Workflow"

    @property
    def description(self) -> str:
        return (
            "Teaches a safe order of operations for code-change tasks: "
            "inspect before writing, keep changes minimal, review the diff, "
            "run tests, and leave a clean working tree."
        )

    def instructions(self, request: AssistantRequest) -> str:
        """Return the fixed workflow instructions; the same for every request."""
        return INSTRUCTIONS


class EngineeringWorkflowPlugin(Plugin):
    """Registers `EngineeringWorkflowSkill` on the assistant's `SkillRegistry`.

    `register`/`unregister` need `ApplicationContext.skills`, which only
    `PluginContext` (passed to `initialize`/`shutdown`) carries — so the
    context is captured there and used from `register`/`unregister`,
    the same shape any plugin contributing tools or skills will need.
    """

    def __init__(self) -> None:
        super().__init__(
            PluginManifest(
                plugin_id=PLUGIN_ID,
                name="Engineering Workflow",
                version="1.0.0",
                description=(
                    "Teaches the assistant a safe order of operations for "
                    "engineering tasks: inspect, minimize, review, test."
                ),
                author="Zenith",
            )
        )
        self._skill = EngineeringWorkflowSkill()
        self._application_context: ApplicationContext | None = None

    def initialize(self, context: PluginContext) -> None:
        """Capture the ApplicationContext register/unregister will need."""
        self._application_context = context.application_context

    def shutdown(self, context: PluginContext) -> None:
        """Release the captured ApplicationContext."""
        self._application_context = None

    def register(self, registry: PluginRegistry) -> None:
        """Register `EngineeringWorkflowSkill` on the assistant's SkillRegistry.

        `PluginRegistry.register` always calls `initialize` first, so
        `self._application_context` is set by the time this runs.
        """
        context = self._application_context
        context.skills.register(self._skill, context)

    def unregister(self, registry: PluginRegistry) -> None:
        """Remove `EngineeringWorkflowSkill` from the assistant's SkillRegistry."""
        context = self._application_context
        context.skills.unregister(self._skill.skill_id, context)


def create_plugin() -> Plugin:
    """Factory `PluginLoader` calls to construct this plugin.

    The convention every plugin's `plugin.py` follows — see
    `docs/plugins.md`.
    """
    return EngineeringWorkflowPlugin()
