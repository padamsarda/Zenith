"""MediaControlTool: simulates hardware media/volume keys."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import optional_int, require_str

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.media_control"
MAX_STEPS = 25

# Standard Windows virtual-key codes for the media/volume keys present on
# most keyboards. Sending one is indistinguishable to the OS (and to
# whatever app owns the active media session, e.g. Spotify) from a
# physical key press — no per-application integration needed.
_VIRTUAL_KEYS: dict[str, int] = {
    "play_pause": 0xB3,
    "next_track": 0xB0,
    "previous_track": 0xB1,
    "mute": 0xAD,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
}
ACTIONS = tuple(_VIRTUAL_KEYS)

_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002

KeySender = Callable[[int], None]


def default_key_sender(vk_code: int) -> None:
    """Press and release `vk_code` as a real hardware key would.

    Raises:
        ToolExecutionError: Off Windows, where there is no keyboard
            input queue to inject into — this fails loudly rather than
            silently doing nothing (the same principle ADR 0022 applies
            to a session that cannot act).
    """
    if sys.platform != "win32":
        raise ToolExecutionError("Media control requires Windows.")
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.keybd_event(vk_code, 0, _KEYEVENTF_EXTENDEDKEY, 0)
    user32.keybd_event(vk_code, 0, _KEYEVENTF_EXTENDEDKEY | _KEYEVENTF_KEYUP, 0)


@dataclass(frozen=True)
class MediaControlResult:
    """The structured outcome of one media control action."""

    action: str
    steps: int
    message: str

    def __str__(self) -> str:
        return self.message


class MediaControlTool(Tool):
    """Controls whatever application currently owns media playback.

    Sends the same virtual-key events a hardware media/volume key would,
    so it works with any app that already responds to them (Spotify,
    browsers, system volume) without per-application integration. There
    is no absolute volume level — `volume_up`/`volume_down` are relative
    steps, matching how the keys themselves work.
    """

    def __init__(
        self,
        *,
        key_sender: KeySender = default_key_sender,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a MediaControlTool.

        Args:
            key_sender: Sends one virtual-key press+release. Injectable
                so tests never touch the real keyboard input queue.
            logger: Defaults to a module logger.
        """
        self._key_sender = key_sender
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "media_control"

    @property
    def name(self) -> str:
        return "Media Control"

    @property
    def description(self) -> str:
        return "Controls media playback and volume: play/pause, skip, mute, volume up/down."

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="action",
                description=f"One of: {', '.join(ACTIONS)}.",
                required=True,
            ),
            ToolParameter(
                name="steps",
                description="For volume_up/volume_down: how many steps (default 1).",
                required=False,
                type="integer",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> MediaControlResult:
        """Perform one media control action.

        Raises:
            ToolExecutionError: If `action` is unrecognized, `steps` is
                out of range, or the platform cannot act (see
                `default_key_sender`).
        """
        action = require_str(arguments, "action")
        vk_code = _VIRTUAL_KEYS.get(action)
        if vk_code is None:
            raise ToolExecutionError(f"Unknown media action {action!r}; expected one of {ACTIONS}.")

        steps = optional_int(arguments, "steps", default=1)
        if not 1 <= steps <= MAX_STEPS:
            raise ToolExecutionError(f"'steps' must be between 1 and {MAX_STEPS}, got {steps}.")

        self._logger.info("Media control %s x%d", action, steps)
        for _ in range(steps):
            self._key_sender(vk_code)

        return MediaControlResult(
            action=action, steps=steps, message=f"Sent {action} x{steps}."
        )
