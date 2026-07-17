"""Console logging configuration for the Zenith runtime.

Uses only the standard library `logging` module.
"""

from __future__ import annotations

import logging

LOGGER_NAME = "zenith"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(debug: bool = False) -> logging.Logger:
    """Configure console logging and return the Zenith logger.

    Args:
        debug: If True, use DEBUG level instead of the INFO default.

    Returns:
        The configured "zenith" logger.
    """
    level = logging.DEBUG if debug else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(level)

    return logging.getLogger(LOGGER_NAME)
