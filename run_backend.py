"""Entry point for the packaged backend (PyInstaller builds blackjack-backend.exe from this file)."""

import sys

from blackjack_assistant.server import main

if __name__ == "__main__":
    sys.exit(main())
