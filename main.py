"""Entry point for the Zenith runtime.

Performs startup checks, prints a startup banner, and idles until the
process receives a shutdown signal (Ctrl+C).
"""

from __future__ import annotations

import logging
import time
import tomllib
from pathlib import Path

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

CONFIG_PATH = Path("configs/config.toml")

logger = logging.getLogger("zenith")


def init_logging() -> None:
    """Configure basic logging for the runtime."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def print_banner() -> None:
    """Print the Zenith startup banner."""
    print(BANNER)


def verify_required_folders(base_path: Path) -> None:
    """Verify that all required top-level folders exist.

    Raises:
        FileNotFoundError: If any required folder is missing.
    """
    missing = [
        name for name in REQUIRED_FOLDERS if not (base_path / name).is_dir()
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing required folder(s): {', '.join(missing)}"
        )
    logger.info("All required folders present.")


def load_configuration(config_path: Path) -> dict:
    """Load configuration from a TOML file if it exists.

    Returns an empty dict if no configuration file is present.
    """
    if not config_path.is_file():
        logger.info("No configuration file found at %s; using defaults.", config_path)
        return {}

    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)
    logger.info("Loaded configuration from %s.", config_path)
    return config


def idle_loop() -> None:
    """Idle until interrupted, then return to allow graceful shutdown."""
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received.")


def main() -> None:
    """Run the Zenith runtime."""
    init_logging()
    print_banner()

    base_path = Path(__file__).resolve().parent
    verify_required_folders(base_path)
    load_configuration(CONFIG_PATH)

    print("Zenith Runtime Started")
    idle_loop()
    print("Zenith Runtime Stopped")


if __name__ == "__main__":
    main()
