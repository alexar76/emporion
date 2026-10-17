"""Run EMPORION: python -m emporion.main (port EMPORION_PORT, default 9351)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn

from emporion.app import build_app
from emporion.capabilities import Runtime
from emporion.sanctions import SanctionsService
from emporion.timers import TimerService


def main() -> None:
    logging.basicConfig(level=os.environ.get("EMPORION_LOG_LEVEL", "INFO"))
    # The last good sanctions lists live beside the signing key, in the one writable volume.
    key = Path(os.environ.get("EMPORION_SIGNING_KEY_PATH", "data/emporion_signing_key"))
    cache = os.environ.get("EMPORION_CACHE_DIR") or str(key.parent / "cache")
    timers = TimerService(os.environ.get("EMPORION_TIMERS_DB") or str(key.parent / "timers.sqlite"))
    runtime = Runtime(sanctions=SanctionsService(cache_dir=cache), timers=timers)
    runtime.sanctions.start()  # first load in the background; screens refuse until it lands
    timers.start()  # delivers due timers every 2 s; the signer is attached by build_app
    uvicorn.run(build_app(runtime), host=os.environ.get("EMPORION_HOST", "0.0.0.0"),
                port=int(os.environ.get("EMPORION_PORT", "9351")),
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
