"""Serve the API over real HTTP with every outside call faked.

`python -m loadtests.server --port 8765 --profile realistic`, with
`JWT_SIGNING_KEY` set in the environment: the load runner mints its tokens with
the same key. `loadtests.run` starts this itself unless given `--base-url`.
The lifespan is off: it would open Postgres, and `fake_backend` replaces
everything it builds.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from api.app import app
from loadtests.fakes import LatencyProfile, fake_backend

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# `instant` measures this service alone; `realistic` holds each turn open about
# as long as production's providers do, so concurrent turns pile up as they
# would there.
PROFILES = {
    "instant": LatencyProfile(),
    "realistic": LatencyProfile(
        llm_first_token=0.8, llm_per_token=0.02, search=0.6, fetch=0.3, db=0.003
    ),
}


def main() -> None:
    """Parse the flags and serve until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="realistic")
    args = parser.parse_args()
    if not os.environ.get("JWT_SIGNING_KEY"):
        sys.exit("JWT_SIGNING_KEY must be set: the load runner signs with it too.")
    logging.basicConfig(level=logging.WARNING)
    with fake_backend(PROFILES[args.profile]):
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            lifespan="off",
            log_level="warning",
            access_log=False,
        )


if __name__ == "__main__":
    main()
