"""Run SYMMARTYS: python -m symmartys.main (port SYMMARTYS_PORT, default 9351)."""

from __future__ import annotations

import logging

import uvicorn

from symmartys.app import build_app
from symmartys.capabilities import Runtime
from symmartys.sanctions import SanctionsService
from symmartys.bitcoin_headers import HeaderChain, HeaderService
from symmartys.timers import TimerService
from symmartys.config import setting, signing_key_path


def main() -> None:
    logging.basicConfig(level=setting("LOG_LEVEL", "INFO"))
    # The last good sanctions lists live beside the signing key, in the one writable volume.
    key = signing_key_path()
    cache = setting("CACHE_DIR") or str(key.parent / "cache")
    timers = TimerService(setting("TIMERS_DB") or str(key.parent / "timers.sqlite"))
    bitcoin = HeaderService(HeaderChain(setting("BTC_HEADERS")
                                        or str(key.parent / "bitcoin-headers.bin")))
    runtime = Runtime(sanctions=SanctionsService(cache_dir=cache), timers=timers,
                      bitcoin=bitcoin)
    runtime.sanctions.start()  # first load in the background; screens refuse until it lands
    timers.start()  # delivers due timers every 2 s; the signer is attached by build_app
    bitcoin.start()  # headers from the Bitcoin network; verify refuses until two nodes agree
    uvicorn.run(build_app(runtime), host=setting("HOST", "0.0.0.0"),
                port=int(setting("PORT", "9351")),
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
