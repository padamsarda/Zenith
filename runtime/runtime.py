"""Application lifecycle owner for the Zenith runtime."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from configs.config import Config, load_config
from runtime.exceptions import ZenithRuntimeError
from runtime.logging_setup import configure_logging
from runtime.state import RuntimeState

BANNER = r"""
 _____              _ _   _
|__  /___ _ __  ___(_) |_| |__
  / // _ \ '_ \/ __| | __| '_ \
 / /|  __/ | | \__ \ | |_| | | |
/____\___|_| |_|___/_|\__|_| |_|
"""

REQUIRED_FOLDERS: tuple[str, ...] = (
    "runtime",
    "plugins",
    "configs",
    "architecture",
    "docs",
    "tests",
)


class Runtime:
    """Owns the Zenith application lifecycle.

    Responsible for configuration loading, logging setup, startup and
    shutdown sequencing, and the idle loop. Transitions through
    `RuntimeState` values as it runs.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        """Create a Runtime.

        Args:
            base_path: Root directory of the project. Defaults to the
                directory containing this package's parent (the project
                root).
        """
        self.base_path: Path = base_path or Path(__file__).resolve().parent.parent
        self.state: RuntimeState = RuntimeState.INITIALIZING
        self.config: Config = Config()
        self.logger: logging.Logger = logging.getLogger("zenith")

    def start(self) -> None:
        """Load configuration, initialize logging, and verify the project layout.

        Raises:
            ZenithRuntimeError: If a required project folder is missing.
        """
        self.state = RuntimeState.STARTING

        self.config = load_config(self.base_path / "configs" / "config.toml")
        self.logger = configure_logging(debug=self.config.debug)
        self.logger.info("Starting Zenith runtime.")

        print(BANNER)
        self._verify_required_folders()

        self.state = RuntimeState.RUNNING
        self.logger.info("Zenith runtime started.")
        print("Zenith Runtime Started")

    def run(self) -> None:
        """Start the runtime and idle until interrupted, then stop.

        Ctrl+C during the idle loop triggers a graceful shutdown.
        """
        try:
            self.start()
            self._idle()
        except KeyboardInterrupt:
            self.logger.info("Shutdown signal received.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Perform graceful shutdown."""
        if self.state == RuntimeState.STOPPED:
            return

        self.state = RuntimeState.STOPPING
        self.logger.info("Stopping Zenith runtime.")

        self.state = RuntimeState.STOPPED
        self.logger.info("Zenith runtime stopped.")
        print("Zenith Runtime Stopped")

    def _idle(self) -> None:
        """Block until the runtime is no longer in the RUNNING state."""
        while self.state == RuntimeState.RUNNING:
            time.sleep(1)

    def _verify_required_folders(self) -> None:
        """Verify that all required top-level project folders exist.

        Raises:
            ZenithRuntimeError: If any required folder is missing.
        """
        missing = [
            name
            for name in REQUIRED_FOLDERS
            if not (self.base_path / name).is_dir()
        ]
        if missing:
            self.state = RuntimeState.FAILED
            raise ZenithRuntimeError(
                f"Missing required folder(s): {', '.join(missing)}"
            )
        self.logger.info("All required folders present.")
