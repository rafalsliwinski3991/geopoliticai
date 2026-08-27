"""Backward-compatible entrypoint for the GeopoliticAI CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app" / "src"))

from cli import main  # noqa: E402

if __name__ == "__main__":
    main()
