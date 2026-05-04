"""Repository-root shim entrypoint.

Use this only for backward compatibility; the live application lives under app/src.
"""

from cli import main

if __name__ == "__main__":
    main()
