"""Entry point for `python -m engineering_manager`."""

from __future__ import annotations

import sys

from engineering_manager.cli import main

if __name__ == "__main__":
    sys.exit(main())
