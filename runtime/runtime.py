"""Application lifecycle owner for the Zenith runtime."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from configs.config import Config, load_config
from runtime.context import ApplicationContext
from runtime.events.lifecycle_events import (
    ApplicationStarted,
    ApplicationStarting,
    ApplicationStartupFailed,
    ApplicationStopped,
    ApplicationStopping,
    ConfigurationLoaded,
    ConfigurationLoadFailed,
)
from runtime.exceptions import ConfigurationError, ZenithRuntimeError
from runtime.logging_setup import configure_logging
from runtime.state import RuntimeState
from runtime.utils.fs_utils import directory_exists
from runtime.validation import validate_config, validate_path_exists

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

SOURCE = "runtime"


class Runtime:
    """Owns the Zenith application lifecycle.

    Responsible for creating the `ApplicationContext`, loading
    configuration, initializing logging, verifying the project layout,
    running the idle loop, and emitting lifecycle events through the
    context's `EventBus`. Transitions the context's `RuntimeState` as it
    runs.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        """Create a Runtime.

        Args:
            base_path: Root directory of the project. Defaults to the
                directory containing this package's parent (the project
                root).
        """
        self.base_path: Path = base_path or Path(__file__).resolve().parent.parent
        self.context: ApplicationContext = ApplicationContext(
            config=Config(),
            logger=logging.getLogger("zenith"),
        )

    @property
    def state(self) -> RuntimeState:
        """The runtime's current lifecycle state."""
        return self.context.state

    def start(self) -> None:
        """Load configuration, initialize logging, and verify the project layout.

        Emits `ApplicationStarting` before setup begins, `ApplicationStarted`
        once the runtime is running, `ConfigurationLoaded` /
        `ConfigurationLoadFailed` around configuration loading, and
        `ApplicationStartupFailed` if the project layout check fails.

        Raises:
            ConfigurationError: If configuration exists but cannot be parsed.
            ZenithRuntimeError: If a required project folder is missing.
        """
        self.context.state = RuntimeState.STARTING
        self.context.events.emit(ApplicationStarting(source=SOURCE))

        try:
            self._load_configuration()
        except ConfigurationError:
            self.context.state = RuntimeState.FAILED
            raise

        self.context.logger = configure_logging(debug=self.context.config.debug)
        self.context.logger.info("Starting Zenith runtime.")
        print(BANNER)

        try:
            self._verify_required_folders()
        except ZenithRuntimeError as exc:
            self.context.state = RuntimeState.FAILED
            self.context.events.emit(
                ApplicationStartupFailed(source=SOURCE, payload={"reason": str(exc)})
            )
            raise

        self.context.state = RuntimeState.RUNNING
        self.context.logger.info("Zenith runtime started.")
        print("Zenith Runtime Started")
        self.context.events.emit(ApplicationStarted(source=SOURCE))

    def run(self) -> None:
        """Start the runtime and idle until interrupted, then stop.

        Ctrl+C during the idle loop triggers a graceful shutdown.
        """
        try:
            self.start()
            self._idle()
        except KeyboardInterrupt:
            self.context.logger.info("Shutdown signal received.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Perform graceful shutdown.

        Emits `ApplicationStopping` before teardown and `ApplicationStopped`
        once it completes. Safe to call more than once. A no-op if the
        runtime never reached RUNNING (state is STOPPED or FAILED) — there
        is nothing running to gracefully stop.
        """
        if self.context.state in (RuntimeState.STOPPED, RuntimeState.FAILED):
            return

        self.context.state = RuntimeState.STOPPING
        self.context.events.emit(ApplicationStopping(source=SOURCE))
        self.context.logger.info("Stopping Zenith runtime.")

        self.context.state = RuntimeState.STOPPED
        self.context.logger.info("Zenith runtime stopped.")
        print("Zenith Runtime Stopped")
        self.context.events.emit(ApplicationStopped(source=SOURCE))

    def _load_configuration(self) -> None:
        """Load and validate configuration, emitting the outcome as an event."""
        config_path = self.base_path / "configs" / "config.toml"
        try:
            config = load_config(config_path)
        except ConfigurationError as exc:
            self.context.events.emit(
                ConfigurationLoadFailed(source=SOURCE, payload={"reason": str(exc)})
            )
            raise

        validate_config(config)
        self.context.config = config
        self.context.events.emit(
            ConfigurationLoaded(source=SOURCE, payload={"debug": config.debug})
        )

    def _idle(self) -> None:
        """Block until the runtime is no longer in the RUNNING state."""
        while self.context.state == RuntimeState.RUNNING:
            time.sleep(1)

    def _verify_required_folders(self) -> None:
        """Verify that all required top-level project folders exist.

        Raises:
            ZenithRuntimeError: If any required folder is missing.
        """
        validate_path_exists(self.base_path, must_be_dir=True)

        missing = [
            name for name in REQUIRED_FOLDERS if not directory_exists(self.base_path / name)
        ]
        if missing:
            raise ZenithRuntimeError(
                f"Missing required folder(s): {', '.join(missing)}"
            )
        self.context.logger.info("All required folders present.")
