"""Entry point for the Zenith runtime."""

from __future__ import annotations

from runtime.runtime import Runtime


def main() -> None:
    """Create and run the Zenith runtime."""
    Runtime().run()


if __name__ == "__main__":
    main()
